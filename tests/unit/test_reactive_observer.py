from __future__ import annotations

import numpy as np

from solarclean.config.models import ReactiveCVObserverConfig, ReactiveInspectionConfig
from solarclean.domain.farm.representation import CohortState
from solarclean.domain.reactive_cv.observer import (
    PerfectInformationObserver,
    StatisticalCVObserver,
)


def _inspection(threshold: float = 0.9) -> ReactiveInspectionConfig:
    return ReactiveInspectionConfig(dirty_soiling_ratio_threshold=threshold)


def _dirty_cohort() -> CohortState:
    return CohortState(cohort_id=0, panel_count=100, dust_soiling_ratio=0.7)


def _clean_cohort() -> CohortState:
    return CohortState(cohort_id=1, panel_count=100, dust_soiling_ratio=0.99)


def test_perfect_information_observer_matches_ground_truth_exactly() -> None:
    observer = PerfectInformationObserver(_inspection())
    rng = np.random.default_rng(0)

    dirty_obs = observer.observe(_dirty_cohort(), rng)
    clean_obs = observer.observe(_clean_cohort(), rng)

    assert dirty_obs.detected_dirty is True
    assert dirty_obs.confidence == 1.0
    assert dirty_obs._ground_truth_dirty is True
    assert clean_obs.detected_dirty is False
    assert clean_obs._ground_truth_dirty is False


def test_statistical_observer_recall_matches_configured_rate_over_many_trials() -> None:
    config = ReactiveCVObserverConfig(
        recall_fraction=0.8,
        false_positive_rate=0.0,
        missed_image_fraction=0.0,
        confidence_std_fraction=0.0,
    )
    observer = StatisticalCVObserver(config, _inspection())
    rng = np.random.default_rng(1)
    cohort = _dirty_cohort()

    detections = [observer.observe(cohort, rng).detected_dirty for _ in range(4000)]
    empirical_recall = sum(detections) / len(detections)

    assert abs(empirical_recall - 0.8) < 0.03


def test_statistical_observer_false_positive_rate_matches_configured_rate() -> None:
    config = ReactiveCVObserverConfig(
        recall_fraction=1.0,
        false_positive_rate=0.1,
        missed_image_fraction=0.0,
        confidence_std_fraction=0.0,
    )
    observer = StatisticalCVObserver(config, _inspection())
    rng = np.random.default_rng(2)
    cohort = _clean_cohort()

    detections = [observer.observe(cohort, rng).detected_dirty for _ in range(4000)]
    empirical_fpr = sum(detections) / len(detections)

    assert abs(empirical_fpr - 0.1) < 0.03


def test_missed_image_short_circuits_detection() -> None:
    config = ReactiveCVObserverConfig(missed_image_fraction=1.0)
    observer = StatisticalCVObserver(config, _inspection())
    rng = np.random.default_rng(3)

    observation = observer.observe(_dirty_cohort(), rng)

    assert observation.image_captured is False
    assert observation.detected_dirty is False
    assert observation.confidence == 0.0


def test_confidence_is_bounded_between_zero_and_one() -> None:
    config = ReactiveCVObserverConfig(
        base_confidence=0.95,
        confidence_std_fraction=1.0,
        missed_image_fraction=0.0,
    )
    observer = StatisticalCVObserver(config, _inspection())
    rng = np.random.default_rng(4)

    for _ in range(500):
        observation = observer.observe(_dirty_cohort(), rng)
        assert 0.0 <= observation.confidence <= 1.0


def test_estimated_loss_is_bounded_between_zero_and_one() -> None:
    observer = PerfectInformationObserver(_inspection())
    rng = np.random.default_rng(5)
    cohort = CohortState(
        cohort_id=2,
        panel_count=100,
        dust_soiling_ratio=0.0,
        bird_drop_loss_fraction=0.8,
    )

    observation = observer.observe(cohort, rng)

    assert observation.estimated_loss_fraction == 1.0
