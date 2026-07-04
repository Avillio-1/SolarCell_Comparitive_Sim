from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType

import numpy as np

from solarclean.domain.farm.representation import CohortState


@dataclass(frozen=True)
class ReactiveScenarioState:
    """True (ground-truth) farm state plus reactive-scenario bookkeeping.

    `cohorts` reuses the same `CohortState` shape as the baseline and
    coating scenarios so all three scenarios represent farm truth
    identically. Only `cv_rng`-derived, observation-shaped values may be
    passed to dispatch logic; `cohorts` itself must never reach it.
    """

    date: date
    cohorts: tuple[CohortState, ...]
    cv_rng: np.random.Generator = field(repr=False, compare=False)
    days_since_inspection: MappingProxyType[int, int] = field(
        default_factory=lambda: MappingProxyType({})
    )
    cleaning_queue: tuple[int, ...] = ()
    queue_age_days: tuple[int, ...] = ()

    def cohort_by_id(self, cohort_id: int) -> CohortState:
        for cohort in self.cohorts:
            if cohort.cohort_id == cohort_id:
                return cohort
        raise KeyError(f"unknown cohort_id {cohort_id}")
