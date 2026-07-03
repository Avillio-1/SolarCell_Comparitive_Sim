from __future__ import annotations

from dataclasses import dataclass

from solarclean.config.models import ReactiveDispatchConfig
from solarclean.domain.reactive_cv.observer import CVObservation


@dataclass(frozen=True)
class DispatchSignal:
    """The only view of an inspection result the dispatch policy may use.

    Deliberately excludes any ground-truth field. `CVObservation` carries
    a `_ground_truth_dirty` label for evaluation; that field is dropped
    here so it is structurally impossible for `ThresholdDispatchPolicy`
    to read it, by construction rather than by convention alone.
    """

    cohort_id: int
    estimated_loss_fraction: float
    confidence: float


def to_dispatch_signal(observation: CVObservation) -> DispatchSignal | None:
    if not observation.image_captured or not observation.detected_dirty:
        return None
    return DispatchSignal(
        cohort_id=observation.cohort_id,
        estimated_loss_fraction=observation.estimated_loss_fraction,
        confidence=observation.confidence,
    )


@dataclass(frozen=True)
class DispatchDecision:
    to_clean_ids: tuple[int, ...]
    updated_queue: tuple[int, ...]
    updated_queue_age_days: tuple[int, ...]


class ThresholdDispatchPolicy:
    """Selects cohorts for cleaning using only estimated loss and confidence."""

    def __init__(self, config: ReactiveDispatchConfig) -> None:
        self.config = config

    def select_for_cleaning(
        self,
        signals: tuple[DispatchSignal, ...],
        *,
        current_queue: tuple[int, ...],
        current_queue_age_days: tuple[int, ...],
        crew_daily_capacity: int,
    ) -> DispatchDecision:
        queue: dict[int, int] = dict(zip(current_queue, current_queue_age_days, strict=True))
        # age everyone already in queue by one day before adding today's flags
        queue = {cohort_id: age + 1 for cohort_id, age in queue.items()}
        for signal in signals:
            if (
                signal.estimated_loss_fraction >= self.config.estimated_loss_threshold_fraction
                and signal.confidence >= self.config.confidence_threshold
                and signal.cohort_id not in queue
            ):
                queue[signal.cohort_id] = 0
        # drop cohorts that have aged out without being cleaned
        queue = {
            cohort_id: age
            for cohort_id, age in queue.items()
            if age <= self.config.max_queue_age_days
        }
        ordered = sorted(queue.items(), key=lambda item: (-item[1], item[0]))
        to_clean = tuple(cohort_id for cohort_id, _ in ordered[:crew_daily_capacity])
        remaining = {
            cohort_id: age for cohort_id, age in queue.items() if cohort_id not in to_clean
        }
        remaining_ids = tuple(sorted(remaining.keys()))
        remaining_ages = tuple(remaining[cohort_id] for cohort_id in remaining_ids)
        return DispatchDecision(
            to_clean_ids=to_clean,
            updated_queue=remaining_ids,
            updated_queue_age_days=remaining_ages,
        )
