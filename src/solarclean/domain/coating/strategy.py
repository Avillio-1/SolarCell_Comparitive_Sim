from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

import numpy as np
import pandas as pd

from solarclean.config.models import (
    BirdDroppingConfig,
    CoatingConfig,
    FarmConfig,
    PVSystemConfig,
    RainfallCleaningConfig,
    SoilingConfig,
)
from solarclean.domain.coating.costs import build_coating_cost_basis
from solarclean.domain.coating.physics import (
    CondensationResult,
    apply_bird_removal,
    calculate_condensation,
    calculate_energy_mechanisms,
    calculate_passive_dust_cleaning,
    calculate_surface_temperature_c,
)
from solarclean.domain.coating.state import CoatingCohortState, CoatingScenarioState
from solarclean.domain.contamination.soiling import (
    ContaminationState,
    KimberStyleSoilingModel,
    SimulationEvent,
)
from solarclean.domain.farm.representation import (
    advance_dust_ratio,
    restore_dust_ratio_after_rain,
)
from solarclean.domain.scenario.contracts import (
    DailyScenarioInput,
    DailyScenarioResult,
    DomainEvent,
    OperationalQuantities,
    ScenarioContext,
    StrategyStep,
)


class CoatingStrategy:
    name = "coating"

    def __init__(
        self,
        *,
        coating: CoatingConfig,
        soiling: SoilingConfig,
        rainfall: RainfallCleaningConfig,
        birds: BirdDroppingConfig,
        farm: FarmConfig,
        pv_system: PVSystemConfig,
    ) -> None:
        self.coating = coating
        if not coating.enabled:
            raise ValueError(
                "disabled coating configuration must use a baseline pass-through strategy"
            )
        self.soiling_model = KimberStyleSoilingModel(soiling, rainfall)
        self.birds = birds
        self.farm = farm
        if farm.representation != "cohort":
            raise ValueError("coating scenario requires farm.representation='cohort'")
        self.pv_system = pv_system
        self.cost_basis = build_coating_cost_basis(
            farm=farm,
            deployment=coating.deployment,
            costs=coating.costs,
        )

    def initial_state(
        self,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> CoatingScenarioState:
        del rng
        first_day = pd.Timestamp(str(next(iter(context.clean_energy.daily.index)))).date()
        cohorts = tuple(
            CoatingCohortState(
                cohort_id=cohort_id,
                panel_count=self.farm.panels_per_cohort,
                applied=self.coating.enabled,
                age_days=0,
                effectiveness_fraction=self.coating.physics.initial_effectiveness_fraction,
                degradation_fraction=0.0,
                dust_soiling_ratio=1.0,
                bird_drop_coverage_fraction=0.0,
                bird_drop_loss_fraction=0.0,
            )
            for cohort_id in range(self.farm.cohort_count)
        )
        return CoatingScenarioState(date=first_day, cohorts=cohorts)

    def simulate_day(
        self,
        day_input: DailyScenarioInput,
        state: object,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> StrategyStep:
        if not isinstance(state, CoatingScenarioState):
            raise TypeError("coating strategy state has the wrong type")
        hourly = context.weather.for_day(day_input.date)
        day_water = _daily_water(hourly, self.coating, self.cost_basis.total_coated_area_m2)
        condensed_per_m2 = (
            day_water.condensed_liters / self.cost_basis.total_coated_area_m2
            if self.cost_basis.total_coated_area_m2 > 0.0
            else 0.0
        )
        previous_average_dust = _average_dust(state.cohorts)
        base_update = self.soiling_model.update(
            ContaminationState(dust_soiling_ratio=previous_average_dust),
            day_input.environment,
            rng,
            event_inputs=day_input.event_inputs,
        )
        events = [
            DomainEvent.from_simulation_event(event, scenario_name=self.name)
            for event in base_update.events
        ]
        daily_loss, dust_event_loss = _dust_event_losses(base_update.events)
        energy_cohorts: list[CoatingCohortState] = []
        next_cohorts: list[CoatingCohortState] = []
        total_restored = 0.0
        total_bird_removed = 0.0
        passive_cleaning_day = False
        bird_removal_day = False
        for cohort in state.cohorts:
            effectiveness = _effectiveness_after_degradation(cohort, self.coating)
            if day_input.event_inputs is not None:
                variation = day_input.event_inputs.cohort_variation_multipliers.get(
                    cohort.cohort_id,
                    1.0,
                )
            else:
                variation = 1.0
            dust_ratio = advance_dust_ratio(
                cohort.dust_soiling_ratio,
                daily_loss_fraction=daily_loss,
                dust_event_loss_fraction=dust_event_loss,
                precipitation_mm=0.0,
                soiling=self.soiling_model.config,
                rainfall=self.soiling_model.rainfall,
                cohort_variation_multiplier=variation,
                accumulation_multiplier=_effective_multiplier(
                    effectiveness,
                    self.coating.physics.dust_accumulation_multiplier,
                ),
            )
            coverage = cohort.bird_drop_coverage_fraction
            coverage_addition = (
                day_input.event_inputs.bird_coverage_additions.get(cohort.cohort_id, 0.0)
                if day_input.event_inputs is not None
                else 0.0
            )
            coverage = min(1.0, coverage + coverage_addition)
            pre_clean_bird_loss = min(
                1.0,
                coverage * self.birds.loss_per_coverage_fraction,
            )
            energy_cohorts.append(
                replace(
                    cohort,
                    effectiveness_fraction=effectiveness,
                    degradation_fraction=max(
                        0.0,
                        1.0
                        - effectiveness
                        / max(1e-12, self.coating.physics.initial_effectiveness_fraction),
                    ),
                    dust_soiling_ratio=dust_ratio,
                    bird_drop_coverage_fraction=coverage,
                    bird_drop_loss_fraction=pre_clean_bird_loss,
                )
            )
            if coverage_addition > 0.0:
                events.append(
                    DomainEvent(
                        date=day_input.date,
                        event_type="bird_dropping_event",
                        magnitude=coverage_addition,
                        description="Sparse cohort-level bird-dropping event.",
                        scenario_name=self.name,
                        cohort_id=cohort.cohort_id,
                    )
                )
            dust_ratio, coverage = _apply_natural_rain_cleaning(
                dust_ratio=dust_ratio,
                coverage=coverage,
                precipitation_mm=day_input.environment.precipitation_mm,
                soiling=self.soiling_model.config,
                rainfall=self.soiling_model.rainfall,
                bird_rain_removal_efficiency=self.birds.rain_removal_efficiency,
            )
            restored = calculate_passive_dust_cleaning(
                current_dust_soiling_ratio=dust_ratio,
                condensed_liters_per_m2=condensed_per_m2,
                tilt_degrees=self.pv_system.tilt_degrees,
                coating_effectiveness=effectiveness,
                physics=self.coating.physics,
                wind_speed_m_s=day_water.max_wind_speed_m_s,
                precipitation_mm=day_input.environment.precipitation_mm,
            )
            dust_ratio_before_cleaning = dust_ratio
            dust_ratio = min(1.0, dust_ratio + restored)
            total_restored += restored * cohort.panel_count
            passive_cleaning_day = passive_cleaning_day or restored > 0.0
            bird = apply_bird_removal(
                current_coverage_fraction=coverage,
                condensed_liters_per_m2=condensed_per_m2,
                coating_effectiveness=effectiveness,
                physics=self.coating.physics,
            )
            total_bird_removed += bird.removed_coverage_fraction * cohort.panel_count
            bird_removed = bird.removed_coverage_fraction > 0.0
            bird_removal_day = bird_removal_day or bird_removed
            bird_loss = min(
                1.0,
                bird.remaining_coverage_fraction * self.birds.loss_per_coverage_fraction,
            )
            cohort_share = cohort.panel_count / self.farm.total_panels
            next_cohorts.append(
                replace(
                    cohort,
                    age_days=cohort.age_days + 1,
                    effectiveness_fraction=effectiveness,
                    degradation_fraction=1.0 - effectiveness,
                    dust_soiling_ratio=dust_ratio,
                    bird_drop_coverage_fraction=bird.remaining_coverage_fraction,
                    bird_drop_loss_fraction=bird_loss,
                    cumulative_condensed_water_liters=cohort.cumulative_condensed_water_liters
                    + day_water.condensed_liters * cohort_share,
                    cumulative_potentially_collectable_water_liters=cohort.cumulative_potentially_collectable_water_liters
                    + day_water.potentially_collectable_liters * cohort_share,
                    cumulative_actually_collected_water_liters=cohort.cumulative_actually_collected_water_liters
                    + day_water.actually_collected_liters * cohort_share,
                )
            )
            if restored > 0.0:
                events.append(
                    DomainEvent(
                        date=day_input.date,
                        event_type="coating_passive_dust_cleaning",
                        magnitude=restored,
                        description="Condensation-assisted coating dust removal.",
                        scenario_name=self.name,
                        cohort_id=cohort.cohort_id,
                        metadata=_passive_dust_cleaning_metadata(
                            water=day_water,
                            condensed_liters_per_m2=condensed_per_m2,
                            cohort=cohort,
                            effectiveness=effectiveness,
                            dust_ratio_before=dust_ratio_before_cleaning,
                            dust_ratio_after=dust_ratio,
                            restored=restored,
                        ),
                        effective_for_energy_date=day_input.date + timedelta(days=1),
                    )
                )
            if bird_removed:
                events.append(
                    DomainEvent(
                        date=day_input.date,
                        event_type="coating_bird_dropping_removal",
                        magnitude=bird.removed_coverage_fraction,
                        description="Limited coating-assisted bird-dropping removal.",
                        scenario_name=self.name,
                        cohort_id=cohort.cohort_id,
                        metadata=_bird_dropping_removal_metadata(
                            water=day_water,
                            condensed_liters_per_m2=condensed_per_m2,
                            coverage_before=coverage,
                            removed=bird.removed_coverage_fraction,
                            coverage_after=bird.remaining_coverage_fraction,
                        ),
                        effective_for_energy_date=day_input.date + timedelta(days=1),
                    )
                )
        if day_water.condensed_liters > 0.0:
            events.append(
                DomainEvent(
                    date=day_input.date,
                    event_type="coating_condensation",
                    magnitude=day_water.condensed_liters,
                    description="Radiative-cooling coating condensed water.",
                    scenario_name=self.name,
                    metadata={
                        "condensed_liters": day_water.condensed_liters,
                        "potentially_collectable_liters": day_water.potentially_collectable_liters,
                        "actually_collected_liters": day_water.actually_collected_liters,
                        "condensed_liters_per_m2": condensed_per_m2,
                        "condensation_dew_eligible": day_water.condensation_dew_eligible,
                        "ambient_temperature_c": day_water.ambient_temperature_c,
                        "coated_surface_temperature_c": day_water.coated_surface_temperature_c,
                        "dew_point_c": day_water.dew_point_c,
                        "relative_humidity_pct": day_water.relative_humidity_pct,
                    },
                    effective_for_energy_date=day_input.date + timedelta(days=1),
                )
            )
        typed_next = tuple(next_cohorts)
        result = self._build_daily_result(
            day_input=day_input,
            context=context,
            hourly=hourly,
            day_water=day_water,
            condensed_per_m2=condensed_per_m2,
            energy_cohorts=tuple(energy_cohorts),
            cohorts=typed_next,
            events=tuple(events),
            passive_cleaning_day=passive_cleaning_day,
            bird_removal_day=bird_removal_day,
            total_restored=total_restored,
            total_bird_removed=total_bird_removed,
        )
        return StrategyStep(
            state=CoatingScenarioState(date=day_input.date, cohorts=typed_next),
            result=result,
        )

    def _build_daily_result(
        self,
        *,
        day_input: DailyScenarioInput,
        context: ScenarioContext,
        hourly: pd.DataFrame,
        day_water: DailyWaterDiagnostics,
        condensed_per_m2: float,
        energy_cohorts: tuple[CoatingCohortState, ...],
        cohorts: tuple[CoatingCohortState, ...],
        events: tuple[DomainEvent, ...],
        passive_cleaning_day: bool,
        bird_removal_day: bool,
        total_restored: float,
        total_bird_removed: float,
    ) -> DailyScenarioResult:
        cleanliness_ratio = _average_cleanliness(energy_cohorts)
        average_dust_soiling_ratio = _average_dust(energy_cohorts)
        next_day_average_dust_soiling_ratio = _average_dust(cohorts)
        average_bird_loss_fraction = _average_bird_loss(cohorts)
        average_restored = total_restored / self.farm.total_panels
        average_bird_removed = total_bird_removed / self.farm.total_panels
        effectiveness = _average_effectiveness(energy_cohorts)
        cooling_delta = _mean_cooling_delta(hourly, self.coating) * effectiveness
        effective_optical = _effective_multiplier(
            effectiveness,
            self.coating.physics.optical_transmittance_multiplier,
        )
        energy = calculate_energy_mechanisms(
            clean_energy_kwh=day_input.clean_energy_kwh,
            cleanliness_ratio=cleanliness_ratio,
            optical_transmittance_multiplier=effective_optical,
            cooling_delta_c=cooling_delta,
            gamma_pdc_per_c=self.pv_system.gamma_pdc_per_c,
        )
        checksum = str(context.metadata.get("event_tape_checksum", ""))
        extensions = {
            "clean_reference_energy_kwh": energy.clean_reference_energy_kwh,
            "optical_effect_kwh": energy.optical_effect_kwh,
            "temperature_effect_kwh": energy.temperature_effect_kwh,
            "cleanliness_effect_kwh": energy.cleanliness_effect_kwh,
            "final_coated_energy_kwh": energy.final_energy_kwh,
            "optical_multiplier": energy.optical_multiplier,
            "temperature_multiplier": energy.temperature_multiplier,
            "cleanliness_ratio": energy.cleanliness_ratio,
            "condensed_water_liters": day_water.condensed_liters,
            "potentially_collectable_water_liters": day_water.potentially_collectable_liters,
            "actually_collected_water_liters": day_water.actually_collected_liters,
            "condensation_dew_eligible": day_water.condensation_dew_eligible,
            "dew_point_c": day_water.dew_point_c,
            "coated_surface_temperature_c": day_water.coated_surface_temperature_c,
            "ambient_temperature_c": day_water.ambient_temperature_c,
            "relative_humidity_pct": day_water.relative_humidity_pct,
            "condensed_liters_per_m2": condensed_per_m2,
            "max_wind_speed_m_s": day_water.max_wind_speed_m_s,
            "precipitation_mm": day_input.environment.precipitation_mm,
            "passive_cleaning_day": passive_cleaning_day,
            "passive_dust_restored_fraction": average_restored,
            "bird_removal_day": bird_removal_day,
            "average_bird_removed_coverage_fraction": average_bird_removed,
            "coating_age_days": max(cohort.age_days for cohort in cohorts),
            "coating_effectiveness_fraction": _average_effectiveness(cohorts),
            "average_dust_soiling_ratio": average_dust_soiling_ratio,
            "next_day_average_dust_soiling_ratio": next_day_average_dust_soiling_ratio,
            "retained_dust_fraction": max(0.0, 1.0 - average_dust_soiling_ratio),
            "average_bird_loss_fraction": average_bird_loss_fraction,
            "bird_loss_fraction": average_bird_loss_fraction,
            "coated_area_m2": self.cost_basis.total_coated_area_m2,
            "coating_cost_basis": self.cost_basis.to_record(),
            "event_tape_checksum": checksum,
        }
        result = DailyScenarioResult(
            date=day_input.date,
            scenario_name=self.name,
            clean_energy_kwh=day_input.clean_energy_kwh,
            actual_energy_kwh=energy.final_energy_kwh,
            allow_above_clean_reference=True,
            operational=OperationalQuantities(
                coated_panel_count=self.farm.total_panels,
                water_liters=0.0,
                energy_used_kwh=(
                    self.cost_basis.process_energy_kwh if day_input.day_index == 0 else 0.0
                ),
            ),
            events=tuple(events),
            extensions=extensions,
        )
        return result


def _dust_event_losses(events: list[SimulationEvent]) -> tuple[float, float]:
    daily_loss = sum(event.magnitude for event in events if event.event_type == "dust_accumulation")
    dust_event_loss = sum(
        event.magnitude for event in events if event.event_type == "heavy_dust_event"
    )
    return daily_loss, dust_event_loss


def _apply_natural_rain_cleaning(
    *,
    dust_ratio: float,
    coverage: float,
    precipitation_mm: float,
    soiling: SoilingConfig,
    rainfall: RainfallCleaningConfig,
    bird_rain_removal_efficiency: float,
) -> tuple[float, float]:
    next_dust_ratio = restore_dust_ratio_after_rain(
        dust_ratio,
        precipitation_mm=precipitation_mm,
        soiling=soiling,
        rainfall=rainfall,
    )
    next_coverage = coverage
    if precipitation_mm > 0.0:
        next_coverage *= 1.0 - bird_rain_removal_efficiency
    return next_dust_ratio, next_coverage


@dataclass(frozen=True)
class DailyWaterDiagnostics:
    dew_point_c: float
    surface_temperature_c: float
    condensed_liters: float
    potentially_collectable_liters: float
    actually_collected_liters: float
    condensation_dew_eligible: bool
    ambient_temperature_c: float
    coated_surface_temperature_c: float
    relative_humidity_pct: float
    max_wind_speed_m_s: float


def _daily_water(
    hourly: pd.DataFrame, coating: CoatingConfig, area_m2: float
) -> DailyWaterDiagnostics:
    total_condensed = 0.0
    total_potential = 0.0
    total_actual = 0.0
    representative: CondensationResult | None = None
    representative_air_temperature = 0.0
    representative_relative_humidity = 0.0
    max_hourly_condensed = -1.0
    for _, row in hourly.iterrows():
        air_temperature = float(row["temp_air_c"])
        relative_humidity = float(row["relative_humidity_pct"])
        surface = calculate_surface_temperature_c(
            air_temperature_c=air_temperature,
            relative_humidity_pct=relative_humidity,
            wind_speed_m_s=float(row["wind_speed_m_s"]),
            irradiance_w_m2=float(row["ghi_w_m2"]),
            physics=coating.physics,
        )
        water = calculate_condensation(
            air_temperature_c=air_temperature,
            relative_humidity_pct=relative_humidity,
            surface_temperature_c=surface,
            exposure_hours=1.0,
            area_m2=area_m2,
            water=coating.water,
        )
        if water.condensed_liters > max_hourly_condensed:
            representative = water
            representative_air_temperature = air_temperature
            representative_relative_humidity = relative_humidity
            max_hourly_condensed = water.condensed_liters
        total_condensed += water.condensed_liters
        total_potential += water.potentially_collectable_liters
        total_actual += water.actually_collected_liters
    if representative is None:
        representative = CondensationResult(
            dew_point_c=0.0,
            surface_temperature_c=0.0,
            condensed_liters=0.0,
            potentially_collectable_liters=0.0,
            actually_collected_liters=0.0,
        )
    return DailyWaterDiagnostics(
        dew_point_c=representative.dew_point_c,
        surface_temperature_c=representative.surface_temperature_c,
        condensed_liters=total_condensed,
        potentially_collectable_liters=total_potential,
        actually_collected_liters=total_actual,
        condensation_dew_eligible=total_condensed > 0.0,
        ambient_temperature_c=representative_air_temperature,
        coated_surface_temperature_c=representative.surface_temperature_c,
        relative_humidity_pct=representative_relative_humidity,
        max_wind_speed_m_s=float(hourly["wind_speed_m_s"].max()),
    )


def _mean_cooling_delta(hourly: pd.DataFrame, coating: CoatingConfig) -> float:
    deltas = []
    for _, row in hourly.iterrows():
        surface = calculate_surface_temperature_c(
            air_temperature_c=float(row["temp_air_c"]),
            relative_humidity_pct=float(row["relative_humidity_pct"]),
            wind_speed_m_s=float(row["wind_speed_m_s"]),
            irradiance_w_m2=float(row["ghi_w_m2"]),
            physics=coating.physics,
        )
        if float(row["ghi_w_m2"]) > 5.0:
            deltas.append(max(0.0, float(row["temp_air_c"]) - surface))
    return float(np.mean(deltas)) if deltas else 0.0


def _effectiveness_after_degradation(
    cohort: CoatingCohortState,
    coating: CoatingConfig,
) -> float:
    initial = coating.physics.initial_effectiveness_fraction
    annual_retention = 1.0 - coating.physics.annual_degradation_fraction
    degraded = initial * annual_retention ** (cohort.age_days / 365.0)
    return float(min(initial, max(0.0, degraded)))


def _effective_multiplier(effectiveness: float, configured_multiplier: float) -> float:
    bounded_effectiveness = min(1.0, max(0.0, effectiveness))
    return 1.0 + bounded_effectiveness * (configured_multiplier - 1.0)


def _average_dust(cohorts: tuple[CoatingCohortState, ...]) -> float:
    total = sum(cohort.panel_count for cohort in cohorts)
    return sum(cohort.panel_count * cohort.dust_soiling_ratio for cohort in cohorts) / total


def _average_effectiveness(cohorts: tuple[CoatingCohortState, ...]) -> float:
    total = sum(cohort.panel_count for cohort in cohorts)
    return sum(cohort.panel_count * cohort.effectiveness_fraction for cohort in cohorts) / total


def _average_bird_loss(cohorts: tuple[CoatingCohortState, ...]) -> float:
    total = sum(cohort.panel_count for cohort in cohorts)
    return sum(cohort.panel_count * cohort.bird_drop_loss_fraction for cohort in cohorts) / total


def _average_cleanliness(cohorts: tuple[CoatingCohortState, ...]) -> float:
    total = sum(cohort.panel_count for cohort in cohorts)
    weighted = 0.0
    for cohort in cohorts:
        weighted += (
            cohort.panel_count * cohort.dust_soiling_ratio * (1.0 - cohort.bird_drop_loss_fraction)
        )
    return weighted / total


def _base_condensation_metadata(
    *,
    water: DailyWaterDiagnostics,
    condensed_liters_per_m2: float,
) -> dict[str, object]:
    return {
        "condensation_dew_eligible": water.condensation_dew_eligible,
        "ambient_temperature_c": water.ambient_temperature_c,
        "coated_surface_temperature_c": water.coated_surface_temperature_c,
        "dew_point_c": water.dew_point_c,
        "relative_humidity_pct": water.relative_humidity_pct,
        "condensed_liters_per_m2": condensed_liters_per_m2,
        "max_wind_speed_m_s": water.max_wind_speed_m_s,
    }


def _passive_dust_cleaning_metadata(
    *,
    water: DailyWaterDiagnostics,
    condensed_liters_per_m2: float,
    cohort: CoatingCohortState,
    effectiveness: float,
    dust_ratio_before: float,
    dust_ratio_after: float,
    restored: float,
) -> dict[str, object]:
    dust_before = max(0.0, 1.0 - dust_ratio_before)
    dust_removed = min(dust_before, max(0.0, restored))
    dust_after = max(0.0, 1.0 - dust_ratio_after)
    metadata = _base_condensation_metadata(
        water=water,
        condensed_liters_per_m2=condensed_liters_per_m2,
    )
    metadata.update(
        {
            "coating_age_days": cohort.age_days,
            "coating_effectiveness_fraction": effectiveness,
            "coating_degradation_multiplier": effectiveness,
            "coating_degradation_fraction": max(0.0, 1.0 - effectiveness),
            "dust_before": dust_before,
            "dust_removed": dust_removed,
            "dust_after": dust_after,
            "dust_soiling_ratio_before": dust_ratio_before,
            "dust_soiling_ratio_after": dust_ratio_after,
            "dust_removal_efficiency_used": (
                dust_removed / dust_before if dust_before > 0.0 else 0.0
            ),
        }
    )
    return metadata


def _bird_dropping_removal_metadata(
    *,
    water: DailyWaterDiagnostics,
    condensed_liters_per_m2: float,
    coverage_before: float,
    removed: float,
    coverage_after: float,
) -> dict[str, object]:
    metadata = _base_condensation_metadata(
        water=water,
        condensed_liters_per_m2=condensed_liters_per_m2,
    )
    metadata.update(
        {
            "bird_contamination_before": coverage_before,
            "bird_removed": min(coverage_before, max(0.0, removed)),
            "bird_contamination_after": coverage_after,
            "bird_removal_efficiency_used": (
                removed / coverage_before if coverage_before > 0.0 else 0.0
            ),
        }
    )
    return metadata
