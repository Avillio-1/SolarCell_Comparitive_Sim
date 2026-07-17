from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Any

from solarclean.config.models import (
    BirdDroppingConfig,
    FarmConfig,
    RainfallCleaningConfig,
    SoilingConfig,
)
from solarclean.domain.random.streams import RngStream, RngStreamFactory


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    return value


def _freeze_mapping(mapping: Mapping[str, object] | None) -> MappingProxyType[str, object]:
    return MappingProxyType(
        {str(key): _freeze_value(value) for key, value in (mapping or {}).items()}
    )


def _thaw_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_thaw_value(item) for item in value]
    return value


@dataclass(frozen=True)
class ExogenousEvent:
    date: date
    stream: str
    event_type: str
    value: float
    cohort_id: int | None = None
    metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def to_record(self) -> dict[str, object]:
        return {
            "date": self.date.isoformat(),
            "stream": self.stream,
            "event_type": self.event_type,
            "value": self.value,
            "cohort_id": self.cohort_id,
            "metadata": _thaw_value(self.metadata or {}),
        }

    @classmethod
    def from_record(cls, record: dict[str, object]) -> ExogenousEvent:
        raw_metadata = record.get("metadata", {})
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        cohort_value = record.get("cohort_id")
        raw_value = record["value"]
        if not isinstance(raw_value, (str, int, float)):
            raise ValueError("event value must be numeric")
        if cohort_value is not None and not isinstance(cohort_value, (str, int, float)):
            raise ValueError("cohort_id must be numeric or null")
        return cls(
            date=date.fromisoformat(str(record["date"])),
            stream=str(record["stream"]),
            event_type=str(record["event_type"]),
            value=float(raw_value),
            cohort_id=None if cohort_value is None else int(cohort_value),
            metadata=metadata,
        )


@dataclass(frozen=True)
class DailyEventInputs:
    date: date
    dust_multiplier: float = 1.0
    dust_event_loss_fraction: float | None = None
    cohort_variation_multipliers: MappingProxyType[int, float] = MappingProxyType({})
    bird_coverage_additions: MappingProxyType[int, float] = MappingProxyType({})


