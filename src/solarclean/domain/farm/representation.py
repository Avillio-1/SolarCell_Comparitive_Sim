from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Protocol

import numpy as np

from solarclean.config.models import (
    BirdDroppingConfig,
    FarmConfig,
    RainfallCleaningConfig,
    SoilingConfig,
)
from solarclean.domain.contamination.soiling import SimulationEvent


@dataclass(frozen=True)
class CohortState:
    cohort_id: int
    panel_count: int
    dust_soiling_ratio: float = 1.0
    bird_drop_coverage_fraction: float = 0.0
    bird_drop_loss_fraction: float = 0.0
    days_since_effective_rain: int = 0
    days_since_manual_cleaning: int = 0
    zone_id: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class FarmState:
    date: date
    cohorts: list[CohortState]

    @property
    def total_panel_count(self) -> int:
        return sum(cohort.panel_count for cohort in self.cohorts)

    @property
    def aggregate_dust_soiling_ratio(self) -> float:
        total = self.total_panel_count
        return sum(c.panel_count * c.dust_soiling_ratio for c in self.cohorts) / total


@dataclass(frozen=True)
class FarmEnergyResult:
    clean_energy_kwh: float
    actual_energy_kwh: float


@dataclass(frozen=True)
class FarmAdvanceResult:
    state: FarmState
    events: list[SimulationEvent]


class FarmRepresentation(Protocol):
    def initial_state(self, day: date, rng: np.random.Generator) -> FarmState: ...

    def calculate_daily_energy(
        self, state: FarmState, clean_per_panel_kwh: float
    ) -> FarmEnergyResult: ...


class RepresentativePanelFarm:
    def __init__(self, config: FarmConfig) -> None:
        self.config = config

    def initial_state(self, day: date, rng: np.random.Generator) -> FarmState:
        del rng
        return FarmState(
            date=day,
            cohorts=[CohortState(cohort_id=0, panel_count=self.config.total_panels)],
        )

    def calculate_daily_energy(
        self, state: FarmState, clean_per_panel_kwh: float
    ) -> FarmEnergyResult:
        clean = clean_per_panel_kwh * state.total_panel_count
        actual = _calculate_state_energy(state, clean_per_panel_kwh)
        return FarmEnergyResult(clean_energy_kwh=clean, actual_energy_kwh=actual)


class CohortFarm:
    def __init__(
        self,
        config: FarmConfig,
        bird_config: BirdDroppingConfig | None = None,
    ) -> None:
        self.config = config
        self.bird_config = bird_config or BirdDroppingConfig()

    def initial_state(self, day: date, rng: np.random.Generator) -> FarmState:
        del rng
        cohorts = [
            CohortState(
                cohort_id=cohort_id,
                panel_count=self.config.panels_per_cohort,
                zone_id=f"zone-{cohort_id % 10:02d}",
            )
            for cohort_id in range(self.config.cohort_count)
        ]
        state = FarmState(date=day, cohorts=cohorts)
        if state.total_panel_count != self.config.total_panels:
            raise ValueError("sum of cohort panel counts must equal configured fleet size")
        return state

    def advance_day(
        self,
        state: FarmState,
        precipitation_mm: float,
        rng: np.random.Generator,
        bird_coverage_additions: dict[int, float] | None = None,
    ) -> FarmAdvanceResult:
        events: list[SimulationEvent] = []
        updated: list[CohortState] = []
        for cohort in state.cohorts:
            coverage = cohort.bird_drop_coverage_fraction
            if precipitation_mm > 0 and coverage > 0:
                coverage *= 1.0 - self.bird_config.rain_removal_efficiency
            if bird_coverage_additions is not None:
                # The event tape is authoritative: an absent cohort entry means
                # no bird event today, not permission to draw a replacement.
                added_coverage = bird_coverage_additions.get(cohort.cohort_id)
            elif rng.random() < self.bird_config.event_probability_per_cohort_day:
                added_coverage = float(
                    rng.uniform(
                        self.bird_config.coverage_min_fraction,
                        self.bird_config.coverage_max_fraction,
                    )
                )
            else:
                added_coverage = None
            if added_coverage is not None:
                coverage = min(1.0, coverage + added_coverage)
                events.append(
                    SimulationEvent(
                        date=state.date,
                        event_type="bird_dropping_event",
                        magnitude=added_coverage,
                        description="Sparse cohort-level bird-dropping event.",
                        cohort_id=cohort.cohort_id,
                    )
                )
            loss = min(1.0, coverage * self.bird_config.loss_per_coverage_fraction)
            updated.append(
                replace(
                    cohort,
                    bird_drop_coverage_fraction=coverage,
                    bird_drop_loss_fraction=loss,
                    days_since_effective_rain=0
                    if precipitation_mm > 0
                    else cohort.days_since_effective_rain + 1,
                    days_since_manual_cleaning=cohort.days_since_manual_cleaning + 1,
                )
            )
        return FarmAdvanceResult(state=FarmState(date=state.date, cohorts=updated), events=events)

    def calculate_daily_energy(
        self, state: FarmState, clean_per_panel_kwh: float
    ) -> FarmEnergyResult:
        clean = clean_per_panel_kwh * state.total_panel_count
        actual = _calculate_state_energy(state, clean_per_panel_kwh)
        return FarmEnergyResult(clean_energy_kwh=clean, actual_energy_kwh=actual)

    def apply_rain_cleaning(
        self,
        state: FarmState,
        precipitation_mm: float,
        *,
        soiling: SoilingConfig,
        rainfall: RainfallCleaningConfig,
        rain_efficiency_multiplier: float = 1.0,
    ) -> FarmState:
        """Apply end-of-day natural cleaning to the state used tomorrow."""

        if precipitation_mm <= 0.0:
            return state
        cohorts: list[CohortState] = []
        for cohort in state.cohorts:
            coverage = cohort.bird_drop_coverage_fraction * (
                1.0 - self.bird_config.rain_removal_efficiency
            )
            cohorts.append(
                replace(
                    cohort,
                    dust_soiling_ratio=restore_dust_ratio_after_rain(
                        cohort.dust_soiling_ratio,
                        precipitation_mm=precipitation_mm,
                        soiling=soiling,
                        rainfall=rainfall,
                        rain_efficiency_multiplier=rain_efficiency_multiplier,
                    ),
                    bird_drop_coverage_fraction=coverage,
                    bird_drop_loss_fraction=min(
                        1.0,
                        coverage * self.bird_config.loss_per_coverage_fraction,
                    ),
                    days_since_effective_rain=0,
                )
            )
        return FarmState(date=state.date, cohorts=cohorts)


