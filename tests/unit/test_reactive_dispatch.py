from __future__ import annotations

import dataclasses

from solarclean.config.models import ReactiveDispatchConfig
from solarclean.domain.reactive_cv.dispatch import (
    DispatchSignal,
    ThresholdDispatchPolicy,
    to_dispatch_signal,
)
from solarclean.domain.reactive_cv.observer import CVObservation


def _config(**overrides: object) -> ReactiveDispatchConfig:
    defaults: dict[str, object] = {
        "estimated_loss_threshold_fraction": 0.05,
        "confidence_threshold": 0.5,
        "max_queue_age_days": 14,
    }
    defaults.update(overrides)
    return ReactiveDispatchConfig(**defaults)  # type: ignore[arg-type]


def test_dispatch_signal_has_no_ground_truth_field() -> None:
    """Structural enforcement: the type dispatch consumes cannot carry truth."""
    field_names = {field.name for field in dataclasses.fields(DispatchSignal)}
    assert "_ground_truth_dirty" not in field_names
    assert field_names == {"cohort_id", "estimated_loss_fraction", "confidence"}


def test_to_dispatch_signal_drops_ground_truth_and_undetected_observations() -> None:
    detected = CVObservation(
        cohort_id=1,
        image_captured=True,
        detected_dirty=True,
        estimated_loss_fraction=0.2,
        confidence=0.9,
        _ground_truth_dirty=True,
    )
    missed = CVObservation(
        cohort_id=2,
        image_captured=False,
        detected_dirty=False,
        estimated_loss_fraction=0.0,
        confidence=0.0,
        _ground_truth_dirty=True,
    )
    not_detected = CVObservation(
        cohort_id=3,
        image_captured=True,
        detected_dirty=False,
        estimated_loss_fraction=0.0,
        confidence=0.9,
        _ground_truth_dirty=False,
    )

    signal = to_dispatch_signal(detected)
    assert signal == DispatchSignal(cohort_id=1, estimated_loss_fraction=0.2, confidence=0.9)
    assert to_dispatch_signal(missed) is None
    assert to_dispatch_signal(not_detected) is None


def test_to_dispatch_signal_bounds_loss_and_confidence() -> None:
    observation = CVObservation(
        cohort_id=4,
        image_captured=True,
        detected_dirty=True,
        estimated_loss_fraction=1.5,
        confidence=-0.2,
        _ground_truth_dirty=True,
    )

    signal = to_dispatch_signal(observation)

    assert signal == DispatchSignal(cohort_id=4, estimated_loss_fraction=1.0, confidence=0.0)


def test_selects_cohorts_above_threshold_respecting_crew_capacity() -> None:
    policy = ThresholdDispatchPolicy(_config(estimated_loss_threshold_fraction=0.05))
    signals = (
        DispatchSignal(cohort_id=1, estimated_loss_fraction=0.10, confidence=0.9),
        DispatchSignal(cohort_id=2, estimated_loss_fraction=0.20, confidence=0.9),
        DispatchSignal(
            cohort_id=3, estimated_loss_fraction=0.01, confidence=0.9
        ),  # below threshold
        DispatchSignal(cohort_id=4, estimated_loss_fraction=0.30, confidence=0.1),  # low confidence
    )

    decision = policy.select_for_cleaning(
        signals,
        current_queue=(),
        current_queue_age_days=(),
        crew_daily_capacity=5,
    )

    assert set(decision.to_clean_ids) == {1, 2}


def test_crew_capacity_limits_cleaning_and_keeps_remainder_queued() -> None:
    policy = ThresholdDispatchPolicy(_config())
    signals = tuple(
        DispatchSignal(cohort_id=i, estimated_loss_fraction=0.5, confidence=0.9) for i in range(5)
    )

    decision = policy.select_for_cleaning(
        signals,
        current_queue=(),
        current_queue_age_days=(),
        crew_daily_capacity=2,
    )

    assert len(decision.to_clean_ids) == 2
    assert len(decision.updated_queue) == 3
    assert set(decision.to_clean_ids) | set(decision.updated_queue) == {0, 1, 2, 3, 4}


def test_older_queued_cohorts_are_prioritized_over_new_flags() -> None:
    policy = ThresholdDispatchPolicy(_config())
    decision = policy.select_for_cleaning(
        (DispatchSignal(cohort_id=99, estimated_loss_fraction=0.5, confidence=0.9),),
        current_queue=(1, 2),
        current_queue_age_days=(5, 3),
        crew_daily_capacity=1,
    )
    # Cohort 1 has waited longest (age 5); it should be cleaned first even
    # though cohort 99 was just freshly flagged.
    assert decision.to_clean_ids == (1,)


def test_queue_persists_and_ages_across_calls() -> None:
    policy = ThresholdDispatchPolicy(_config(max_queue_age_days=14))
    decision = policy.select_for_cleaning(
        (),
        current_queue=(7,),
        current_queue_age_days=(0,),
        crew_daily_capacity=0,
    )
    assert decision.updated_queue == (7,)
    assert decision.updated_queue_age_days == (1,)


def test_entries_older_than_max_queue_age_are_dropped() -> None:
    policy = ThresholdDispatchPolicy(_config(max_queue_age_days=3))
    decision = policy.select_for_cleaning(
        (),
        current_queue=(7,),
        current_queue_age_days=(3,),
        crew_daily_capacity=0,
    )
    assert decision.updated_queue == ()


def test_duplicate_flags_do_not_double_queue_a_cohort() -> None:
    policy = ThresholdDispatchPolicy(_config())
    decision = policy.select_for_cleaning(
        (DispatchSignal(cohort_id=1, estimated_loss_fraction=0.5, confidence=0.9),),
        current_queue=(1,),
        current_queue_age_days=(2,),
        crew_daily_capacity=0,
    )
    assert decision.updated_queue == (1,)
    assert decision.updated_queue_age_days == (3,)
