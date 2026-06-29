from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from solarclean.config.models import BirdDroppingConfig, FarmConfig
from solarclean.domain.farm.representation import CohortFarm, CohortState, RepresentativePanelFarm


def test_cohort_panel_counts_sum_to_fleet_size() -> None:
    farm = CohortFarm(FarmConfig(total_panels=10000, panel_capacity_w=400, cohort_count=100))

    state = farm.initial_state(date(2025, 1, 1), np.random.default_rng(1))

    assert state.total_panel_count == 10000
    assert sum(cohort.panel_count for cohort in state.cohorts) == 10000


def test_homogeneous_cohorts_equal_representative_scaling() -> None:
    clean_per_panel_kwh = 1.5
    config = FarmConfig(total_panels=10000, panel_capacity_w=400, cohort_count=100)
    cohort_farm = CohortFarm(config, BirdDroppingConfig(event_probability_per_cohort_day=0.0))
    representative = RepresentativePanelFarm(config)
    rng = np.random.default_rng(10)
    state = cohort_farm.initial_state(date(2025, 1, 1), rng)

    cohort_energy = cohort_farm.calculate_daily_energy(state, clean_per_panel_kwh)
    representative_state = representative.initial_state(date(2025, 1, 1), rng)
    representative_energy = representative.calculate_daily_energy(
        representative_state, clean_per_panel_kwh
    )

    assert cohort_energy.actual_energy_kwh == pytest.approx(representative_energy.actual_energy_kwh)


def test_heterogeneous_cohort_aggregate_equals_explicit_sum() -> None:
    config = FarmConfig(
        total_panels=10000, panel_capacity_w=400, cohort_count=2, panels_per_cohort=5000
    )
    farm = CohortFarm(config, BirdDroppingConfig(event_probability_per_cohort_day=0.0))
    state = farm.initial_state(date(2025, 1, 1), np.random.default_rng(1))
    state.cohorts[0] = CohortState(cohort_id=0, panel_count=5000, dust_soiling_ratio=0.9)
    state.cohorts[1] = CohortState(cohort_id=1, panel_count=5000, dust_soiling_ratio=0.8)

    result = farm.calculate_daily_energy(state, clean_per_panel_kwh=2.0)

    assert result.actual_energy_kwh == pytest.approx((5000 * 2.0 * 0.9) + (5000 * 2.0 * 0.8))


def test_invalid_cohort_configuration_fails_validation() -> None:
    with pytest.raises(ValueError, match="cohort_count .* panels_per_cohort"):
        FarmConfig(total_panels=10000, panel_capacity_w=400, cohort_count=90, panels_per_cohort=100)


def test_same_seed_reproduces_sparse_bird_events() -> None:
    config = FarmConfig(total_panels=10000, panel_capacity_w=400, cohort_count=100)
    bird_config = BirdDroppingConfig(
        event_probability_per_cohort_day=0.2,
        coverage_min_fraction=0.01,
        coverage_max_fraction=0.02,
        loss_per_coverage_fraction=0.5,
    )
    farm = CohortFarm(config, bird_config)
    first = farm.advance_day(
        farm.initial_state(date(2025, 1, 1), np.random.default_rng(123)),
        0,
        np.random.default_rng(123),
    )
    second = farm.advance_day(
        farm.initial_state(date(2025, 1, 1), np.random.default_rng(123)),
        0,
        np.random.default_rng(123),
    )

    assert [event.to_record() for event in first.events] == [
        event.to_record() for event in second.events
    ]
