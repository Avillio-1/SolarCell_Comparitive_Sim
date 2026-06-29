from __future__ import annotations

from enum import StrEnum

import numpy as np


class RngStream(StrEnum):
    DUST = "dust"
    DUST_EVENT = "dust_event"
    BIRD = "bird"
    COHORT_VARIATION = "cohort_variation"
    FUTURE_SCENARIO = "future_scenario"


class RngStreamFactory:
    """Creates deterministic, independent RNG streams from one root seed."""

    _ORDER: tuple[RngStream, ...] = (
        RngStream.DUST,
        RngStream.DUST_EVENT,
        RngStream.BIRD,
        RngStream.COHORT_VARIATION,
        RngStream.FUTURE_SCENARIO,
    )

    def __init__(self, seed: int) -> None:
        self.seed = seed
        sequences = np.random.SeedSequence(seed).spawn(len(self._ORDER))
        self._sequences = dict(zip(self._ORDER, sequences, strict=True))

    def generator(self, stream: RngStream) -> np.random.Generator:
        return np.random.default_rng(self._sequences[stream])