def _calculate_state_energy(state: FarmState, clean_per_panel_kwh: float) -> float:
    total = 0.0
    for cohort in state.cohorts:
        dust = max(0.0, min(1.0, cohort.dust_soiling_ratio))
        bird = max(0.0, min(1.0, 1.0 - cohort.bird_drop_loss_fraction))
        total += clean_per_panel_kwh * cohort.panel_count * dust * bird
    return total


def advance_dust_ratio(
    current_ratio: float,
    *,
    daily_loss_fraction: float,
    dust_event_loss_fraction: float,
    precipitation_mm: float,
    soiling: SoilingConfig,
    rainfall: RainfallCleaningConfig,
    cohort_variation_multiplier: float = 1.0,
    accumulation_multiplier: float = 1.0,
    unscaled_deposition_fraction: float = 0.0,
    rain_efficiency_multiplier: float = 1.0,
) -> float:
    """Apply shared environmental dust drivers to one cohort's persistent state.

    Cohort variation is defined as a non-negative multiplier on *new deposition*,
    never on the cohort's complete accumulated cleanliness state. Scenario-specific
    coatings may reduce new deposition through ``accumulation_multiplier`` while
    rainfall restoration remains a shared environmental effect.
    ``unscaled_deposition_fraction`` carries deposition already adjusted by the
    caller (dew-cementation adhesion after coating suppression), so it bypasses
    ``accumulation_multiplier`` while still varying per cohort.
    """
    variation = max(0.0, cohort_variation_multiplier)
    deposition_multiplier = max(0.0, accumulation_multiplier)
    deposited = max(0.0, daily_loss_fraction + dust_event_loss_fraction)
    unscaled = max(0.0, unscaled_deposition_fraction)
    if unscaled == 0.0:
        # Preserve the frozen calculation order exactly when dew cementation is
        # disabled; the historical regression fixtures depend on bit-for-bit
        # compatibility with this path.
        ratio = current_ratio - deposited * variation * deposition_multiplier
    else:
        ratio = current_ratio - (deposited * deposition_multiplier + unscaled) * variation
    ratio = max(soiling.minimum_soiling_ratio, min(1.0, ratio))
    return restore_dust_ratio_after_rain(
        ratio,
        precipitation_mm=precipitation_mm,
        soiling=soiling,
        rainfall=rainfall,
        rain_efficiency_multiplier=rain_efficiency_multiplier,
    )


def restore_dust_ratio_after_rain(
    current_ratio: float,
    *,
    precipitation_mm: float,
    soiling: SoilingConfig,
    rainfall: RainfallCleaningConfig,
    rain_efficiency_multiplier: float = 1.0,
) -> float:
    multiplier = min(1.0, max(0.0, rain_efficiency_multiplier))
    ratio = max(soiling.minimum_soiling_ratio, min(1.0, current_ratio))
    if precipitation_mm >= rainfall.full_rain_cleaning_threshold_mm:
        ratio += (1.0 - ratio) * rainfall.full_rain_cleaning_efficiency * multiplier
    elif precipitation_mm >= rainfall.partial_rain_threshold_mm:
        ratio += (1.0 - ratio) * rainfall.partial_rain_cleaning_efficiency * multiplier
    return max(soiling.minimum_soiling_ratio, min(1.0, ratio))
