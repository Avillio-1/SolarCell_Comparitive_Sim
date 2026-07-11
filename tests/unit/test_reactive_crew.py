from __future__ import annotations

import pytest

from solarclean.config.models import ReactiveCrewConfig
from solarclean.domain.farm.representation import CohortState
from solarclean.domain.reactive_cv.crew import CleaningCrew


def _config(**overrides: object) -> ReactiveCrewConfig:
    defaults: dict[str, object] = {
        "daily_capacity_cohorts": 6,
        "setup_minutes_per_cohort": 8.0,
        "cleaning_minutes_per_cohort": 25.0,
        "water_liters_per_cohort": 180.0,
        "dust_removal_efficiency": 0.9,
        "bird_removal_efficiency": 0.8,
    }
    defaults.update(overrides)
    return ReactiveCrewConfig(**defaults)  # type: ignore[arg-type]


def test_cleaning_restores_most_but_not_all_dust_soiling() -> None:
    crew = CleaningCrew(_config(dust_removal_efficiency=0.9))
    cohort = CohortState(cohort_id=0, panel_count=100, dust_soiling_ratio=0.6)

    outcome = crew.clean(cohort)

    # 0.9 efficiency on a 0.4 deficit restores 0.36, landing at 0.96.
    assert outcome.cohort.dust_soiling_ratio == pytest.approx(0.96)
    assert outcome.cohort.dust_soiling_ratio <= 1.0


def test_cleaning_reduces_bird_coverage_and_loss() -> None:
    crew = CleaningCrew(_config(bird_removal_efficiency=0.8))
    cohort = CohortState(
        cohort_id=0,
        panel_count=100,
        bird_drop_coverage_fraction=0.5,
        bird_drop_loss_fraction=0.4,
    )

    outcome = crew.clean(cohort)

    assert outcome.cohort.bird_drop_coverage_fraction == pytest.approx(0.1)
    assert outcome.cohort.bird_drop_loss_fraction == pytest.approx(0.08)


def test_cleaning_resets_days_since_manual_cleaning() -> None:
    crew = CleaningCrew(_config())
    cohort = CohortState(cohort_id=0, panel_count=100, days_since_manual_cleaning=42)

    outcome = crew.clean(cohort)

    assert outcome.cohort.days_since_manual_cleaning == 0


def test_reports_crew_hours_and_water_from_config() -> None:
    crew = CleaningCrew(
        _config(
            setup_minutes_per_cohort=10.0,
            cleaning_minutes_per_cohort=20.0,
            water_liters_per_cohort=150.0,
        )
    )
    cohort = CohortState(cohort_id=0, panel_count=100)

    outcome = crew.clean(cohort)

    assert outcome.crew_hours == 0.5
    assert outcome.water_liters == 150.0


def test_cementation_multiplier_reduces_dust_removal_efficiency() -> None:
    crew = CleaningCrew(_config(dust_removal_efficiency=0.9))
    cohort = CohortState(cohort_id=0, panel_count=100, dust_soiling_ratio=0.6)

    outcome = crew.clean(cohort, dust_efficiency_multiplier=0.5)

    assert outcome.effective_dust_removal_efficiency == pytest.approx(0.45)
    assert outcome.cohort.dust_soiling_ratio == pytest.approx(0.78)
