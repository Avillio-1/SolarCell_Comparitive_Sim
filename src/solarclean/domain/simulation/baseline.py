from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

import numpy as np
import pandas as pd

from solarclean.config.models import FarmConfig
from solarclean.domain.contamination.soiling import (
    ContaminationState,
    DailyEnvironment,
    KimberStyleSoilingModel,
    SimulationEvent,
)
from solarclean.domain.environment.weather import WeatherDataset
from solarclean.domain.events.tape import ExogenousEventTape
from solarclean.domain.farm.representation import CohortFarm, FarmState
from solarclean.domain.pv.model import CleanEnergyProfile


@dataclass
class BaselineSimulationResult:
    daily: pd.DataFrame
    events: list[SimulationEvent]
    annual_clean_energy_kwh: float
    annual_actual_energy_kwh: float
    annual_soiling_loss_kwh: float
    annual_soiling_loss_percent: float
    cohort_daily: pd.DataFrame | None = None


class BaselineSimulationEngine:
    def __init__(
        self,
        soiling_model: KimberStyleSoilingModel,
        farm: CohortFarm | None = None,
        farm_config: FarmConfig | None = None,
    ) -> None:
        self.soiling_model = soiling_model
        self.farm = farm
        self.farm_config = farm_config

    def run(
        self,
        clean: CleanEnergyProfile,
        weather: WeatherDataset,
        random_seed: int,
        event_tape: ExogenousEventTape | None = None,
    ) -> BaselineSimulationResult:
        rng = np.random.default_rng(random_seed)
        contamination_state = ContaminationState()
        events: list[SimulationEvent] = []
        records: list[dict[str, object]] = []
        cohort_records: list[dict[str, object]] = []
        farm_state: FarmState | None = None
        if self.farm is not None:
            first_day = pd.Timestamp(str(clean.daily.index[0])).date()
            farm_state = self.farm.initial_state(first_day, rng)

        weather_daily = _daily_environment(weather)
        for day_index, row in clean.daily.iterrows():
            day = pd.Timestamp(str(day_index)).date()
            environment = weather_daily[day]
            event_inputs = event_tape.to_daily_inputs(day) if event_tape is not None else None
            update = self.soiling_model.update(
                contamination_state, environment, rng, event_inputs=event_inputs
            )
            contamination_state = update.state
            events.extend(update.events)
            clean_energy = float(row["clean_ac_energy_kwh"])
            if self.farm is None:
                actual_energy = clean_energy * contamination_state.dust_soiling_ratio
                cohort_count = 1
            else:
                assert farm_state is not None
                varied_state = _apply_dust_to_farm(
                    farm_state,
                    contamination_state.dust_soiling_ratio,
                    self.farm_config.cohort_soiling_variation_fraction if self.farm_config else 0.0,
                    rng,
                    dict(event_inputs.cohort_variation_multipliers) if event_inputs else None,
                )
                advanced = self.farm.advance_day(
                    varied_state,
                    environment.precipitation_mm,
                    rng,
                    dict(event_inputs.bird_coverage_additions) if event_inputs else None,
                )
                farm_state = advanced.state
                events.extend(advanced.events)
                clean_per_panel = clean_energy / farm_state.total_panel_count
                farm_energy = self.farm.calculate_daily_energy(farm_state, clean_per_panel)
                actual_energy = min(clean_energy, farm_energy.actual_energy_kwh)
                cohort_count = len(farm_state.cohorts)
                for cohort in farm_state.cohorts:
                    cohort_records.append(
                        {
                            "date": day.isoformat(),
                            "cohort_id": cohort.cohort_id,
                            "panel_count": cohort.panel_count,
                            "dust_soiling_ratio": cohort.dust_soiling_ratio,
                            "bird_drop_coverage_fraction": cohort.bird_drop_coverage_fraction,
                            "bird_drop_loss_fraction": cohort.bird_drop_loss_fraction,
                            "actual_energy_kwh": clean_per_panel
                            * cohort.panel_count
                            * cohort.dust_soiling_ratio
                            * (1.0 - cohort.bird_drop_loss_fraction),
                        }
                    )
            actual_energy = min(clean_energy, max(0.0, actual_energy))
            records.append(
                {
                    "date": day.isoformat(),
                    "clean_energy_kwh": clean_energy,
                    "actual_energy_kwh": actual_energy,
                    "energy_loss_kwh": clean_energy - actual_energy,
                    "soiling_ratio": actual_energy / clean_energy if clean_energy > 0 else 1.0,
                    "dust_soiling_ratio": contamination_state.dust_soiling_ratio,
                    "precipitation_mm": environment.precipitation_mm,
                    "mean_relative_humidity_pct": environment.mean_relative_humidity_pct,
                    "cohort_count": cohort_count,
                }
            )
        daily = pd.DataFrame.from_records(records).set_index("date")
        annual_clean = float(daily["clean_energy_kwh"].sum())
        annual_actual = float(daily["actual_energy_kwh"].sum())
        annual_loss = annual_clean - annual_actual
        loss_percent = (annual_loss / annual_clean * 100.0) if annual_clean > 0 else 0.0
        cohort_daily = pd.DataFrame.from_records(cohort_records) if cohort_records else None
        return BaselineSimulationResult(
            daily=daily,
            events=events,
            annual_clean_energy_kwh=annual_clean,
            annual_actual_energy_kwh=annual_actual,
            annual_soiling_loss_kwh=annual_loss,
            annual_soiling_loss_percent=loss_percent,
            cohort_daily=cohort_daily,
        )


def _daily_environment(weather: WeatherDataset) -> dict[date, DailyEnvironment]:
    index = pd.DatetimeIndex(weather.hourly.index)
    grouped = weather.hourly.groupby(index.date)
    result: dict[date, DailyEnvironment] = {}
    for raw_day, frame in grouped:
        day = raw_day if isinstance(raw_day, date) else pd.Timestamp(str(raw_day)).date()
        result[day] = DailyEnvironment(
            date=day,
            precipitation_mm=float(frame["precipitation_mm"].sum()),
            mean_relative_humidity_pct=float(frame["relative_humidity_pct"].mean()),
        )
    return result


def _apply_dust_to_farm(
    state: FarmState,
    base_ratio: float,
    variation_fraction: float,
    rng: np.random.Generator,
    cohort_variation_multipliers: dict[int, float] | None = None,
) -> FarmState:
    cohorts = []
    for cohort in state.cohorts:
        ratio = base_ratio
        if cohort_variation_multipliers is not None:
            ratio *= cohort_variation_multipliers.get(cohort.cohort_id, 1.0)
        elif variation_fraction > 0:
            ratio *= float(rng.normal(1.0, variation_fraction))
        cohorts.append(replace(cohort, dust_soiling_ratio=max(0.0, min(1.0, ratio))))
    return FarmState(date=state.date, cohorts=cohorts)
