from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from solarclean.config.models import ReactiveCVObserverConfig, ReactiveInspectionConfig
from solarclean.domain.farm.representation import CohortState


@dataclass(frozen=True)
class CVObservation:
    """What the dispatch policy is allowed to see. No true-state fields."""

    cohort_id: int
    image_captured: bool
    detected_dirty: bool
    estimated_loss_fraction: float
    confidence: float
    # Ground-truth label, carried ONLY for offline evaluation/metrics.
    # `dispatch.py` must never read this field.
    _ground_truth_dirty: bool


class CVObserver(Protocol):
    def observe(self, cohort: CohortState, rng: np.random.Generator) -> CVObservation: ...


class StatisticalCVObserver:
    """Imperfect observer: recall, false-positive rate, missed images, noise."""

    def __init__(
        self,
        observer: ReactiveCVObserverConfig,
        inspection: ReactiveInspectionConfig,
    ) -> None:
        self.observer = observer
        self.inspection = inspection

    def observe(self, cohort: CohortState, rng: np.random.Generator) -> CVObservation:
        ground_truth_dirty = _is_dirty(cohort, self.inspection)
        if rng.random() < self.observer.missed_image_fraction:
            return CVObservation(
                cohort_id=cohort.cohort_id,
                image_captured=False,
                detected_dirty=False,
                estimated_loss_fraction=0.0,
                confidence=0.0,
                _ground_truth_dirty=ground_truth_dirty,
            )
        if ground_truth_dirty:
            detected = rng.random() < self.observer.recall_fraction
        else:
            detected = rng.random() < self.observer.false_positive_rate
        true_loss_fraction = (
            max(0.0, 1.0 - cohort.dust_soiling_ratio) + cohort.bird_drop_loss_fraction
        )
        noise = float(rng.normal(0.0, self.observer.severity_error_std_fraction))
        estimated_loss = max(0.0, true_loss_fraction + noise) if detected else 0.0
        confidence = float(
            np.clip(
                rng.normal(self.observer.base_confidence, self.observer.confidence_std_fraction),
                0.0,
                1.0,
            )
        )
        return CVObservation(
            cohort_id=cohort.cohort_id,
            image_captured=True,
            detected_dirty=detected,
            estimated_loss_fraction=estimated_loss,
            confidence=confidence,
            _ground_truth_dirty=ground_truth_dirty,
        )


class PerfectInformationObserver:
    """Benchmark observer with no CV error, for isolating the cost of CV error."""

    def __init__(self, inspection: ReactiveInspectionConfig) -> None:
        self.inspection = inspection

    def observe(self, cohort: CohortState, rng: np.random.Generator) -> CVObservation:
        del rng
        ground_truth_dirty = _is_dirty(cohort, self.inspection)
        true_loss_fraction = (
            max(0.0, 1.0 - cohort.dust_soiling_ratio) + cohort.bird_drop_loss_fraction
        )
        return CVObservation(
            cohort_id=cohort.cohort_id,
            image_captured=True,
            detected_dirty=ground_truth_dirty,
            estimated_loss_fraction=true_loss_fraction if ground_truth_dirty else 0.0,
            confidence=1.0,
            _ground_truth_dirty=ground_truth_dirty,
        )


def _is_dirty(cohort: CohortState, inspection: ReactiveInspectionConfig) -> bool:
    return (
        cohort.dust_soiling_ratio < inspection.dirty_soiling_ratio_threshold
        or cohort.bird_drop_loss_fraction > 0.0
    )
