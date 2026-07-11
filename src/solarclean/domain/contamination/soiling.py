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
    cementation_index: float = 0.0


@dataclass(frozen=True)
class DailyEnvironment:
    date: date
    precipitation_mm: float
    mean_relative_humidity_pct: float
    max_relative_humidity_pct: float | None = None

    @property
    def dew_relative_humidity_pct(self) -> float:
        """Humidity signal used for dew formation: the daily peak (nighttime)
        when available, otherwise the daily mean as a conservative fallback."""
        if self.max_relative_humidity_pct is not None:
            return self.max_relative_humidity_pct
        return self.mean_relative_humidity_pct


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
    energy_state: ContaminationState
    state: ContaminationState
    events: list[SimulationEvent]
    dew_risk: float = 0.0
    rain_efficiency_multiplier: float = 1.0


class KimberStyleSoilingModel:
    """Configuration-driven empirical soiling model awaiting site calibration."""

    def __init__(self, config: SoilingConfig, rainfall: RainfallCleaningConfig) -> None:
        self.config = config
        self.rainfall = rainfall

    def dew_risk(self, environment: DailyEnvironment) -> float:
        """Fraction 0..1 of full dew formation for the day, from peak humidity."""
        cementation = self.config.dew_cementation
        if not cementation.enabled:
            return 0.0
        humidity = environment.dew_relative_humidity_pct
        span = (
            cementation.saturation_relative_humidity_pct - cementation.onset_relative_humidity_pct
        )
        risk = (humidity - cementation.onset_relative_humidity_pct) / span
        return min(1.0, max(0.0, risk))

    def rain_efficiency_multiplier(self, previous_state: ContaminationState) -> float:
        """Rainfall cleaning efficiency multiplier given the cemented-crust state."""
        cementation = self.config.dew_cementation
        if not cementation.enabled:
            return 1.0
        index = min(1.0, max(0.0, previous_state.cementation_index))
        return 1.0 - cementation.max_rain_efficiency_penalty * index

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
        dew_risk = self.dew_risk(environment)
        rain_multiplier = self.rain_efficiency_multiplier(previous_state)
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
        cementation_loss = (
            daily_loss * (self.config.dew_cementation.max_soiling_rate_multiplier - 1.0) * dew_risk
        )
        if cementation_loss > 0:
            ratio -= cementation_loss
            events.append(
                SimulationEvent(
                    date=environment.date,
                    event_type="dew_cementation_adhesion",
                    magnitude=cementation_loss,
                    description="Dew-cemented extra dust retention on a humid night.",
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
        energy_state = replace(previous_state, dust_soiling_ratio=ratio)
        effective_rain = False
        full_rain = False
        if environment.precipitation_mm >= self.rainfall.full_rain_cleaning_threshold_mm:
            full_rain = True
            restored = (1.0 - ratio) * self.rainfall.full_rain_cleaning_efficiency * rain_multiplier
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
            restored = (
                (1.0 - ratio) * self.rainfall.partial_rain_cleaning_efficiency * rain_multiplier
            )
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
            cementation_index=self._next_cementation_index(
                previous_state.cementation_index,
                dew_risk=dew_risk,
                full_rain=full_rain,
            ),
        )
        return SoilingUpdate(
            energy_state=energy_state,
            state=state,
            events=events,
            dew_risk=dew_risk,
            rain_efficiency_multiplier=rain_multiplier,
        )

    def _next_cementation_index(
        self,
        current_index: float,
        *,
        dew_risk: float,
        full_rain: bool,
    ) -> float:
        """Crust state: relaxes toward the day's dew risk over memory_days;
        a full-cleaning rain dissolves and washes the crust away."""
        cementation = self.config.dew_cementation
        if not cementation.enabled or full_rain:
            return 0.0
        index = current_index + (dew_risk - current_index) / cementation.memory_days
        return min(1.0, max(0.0, index))
