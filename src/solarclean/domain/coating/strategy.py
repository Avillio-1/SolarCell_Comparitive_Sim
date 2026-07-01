from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import cast

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
from solarclean.domain.contamination.soiling import ContaminationState, KimberStyleSoilingModel
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
        self.soiling_model = KimberStyleSoilingModel(soiling, rainfall)
        self.birds = birds
        self.farm = farm
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
        hourly = _hourly_for_day(context.weather.hourly, day_input.date)
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
        next_cohorts: list[CoatingCohortState] = []
        for cohort in state.cohorts:
            effectiveness = _effectiveness_after_degradation(cohort, self.coating)
            uncoated_delta = base_update.state.dust_soiling_ratio - previous_average_dust
            if day_input.event_inputs is not None:
                variation = day_input.event_inputs.cohort_variation_multipliers.get(
                    cohort.cohort_id,
                    1.0,
                )
            else:
                variation = 1.0
            if uncoated_delta < 0.0:
                coated_delta = (
                    uncoated_delta * variation * self.coating.physics.dust_accumulation_multiplier
                )
            else:
                coated_delta = uncoated_delta
            dust_ratio = max(0.0, min(1.0, cohort.dust_soiling_ratio + coated_delta))
            restored = calculate_passive_dust_cleaning(
                current_dust_soiling_ratio=dust_ratio,
                condensed_liters_per_m2=condensed_per_m2,
                tilt_degrees=self.pv_system.tilt_degrees,
                coating_effectiveness=effectiveness,
                physics=self.coating.physics,
            )
            dust_ratio = min(1.0, dust_ratio + restored)
            coverage_addition = (
                day_input.event_inputs.bird_coverage_additions.get(cohort.cohort_id, 0.0)
                if day_input.event_inputs is not None
                else 0.0
            )
            coverage = min(1.0, cohort.bird_drop_coverage_fraction + coverage_addition)
            if day_input.environment.precipitation_mm > 0.0:
                coverage *= 1.0 - self.birds.rain_removal_efficiency
            bird = apply_bird_removal(
                current_coverage_fraction=coverage,
                condensed_liters_per_m2=condensed_per_m2,
                coating_effectiveness=effectiveness,
                physics=self.coating.physics,
            )
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
                        metadata={"condensed_liters_per_m2": condensed_per_m2},
                    )
                )
            if bird.removed_coverage_fraction > 0.0:
                events.append(
                    DomainEvent(
                        date=day_input.date,
                        event_type="coating_bird_dropping_removal",
                        magnitude=bird.removed_coverage_fraction,
                        description="Limited coating-assisted bird-dropping removal.",
                        scenario_name=self.name,
                        cohort_id=cohort.cohort_id,
                        metadata={"condensed_liters_per_m2": condensed_per_m2},
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
                        "potentially_collectable_liters": day_water.potentially_collectable_liters
                    },
                )
            )
        typed_next = tuple(next_cohorts)
        cleanliness_ratio = _average_cleanliness(typed_next)
        cooling_delta = _mean_cooling_delta(hourly, self.coating)
        energy = calculate_energy_mechanisms(
            clean_energy_kwh=day_input.clean_energy_kwh,
            cleanliness_ratio=cleanliness_ratio,
            optical_transmittance_multiplier=self.coating.physics.optical_transmittance_multiplier,
            cooling_delta_c=cooling_delta,
            gamma_pdc_per_c=self.pv_system.gamma_pdc_per_c,
        )
        checksum = context.event_tape.checksum() if context.event_tape is not None else ""
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
            "coating_age_days": max(cohort.age_days for cohort in typed_next),
            "coating_effectiveness_fraction": _average_effectiveness(typed_next),
            "average_dust_soiling_ratio": _average_dust(typed_next),
            "average_bird_loss_fraction": _average_bird_loss(typed_next),
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
                water_liters=day_water.actually_collected_liters,
                energy_used_kwh=self.cost_basis.process_energy_kwh / 365.0,
                capex_cost=self.cost_basis.material_cost_total
                + self.cost_basis.surface_preparation_cost_total
                + self.cost_basis.fixed_equipment_setup_cost,
            ),
            events=tuple(events),
            extensions=extensions,
        )
        return StrategyStep(
            state=CoatingScenarioState(date=day_input.date, cohorts=typed_next),
            result=result,
        )


def _hourly_for_day(hourly: pd.DataFrame, day: date) -> pd.DataFrame:
    frame = cast(pd.DataFrame, hourly.loc[pd.DatetimeIndex(hourly.index).date == day])
    if frame.empty:
        raise ValueError(f"missing hourly weather for coating day {day.isoformat()}")
    return frame


def _daily_water(
    hourly: pd.DataFrame, coating: CoatingConfig, area_m2: float
) -> CondensationResult:
    total_condensed = 0.0
    total_potential = 0.0
    total_actual = 0.0
    for _, row in hourly.iterrows():
        surface = calculate_surface_temperature_c(
            air_temperature_c=float(row["temp_air_c"]),
            relative_humidity_pct=float(row["relative_humidity_pct"]),
            wind_speed_m_s=float(row["wind_speed_m_s"]),
            irradiance_w_m2=float(row["ghi_w_m2"]),
            physics=coating.physics,
        )
        water = calculate_condensation(
            air_temperature_c=float(row["temp_air_c"]),
            relative_humidity_pct=float(row["relative_humidity_pct"]),
            surface_temperature_c=surface,
            exposure_hours=1.0,
            area_m2=area_m2,
            water=coating.water,
        )
        total_condensed += water.condensed_liters
        total_potential += water.potentially_collectable_liters
        total_actual += water.actually_collected_liters
    return CondensationResult(
        dew_point_c=0.0,
        surface_temperature_c=0.0,
        condensed_liters=total_condensed,
        potentially_collectable_liters=total_potential,
        actually_collected_liters=total_actual,
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
    daily_degradation = coating.physics.annual_degradation_fraction / 365.0
    degraded = cohort.effectiveness_fraction - daily_degradation
    return min(coating.physics.initial_effectiveness_fraction, max(0.0, degraded))


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
