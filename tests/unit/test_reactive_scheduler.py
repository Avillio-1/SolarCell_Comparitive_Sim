from __future__ import annotations

from solarclean.config.models import ReactiveInspectionConfig
from solarclean.domain.reactive_cv.scheduler import InspectionScheduler


def _config(
    interval_days: int = 7, first_inspection_day_index: int = 0
) -> ReactiveInspectionConfig:
    return ReactiveInspectionConfig(
        interval_days=interval_days,
        first_inspection_day_index=first_inspection_day_index,
    )


def test_rotation_covers_every_cohort_exactly_once_per_interval() -> None:
    total_cohorts = 23
    interval_days = 7
    scheduler = InspectionScheduler(_config(interval_days=interval_days), total_cohorts)

    covered: set[int] = set()
    for day_index in range(interval_days):
        due = scheduler.due_cohorts(day_index).due_cohort_ids
        assert covered.isdisjoint(due)
        covered.update(due)

    assert covered == set(range(total_cohorts))


def test_rotation_repeats_identically_across_cycles() -> None:
    scheduler = InspectionScheduler(_config(interval_days=5), total_cohorts=17)
    first_cycle = [scheduler.due_cohorts(day_index).due_cohort_ids for day_index in range(5)]
    second_cycle = [scheduler.due_cohorts(day_index).due_cohort_ids for day_index in range(5, 10)]
    assert first_cycle == second_cycle


def test_first_inspection_day_index_shifts_the_cycle() -> None:
    scheduler = InspectionScheduler(
        _config(interval_days=4, first_inspection_day_index=2), total_cohorts=8
    )
    # The configured offset day starts group 0 of the rotation.
    assert scheduler.due_cohorts(2).due_cohort_ids == (0, 4)
    # The cycle repeats every interval_days afterwards.
    assert scheduler.due_cohorts(2).due_cohort_ids == scheduler.due_cohorts(6).due_cohort_ids