@dataclass(frozen=True)
class ExogenousEventTape:
    seed: int
    events: tuple[ExogenousEvent, ...]
    metadata: Mapping[str, object] = MappingProxyType({})
    _events_by_date: MappingProxyType[date, tuple[ExogenousEvent, ...]] = field(
        init=False,
        repr=False,
        compare=False,
    )
    _checksum: str | None = field(
        init=False,
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        sorted_events = tuple(
            sorted(
                self.events,
                key=lambda event: (
                    event.date.isoformat(),
                    event.stream,
                    event.event_type,
                    -1 if event.cohort_id is None else event.cohort_id,
                ),
            )
        )
        object.__setattr__(self, "events", sorted_events)
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        events_by_date: dict[date, list[ExogenousEvent]] = {}
        for event in sorted_events:
            events_by_date.setdefault(event.date, []).append(event)
        object.__setattr__(
            self,
            "_events_by_date",
            MappingProxyType(
                {event_date: tuple(events) for event_date, events in events_by_date.items()}
            ),
        )

    def to_records(self) -> list[dict[str, object]]:
        return [event.to_record() for event in self.events]

    def to_json(self) -> str:
        payload = {
            "seed": self.seed,
            "metadata": _thaw_value(self.metadata),
            "events": self.to_records(),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, payload: str) -> ExogenousEventTape:
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise ValueError("event tape JSON must contain an object")
        events = raw.get("events", [])
        if not isinstance(events, list):
            raise ValueError("event tape JSON events must be a list")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return cls(
            seed=int(raw["seed"]),
            events=tuple(ExogenousEvent.from_record(record) for record in events),
            metadata=metadata,
        )

    def checksum(self) -> str:
        cached = self._checksum
        if cached is None:
            cached = hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()
            # The tape and all nested values are immutable, so its checksum
            # cannot become stale. Scenario isolation asks for this value
            # repeatedly; memoizing avoids serializing tens of thousands of
            # events once per scenario.
            object.__setattr__(self, "_checksum", cached)
        return cached

    def to_daily_inputs(self, day: date) -> DailyEventInputs:
        dust_multiplier = 1.0
        dust_event_loss: float | None = None
        cohort_variation: dict[int, float] = {}
        bird_coverage: dict[int, float] = {}
        for event in self._events_by_date.get(day, ()):
            if event.event_type == "dust_stochastic_multiplier":
                dust_multiplier = event.value
            elif event.event_type == "heavy_dust_event_loss":
                dust_event_loss = event.value
            elif event.event_type == "cohort_variation_multiplier" and event.cohort_id is not None:
                cohort_variation[event.cohort_id] = event.value
            elif event.event_type == "bird_coverage_addition" and event.cohort_id is not None:
                bird_coverage[event.cohort_id] = event.value
        return DailyEventInputs(
            date=day,
            dust_multiplier=dust_multiplier,
            dust_event_loss_fraction=dust_event_loss,
            cohort_variation_multipliers=MappingProxyType(cohort_variation),
            bird_coverage_additions=MappingProxyType(bird_coverage),
        )


def generate_event_tape(
    *,
    dates: Iterable[date],
    seed: int,
    soiling: SoilingConfig,
    rainfall: RainfallCleaningConfig,
    farm: FarmConfig,
    birds: BirdDroppingConfig,
) -> ExogenousEventTape:
    del rainfall
    factory = RngStreamFactory(seed)
    dust_rng = factory.generator(RngStream.DUST)
    dust_event_rng = factory.generator(RngStream.DUST_EVENT)
    bird_rng = factory.generator(RngStream.BIRD)
    cohort_rng = factory.generator(RngStream.COHORT_VARIATION)
    events: list[ExogenousEvent] = []
    ordered_dates = tuple(sorted(dates))
    for day in ordered_dates:
        multiplier = 1.0
        if soiling.stochastic_std_fraction > 0:
            multiplier = max(0.0, float(dust_rng.normal(1.0, soiling.stochastic_std_fraction)))
        events.append(
            _event(
                day,
                RngStream.DUST,
                "dust_stochastic_multiplier",
                multiplier,
            )
        )
        if dust_event_rng.random() < soiling.dust_event_probability:
            events.append(
                _event(
                    day,
                    RngStream.DUST_EVENT,
                    "heavy_dust_event_loss",
                    float(
                        dust_event_rng.uniform(
                            soiling.dust_event_loss_min_fraction,
                            soiling.dust_event_loss_max_fraction,
                        )
                    ),
                )
            )
        for cohort_id in range(farm.cohort_count):
            variation = 1.0
            if farm.cohort_soiling_variation_fraction > 0:
                variation = max(
                    0.0,
                    float(cohort_rng.normal(1.0, farm.cohort_soiling_variation_fraction)),
                )
            events.append(
                _event(
                    day,
                    RngStream.COHORT_VARIATION,
                    "cohort_variation_multiplier",
                    variation,
                    cohort_id=cohort_id,
                )
            )
            if bird_rng.random() < birds.event_probability_per_cohort_day:
                coverage = float(
                    bird_rng.uniform(birds.coverage_min_fraction, birds.coverage_max_fraction)
                )
                events.append(
                    _event(
                        day,
                        RngStream.BIRD,
                        "bird_coverage_addition",
                        coverage,
                        cohort_id=cohort_id,
                    )
                )
    return ExogenousEventTape(
        seed=seed,
        events=tuple(events),
        metadata={
            "version": "phase-3.5",
            "stream_names": [stream.value for stream in RngStream],
            "date_count": len(ordered_dates),
        },
    )


def _event(
    day: date,
    stream: RngStream,
    event_type: str,
    value: float,
    cohort_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExogenousEvent:
    return ExogenousEvent(
        date=day,
        stream=stream.value,
        event_type=event_type,
        value=value,
        cohort_id=cohort_id,
        metadata=metadata or {},
    )
