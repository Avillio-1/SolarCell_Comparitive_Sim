from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

import numpy as np

from solarclean.config.models import RainfallCleaningConfig, SoilingConfig
from solarclean.domain.events.tape import DailyEventInputs


@dataclass(frozen=True)
class ContaminationState:
    dust_soiling_ratio: float = 1.0
    days_since_effective_rain: int = 0
    days_since_manual_cleaning: int = 0


@dataclass(frozen=True)
class DailyEnvironment:
    date: date
    precipitation_mm: float
    mean_relative_humidity_pct: float


@dataclass(frozen=True)
class SimulationEvent:
    date: date
    event_type: str
    magnitude: float
    description: str
    cohort_id: int | None = None

    def to_record(self) -> dict[str, object]:
        return {
            "date": self.date.isoformat(),
            "event_type": self.event_type,
            "magnitude": self.magnitude,
            "description": self.description,
            "cohort_id": self.cohort_id,
        }


@dataclass(frozen=True)
class SoilingUpdate:
    state: ContaminationState
    events: list[SimulationEvent]


class KimberStyleSoilingModel:
    """Configuration-driven empirical soiling model awaiting site calibration."""

    def __init__(self, config: SoilingConfig, rainfall: RainfallCleaningConfig) -> None:
        self.config = config
        self.rainfall = rainfall

    def update(
        self,
        previous_state: ContaminationState,
        environment: DailyEnvironment,
        rng: np.random.Generator,
        event_inputs: DailyEventInputs | None = None,
    ) -> SoilingUpdate:
        events: list[SimulationEvent] = []
        ratio = previous_state.dust_soiling_ratio
        month_multiplier = self.config.seasonal_multipliers.get(environment.date.month, 1.0)
        stochastic_multiplier = 1.0
        if event_inputs is not None:
            stochastic_multiplier = event_inputs.dust_multiplier
        elif self.config.stochastic_std_fraction > 0:
            stochastic_multiplier = max(
                0.0,
                float(rng.normal(1.0, self.config.stochastic_std_fraction)),
            )
        daily_loss = (
            self.config.base_daily_soiling_loss_fraction * month_multiplier * stochastic_multiplier
        )
        if daily_loss > 0:
            ratio -= daily_loss
            events.append(
                SimulationEvent(
                    date=environment.date,
                    event_type="dust_accumulation",
                    magnitude=daily_loss,
                    description="Daily provisional dust accumulation applied.",
                )
            )
        if event_inputs is not None:
            dust_loss = event_inputs.dust_event_loss_fraction
        elif rng.random() < self.config.dust_event_probability:
            dust_loss = float(
                rng.uniform(
                    self.config.dust_event_loss_min_fraction,
                    self.config.dust_event_loss_max_fraction,
                )
            )
        else:
            dust_loss = None
        if dust_loss is not None:
            ratio -= dust_loss
            events.append(
                SimulationEvent(
                    date=environment.date,
                    event_type="heavy_dust_event",
                    magnitude=dust_loss,
                    description="Stochastic localized heavy dust event.",
                )
            )
        ratio = max(self.config.minimum_soiling_ratio, min(1.0, ratio))
        effective_rain = False
        if environment.precipitation_mm >= self.rainfall.full_rain_cleaning_threshold_mm:
            restored = (1.0 - ratio) * self.rainfall.full_rain_cleaning_efficiency
            ratio += restored
            effective_rain = restored > 0
            events.append(
                SimulationEvent(
                    date=environment.date,
                    event_type="full_rain_cleaning",
                    magnitude=restored,
                    description="Strong rainfall natural cleaning applied.",
                )
            )
        elif environment.precipitation_mm >= self.rainfall.partial_rain_threshold_mm:
            restored = (1.0 - ratio) * self.rainfall.partial_rain_cleaning_efficiency
            ratio += restored
            effective_rain = restored > 0
            events.append(
                SimulationEvent(
                    date=environment.date,
                    event_type="partial_rain_cleaning",
                    magnitude=restored,
                    description="Partial rainfall natural cleaning applied.",
                )
            )
        ratio = max(self.config.minimum_soiling_ratio, min(1.0, ratio))
        state = replace(
            previous_state,
            dust_soiling_ratio=ratio,
            days_since_effective_rain=0
            if effective_rain
            else previous_state.days_since_effective_rain + 1,
            days_since_manual_cleaning=previous_state.days_since_manual_cleaning + 1,
        )
        return SoilingUpdate(state=state, events=events)
