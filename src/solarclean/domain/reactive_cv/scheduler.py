from __future__ import annotations

from dataclasses import dataclass

from solarclean.config.models import ReactiveInspectionConfig


@dataclass(frozen=True)
class ScheduledInspection:
    due_cohort_ids: tuple[int, ...]


class InspectionScheduler:
    """Rotating cohort coverage: the whole farm is covered once per interval.

    Cohorts are split into `interval_days` rotating groups. On each day
    whose position in the cycle matches a group, that group becomes due
    for inspection. This guarantees every cohort gets inspected roughly
    once per `interval_days`, independent of drone capacity (capacity
    limits are applied afterwards by the drone fleet, not here).
    """

    def __init__(self, config: ReactiveInspectionConfig, total_cohorts: int) -> None:
        self.config = config
        self.total_cohorts = total_cohorts
        self._groups: tuple[tuple[int, ...], ...] = tuple(
            tuple(range(offset, total_cohorts, config.interval_days))
            for offset in range(config.interval_days)
        )

    def due_cohorts(self, day_index: int) -> ScheduledInspection:
        cycle_position = (day_index - self.config.first_inspection_day_index) % (
            self.config.interval_days
        )
        due = self._groups[cycle_position] if cycle_position < len(self._groups) else ()
        return ScheduledInspection(due_cohort_ids=due)
