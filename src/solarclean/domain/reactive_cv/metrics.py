from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from solarclean.domain.scenario.contracts import AnnualScenarioResult, DailyScenarioResult


@dataclass(frozen=True)
class DetectionPerformance:
    true_positive_count: int
    false_positive_count: int
    false_negative_count: int
    true_negative_count: int
    missed_image_count: int
    system_dirty_cohort_count: int
    system_detected_dirty_count: int
    system_missed_dirty_count: int
    dirty_cleaning_count: int
    false_positive_cleaning_count: int

    @property
    def precision(self) -> float:
        denom = self.true_positive_count + self.false_positive_count
        return self.true_positive_count / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positive_count + self.false_negative_count
        return self.true_positive_count / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def system_detection_recall(self) -> float:
        denom = self.system_dirty_cohort_count
        return self.system_detected_dirty_count / denom if denom > 0 else 0.0

    @property
    def cleaning_precision(self) -> float:
        denom = self.dirty_cleaning_count + self.false_positive_cleaning_count
        return self.dirty_cleaning_count / denom if denom > 0 else 0.0

    def to_record(self) -> dict[str, object]:
        return {
            "true_positive_count": self.true_positive_count,
            "false_positive_count": self.false_positive_count,
            "false_negative_count": self.false_negative_count,
            "true_negative_count": self.true_negative_count,
            "missed_image_count": self.missed_image_count,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "system_dirty_cohort_count": self.system_dirty_cohort_count,
            "system_detected_dirty_count": self.system_detected_dirty_count,
            "system_missed_dirty_count": self.system_missed_dirty_count,
            "missed_contamination_count": self.system_missed_dirty_count,
            "system_detection_recall": self.system_detection_recall,
            "dirty_cleaning_count": self.dirty_cleaning_count,
            "false_positive_cleaning_count": self.false_positive_cleaning_count,
            "cleaning_precision": self.cleaning_precision,
        }


def summarize_detection_performance(result: AnnualScenarioResult) -> DetectionPerformance:
    """Aggregates realized precision/recall/F1 from daily confusion-matrix extensions.

    Reads only the `extension_*` confusion-matrix counters that the
    strategy records for evaluation purposes; this function is analytics,
    not part of the dispatch decision path.
    """
    tp = fp = fn = tn = missed = 0
    system_dirty = system_detected = system_missed = 0
    dirty_cleaning = false_positive_cleaning = 0
    for daily in result.daily_results:
        tp += _extension_int(daily, "inspection_true_positive_count")
        fp += _extension_int(daily, "inspection_false_positive_count")
        fn += _extension_int(daily, "inspection_false_negative_count")
        tn += _extension_int(daily, "inspection_true_negative_count")
        missed += _extension_int(daily, "inspection_missed_image_count")
        system_dirty += _extension_int(daily, "system_dirty_cohort_count")
        system_detected += _extension_int(daily, "system_detected_dirty_count")
        system_missed += _extension_int(daily, "system_missed_dirty_count")
        dirty_cleaning += _extension_int(daily, "dirty_cleaning_count")
        false_positive_cleaning += _extension_int(daily, "false_positive_cleaning_count")
    return DetectionPerformance(
        true_positive_count=tp,
        false_positive_count=fp,
        false_negative_count=fn,
        true_negative_count=tn,
        missed_image_count=missed,
        system_dirty_cohort_count=system_dirty,
        system_detected_dirty_count=system_detected,
        system_missed_dirty_count=system_missed,
        dirty_cleaning_count=dirty_cleaning,
        false_positive_cleaning_count=false_positive_cleaning,
    )


def _extension_int(daily: DailyScenarioResult, key: str) -> int:
    value = daily.extensions.get(key, 0)
    return int(cast(int, value))
