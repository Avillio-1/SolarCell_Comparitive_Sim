from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from types import MappingProxyType
from typing import Protocol, cast

import numpy as np
import pandas as pd

from solarclean.config.models import FarmConfig
from solarclean.domain.contamination.soiling import DailyEnvironment, SimulationEvent
from solarclean.domain.environment.weather import WeatherDataset
from solarclean.domain.events.tape import DailyEventInputs, ExogenousEventTape
from solarclean.domain.pv.model import CleanEnergyProfile


def _freeze_mapping(mapping: Mapping[str, object] | None) -> Mapping[str, object]:
    return cast(Mapping[str, object], MappingProxyType(dict(mapping or {})))


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    return value


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_safe(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


_EVENT_PHASE_ORDER: dict[str, int] = {
    "exogenous_morning": 0,
    "pre_generation_state": 1,
    "pv_generation": 2,
    "inspection": 3,
    "dispatch": 4,
    "cleaning": 5,
    "nighttime_condensation": 6,
    "post_day_state_update": 7,
}

_EVENT_TYPE_PHASES: dict[str, str] = {
    "dust_accumulation": "pre_generation_state",
    "heavy_dust_event": "pre_generation_state",
    "partial_rain_cleaning": "pre_generation_state",
    "full_rain_cleaning": "pre_generation_state",
    "bird_dropping_event": "pre_generation_state",
    "reactive_inspection": "inspection",
    "reactive_cleaning_dispatch": "dispatch",
    "reactive_cleaning_action": "cleaning",
    "coating_condensation": "nighttime_condensation",
    "coating_passive_dust_cleaning": "nighttime_condensation",
    "coating_bird_dropping_removal": "nighttime_condensation",
}

_EVENT_TYPE_ORDER: dict[str, int] = {
    "dust_accumulation": 10,
    "heavy_dust_event": 20,
    "partial_rain_cleaning": 30,
    "full_rain_cleaning": 30,
    "bird_dropping_event": 40,
    "reactive_inspection": 10,
    "reactive_cleaning_dispatch": 10,
    "reactive_cleaning_action": 10,
    "coating_condensation": 10,
    "coating_passive_dust_cleaning": 20,
    "coating_bird_dropping_removal": 30,
}


def _default_event_phase(event_type: str) -> str:
    return _EVENT_TYPE_PHASES.get(event_type, "post_day_state_update")


@dataclass(frozen=True)
class FrozenWeatherInput:
    _hourly: pd.DataFrame = field(repr=False)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_hourly", self._hourly.copy(deep=True))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    @classmethod
    def from_dataset(cls, dataset: WeatherDataset) -> FrozenWeatherInput:
        return cls(_hourly=dataset.hourly, metadata=dataset.metadata)

    @property
    def hourly(self) -> pd.DataFrame:
        return self._hourly.copy(deep=True)

    def to_dataset(self) -> WeatherDataset:
        return WeatherDataset(hourly=self.hourly, metadata=dict(self.metadata))


@dataclass(frozen=True)
class FrozenCleanEnergyInput:
    _hourly: pd.DataFrame = field(repr=False)
    _daily: pd.DataFrame = field(repr=False)
    annual_clean_energy_kwh: float
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_hourly", self._hourly.copy(deep=True))
        object.__setattr__(self, "_daily", self._daily.copy(deep=True))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    @classmethod
    def from_profile(cls, profile: CleanEnergyProfile) -> FrozenCleanEnergyInput:
        return cls(
            _hourly=profile.hourly,
            _daily=profile.daily,
            annual_clean_energy_kwh=profile.annual_clean_energy_kwh,
            metadata=profile.metadata,
        )

    @property
    def hourly(self) -> pd.DataFrame:
        return self._hourly.copy(deep=True)

    @property
    def daily(self) -> pd.DataFrame:
        return self._daily.copy(deep=True)

    def to_profile(self) -> CleanEnergyProfile:
        return CleanEnergyProfile(
            hourly=self.hourly,
            daily=self.daily,
            annual_clean_energy_kwh=self.annual_clean_energy_kwh,
            metadata=dict(self.metadata),
        )


@dataclass(frozen=True)
class ScenarioContext:
    weather: FrozenWeatherInput
    clean_energy: FrozenCleanEnergyInput
    event_tape: ExogenousEventTape | None = None
    farm_config: FarmConfig | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    @classmethod
    def from_inputs(
        cls,
        *,
        weather: WeatherDataset,
        clean_energy: CleanEnergyProfile,
        event_tape: ExogenousEventTape | None = None,
        farm_config: FarmConfig | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ScenarioContext:
        return cls(
            weather=FrozenWeatherInput.from_dataset(weather),
            clean_energy=FrozenCleanEnergyInput.from_profile(clean_energy),
            event_tape=event_tape,
            farm_config=farm_config,
            metadata=_freeze_mapping(metadata),
        )


@dataclass(frozen=True)
class DailyScenarioInput:
    date: date
    clean_energy_kwh: float
    clean_energy_per_panel_kwh: float
    environment: DailyEnvironment
    event_inputs: DailyEventInputs | None
    day_index: int


@dataclass(frozen=True)
class OperationalQuantities:
    inspections_count: int = 0
    cleaning_actions_count: int = 0
    coated_panel_count: int = 0
    crew_hours: float = 0.0
    drone_flight_hours: float = 0.0
    water_liters: float = 0.0
    energy_used_kwh: float = 0.0
    opex_cost: float = 0.0
    capex_cost: float = 0.0

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DomainEvent:
    date: date
    event_type: str
    magnitude: float
    description: str
    scenario_name: str
    cohort_id: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    event_sequence: int = 0
    event_phase: str = ""
    effective_for_energy_date: dt.date | None = None

    def __post_init__(self) -> None:
        cohort_id = None if self.cohort_id is None else int(self.cohort_id)
        phase = self.event_phase or _default_event_phase(self.event_type)
        effective_date = self.effective_for_energy_date
        if effective_date is None:
            effective_date = (
                self.date + dt.timedelta(days=1)
                if phase in {"cleaning", "nighttime_condensation"}
                else self.date
            )
        object.__setattr__(self, "cohort_id", cohort_id)
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        object.__setattr__(self, "event_sequence", int(self.event_sequence))
        object.__setattr__(self, "event_phase", phase)
        object.__setattr__(self, "effective_for_energy_date", effective_date)

    @classmethod
    def from_simulation_event(
        cls,
        event: SimulationEvent,
        *,
        scenario_name: str,
        metadata: Mapping[str, object] | None = None,
        event_phase: str | None = None,
        effective_for_energy_date: dt.date | None = None,
    ) -> DomainEvent:
        return cls(
            date=event.date,
            event_type=event.event_type,
            magnitude=event.magnitude,
            description=event.description,
            scenario_name=scenario_name,
            cohort_id=event.cohort_id,
            metadata=metadata or {},
            event_phase=event_phase or "",
            effective_for_energy_date=effective_for_energy_date,
        )

    def to_record(self) -> dict[str, object]:
        metadata = _json_safe(self.metadata)
        effective_date = self.effective_for_energy_date or self.date
        return {
            "date": self.date.isoformat(),
            "scenario_name": self.scenario_name,
            "event_sequence": self.event_sequence,
            "event_phase": self.event_phase,
            "effective_for_energy_date": effective_date.isoformat(),
            "event_type": self.event_type,
            "magnitude": self.magnitude,
            "description": self.description,
            "cohort_id": self.cohort_id,
            "metadata": json.dumps(metadata, sort_keys=True),
        }

    def to_simulation_event(self) -> SimulationEvent:
        return SimulationEvent(
            date=self.date,
            event_type=self.event_type,
            magnitude=self.magnitude,
            description=self.description,
            cohort_id=self.cohort_id,
        )


def ordered_domain_events(events: Sequence[DomainEvent]) -> tuple[DomainEvent, ...]:
    """Return events sorted by modeled phase and assigned per-day sequence numbers."""
    return _normalize_events(tuple(events))


def _normalize_events(events: tuple[DomainEvent, ...]) -> tuple[DomainEvent, ...]:
    ordered = [event for _, event in sorted(enumerate(events), key=_event_sort_key)]
    sequenced: list[DomainEvent] = []
    current_date: date | None = None
    sequence = 0
    for event in ordered:
        if event.date != current_date:
            current_date = event.date
            sequence = 1
        else:
            sequence += 1
        sequenced.append(replace(event, event_sequence=sequence))
    return tuple(sequenced)


def _event_sort_key(indexed_event: tuple[int, DomainEvent]) -> tuple[object, ...]:
    original_index, event = indexed_event
    cohort_sort = -1 if event.cohort_id is None else event.cohort_id
    return (
        event.date,
        _EVENT_PHASE_ORDER.get(event.event_phase, 10_000),
        _EVENT_TYPE_ORDER.get(event.event_type, 1_000),
        cohort_sort,
        event.event_type,
        event.description,
        event.magnitude,
        original_index,
    )


@dataclass(frozen=True)
class DailyScenarioResult:
    date: date
    scenario_name: str
    clean_energy_kwh: float
    actual_energy_kwh: float
    allow_above_clean_reference: bool = False
    operational: OperationalQuantities = field(default_factory=OperationalQuantities)
    events: tuple[DomainEvent, ...] = ()
    extensions: Mapping[str, object] = field(default_factory=dict)
    energy_loss_kwh: float = field(init=False)
    soiling_ratio: float = field(init=False)

    def __post_init__(self) -> None:
        if self.clean_energy_kwh < 0:
            raise ValueError("clean energy must be non-negative")
        if self.actual_energy_kwh < 0:
            raise ValueError("actual energy must be non-negative")
        if (
            not self.allow_above_clean_reference
            and self.actual_energy_kwh > self.clean_energy_kwh + 1e-9
        ):
            raise ValueError(
                "actual energy cannot exceed clean energy unless the scenario "
                "explicitly allows an above-reference physical gain"
            )
        loss = self.clean_energy_kwh - self.actual_energy_kwh
        ratio = self.actual_energy_kwh / self.clean_energy_kwh if self.clean_energy_kwh > 0 else 1.0
        object.__setattr__(self, "events", _normalize_events(tuple(self.events)))
        object.__setattr__(
            self,
            "extensions",
            _freeze_mapping({key: _freeze_value(value) for key, value in self.extensions.items()}),
        )
        object.__setattr__(self, "energy_loss_kwh", loss)
        object.__setattr__(self, "soiling_ratio", ratio)

    def to_record(self) -> dict[str, object]:
        record: dict[str, object] = {
            "date": self.date.isoformat(),
            "scenario_name": self.scenario_name,
            "clean_energy_kwh": self.clean_energy_kwh,
            "actual_energy_kwh": self.actual_energy_kwh,
            "allow_above_clean_reference": self.allow_above_clean_reference,
            "energy_loss_kwh": self.energy_loss_kwh,
            "soiling_ratio": self.soiling_ratio,
        }
        for key, value in self.operational.to_record().items():
            record[f"operational_{key}"] = value
        for key, value in self.extensions.items():
            safe = _json_safe(value)
            record[f"extension_{key}"] = (
                json.dumps(safe, sort_keys=True) if isinstance(safe, dict | list) else safe
            )
        return record


@dataclass(frozen=True)
class AnnualScenarioResult:
    scenario_name: str
    daily_results: tuple[DailyScenarioResult, ...]
    events: tuple[DomainEvent, ...] = ()
    extensions: Mapping[str, object] = field(default_factory=dict)
    annual_clean_energy_kwh: float = field(init=False)
    annual_actual_energy_kwh: float = field(init=False)
    annual_energy_loss_kwh: float = field(init=False)
    annual_energy_loss_percent: float = field(init=False)

    def __post_init__(self) -> None:
        daily = tuple(self.daily_results)
        events = (
            tuple(self.events)
            if self.events
            else tuple(event for result in daily for event in result.events)
        )
        annual_clean = sum(result.clean_energy_kwh for result in daily)
        annual_actual = sum(result.actual_energy_kwh for result in daily)
        annual_loss = annual_clean - annual_actual
        loss_percent = annual_loss / annual_clean * 100.0 if annual_clean > 0 else 0.0
        object.__setattr__(self, "daily_results", daily)
        object.__setattr__(self, "events", _normalize_events(events))
        object.__setattr__(
            self,
            "extensions",
            _freeze_mapping({key: _freeze_value(value) for key, value in self.extensions.items()}),
        )
        object.__setattr__(self, "annual_clean_energy_kwh", float(annual_clean))
        object.__setattr__(self, "annual_actual_energy_kwh", float(annual_actual))
        object.__setattr__(self, "annual_energy_loss_kwh", float(annual_loss))
        object.__setattr__(self, "annual_energy_loss_percent", float(loss_percent))

    def to_daily_frame(self) -> pd.DataFrame:
        return pd.DataFrame.from_records([result.to_record() for result in self.daily_results])

    def extension_keys(self) -> list[str]:
        keys = set(self.extensions.keys())
        for result in self.daily_results:
            keys.update(result.extensions.keys())
        return sorted(keys)

    def summary(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "scenario_name": self.scenario_name,
            "daily_result_count": len(self.daily_results),
            "event_count": len(self.events),
            "annual_clean_energy_kwh": self.annual_clean_energy_kwh,
            "annual_actual_energy_kwh": self.annual_actual_energy_kwh,
            "annual_energy_loss_kwh": self.annual_energy_loss_kwh,
            "annual_energy_loss_percent": self.annual_energy_loss_percent,
            "extension_keys": self.extension_keys(),
        }
        for key, value in self.extensions.items():
            payload[f"extension_{key}"] = _json_safe(value)
        return payload


@dataclass(frozen=True)
class StrategyStep:
    state: object
    result: DailyScenarioResult


class MitigationStrategy(Protocol):
    name: str

    def initial_state(
        self,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> object: ...

    def simulate_day(
        self,
        day_input: DailyScenarioInput,
        state: object,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> StrategyStep: ...


@dataclass(frozen=True)
class ScenarioComparisonInput:
    context: ScenarioContext
    strategies: Sequence[MitigationStrategy]
    random_seed: int
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategies", tuple(self.strategies))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True)
class ScenarioOutputBundle:
    summary: Mapping[str, object]
    daily_frame: pd.DataFrame
    events: tuple[DomainEvent, ...]
    extensions: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", _freeze_mapping(self.summary))
        object.__setattr__(self, "daily_frame", self.daily_frame.copy(deep=True))
        object.__setattr__(self, "events", _normalize_events(tuple(self.events)))
        object.__setattr__(self, "extensions", _freeze_mapping(self.extensions))
