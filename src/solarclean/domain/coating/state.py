from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CoatingCohortState:
    cohort_id: int
    panel_count: int
    applied: bool
    age_days: int
    effectiveness_fraction: float
    degradation_fraction: float
    dust_soiling_ratio: float
    bird_drop_coverage_fraction: float
    bird_drop_loss_fraction: float
    cumulative_condensed_water_liters: float = 0.0
    cumulative_potentially_collectable_water_liters: float = 0.0
    cumulative_actually_collected_water_liters: float = 0.0


@dataclass(frozen=True)
class CoatingScenarioState:
    date: date
    cohorts: tuple[CoatingCohortState, ...]
