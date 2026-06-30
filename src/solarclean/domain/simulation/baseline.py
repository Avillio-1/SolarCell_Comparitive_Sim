from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from solarclean.config.models import FarmConfig
from solarclean.domain.contamination.soiling import (
    KimberStyleSoilingModel,
    SimulationEvent,
)
from solarclean.domain.environment.weather import WeatherDataset
from solarclean.domain.events.tape import ExogenousEventTape
from solarclean.domain.farm.representation import CohortFarm
from solarclean.domain.pv.model import CleanEnergyProfile
from solarclean.domain.scenario.contracts import ScenarioContext
from solarclean.domain.simulation.baseline_strategy import BaselineStrategy
from solarclean.domain.simulation.scenario_engine import ScenarioSimulationEngine


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
        context = ScenarioContext.from_inputs(
            weather=weather,
            clean_energy=clean,
            event_tape=event_tape,
            farm_config=self.farm_config,
        )
        annual = ScenarioSimulationEngine(
            BaselineStrategy(
                self.soiling_model,
                farm=self.farm,
                farm_config=self.farm_config,
            )
        ).run(context, random_seed=random_seed)
        records: list[dict[str, object]] = []
        cohort_records: list[dict[str, object]] = []
        for result in annual.daily_results:
            records.append(
                {
                    "date": result.date.isoformat(),
                    "clean_energy_kwh": result.clean_energy_kwh,
                    "actual_energy_kwh": result.actual_energy_kwh,
                    "energy_loss_kwh": result.energy_loss_kwh,
                    "soiling_ratio": result.soiling_ratio,
                    "dust_soiling_ratio": result.extensions["dust_soiling_ratio"],
                    "precipitation_mm": result.extensions["precipitation_mm"],
                    "mean_relative_humidity_pct": result.extensions["mean_relative_humidity_pct"],
                    "cohort_count": result.extensions["cohort_count"],
                }
            )
            raw_cohort_records = result.extensions.get("cohort_records", ())
            if isinstance(raw_cohort_records, tuple):
                cohort_records.extend(dict(record) for record in raw_cohort_records)
        daily = pd.DataFrame.from_records(records).set_index("date")
        annual_clean = float(daily["clean_energy_kwh"].sum())
        annual_actual = float(daily["actual_energy_kwh"].sum())
        annual_loss = annual_clean - annual_actual
        loss_percent = (annual_loss / annual_clean * 100.0) if annual_clean > 0 else 0.0
        cohort_daily = pd.DataFrame.from_records(cohort_records) if cohort_records else None
        events = [event.to_simulation_event() for event in annual.events]
        return BaselineSimulationResult(
            daily=daily,
            events=events,
            annual_clean_energy_kwh=annual_clean,
            annual_actual_energy_kwh=annual_actual,
            annual_soiling_loss_kwh=annual_loss,
            annual_soiling_loss_percent=loss_percent,
            cohort_daily=cohort_daily,
        )
