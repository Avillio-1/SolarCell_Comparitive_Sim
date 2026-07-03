from __future__ import annotations

from dataclasses import dataclass, replace

from solarclean.config.models import ReactiveCrewConfig
from solarclean.domain.farm.representation import CohortState


@dataclass(frozen=True)
class CleaningOutcome:
    cohort: CohortState
    crew_hours: float
    water_liters: float


class CleaningCrew:
    """Applies targeted, capacity-limited cleaning to selected cohorts only."""

    def __init__(self, config: ReactiveCrewConfig) -> None:
        self.config = config

    def clean(self, cohort: CohortState) -> CleaningOutcome:
        restored_dust = (1.0 - cohort.dust_soiling_ratio) * self.config.dust_removal_efficiency
        new_dust_ratio = min(1.0, cohort.dust_soiling_ratio + restored_dust)
        new_bird_coverage = cohort.bird_drop_coverage_fraction * (
            1.0 - self.config.bird_removal_efficiency
        )
        new_bird_loss = cohort.bird_drop_loss_fraction * (1.0 - self.config.bird_removal_efficiency)
        cleaned = replace(
            cohort,
            dust_soiling_ratio=new_dust_ratio,
            bird_drop_coverage_fraction=new_bird_coverage,
            bird_drop_loss_fraction=new_bird_loss,
            days_since_manual_cleaning=0,
        )
        hours = (
            self.config.setup_minutes_per_cohort + self.config.cleaning_minutes_per_cohort
        ) / 60.0
        return CleaningOutcome(
            cohort=cleaned,
            crew_hours=hours,
            water_liters=self.config.water_liters_per_cohort,
        )
