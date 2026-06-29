from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Protocol

import numpy as np

from solarclean.config.models import BirdDroppingConfig, FarmConfig
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
            tape_coverage = (
                bird_coverage_additions.get(cohort.cohort_id)
                if bird_coverage_additions is not None
                else None
            )
            if tape_coverage is not None:
                added_coverage = tape_coverage
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


def _calculate_state_energy(state: FarmState, clean_per_panel_kwh: float) -> float:
    total = 0.0
    for cohort in state.cohorts:
        dust = max(0.0, min(1.0, cohort.dust_soiling_ratio))
        bird = max(0.0, min(1.0, 1.0 - cohort.bird_drop_loss_fraction))
        total += clean_per_panel_kwh * cohort.panel_count * dust * bird
    return total
