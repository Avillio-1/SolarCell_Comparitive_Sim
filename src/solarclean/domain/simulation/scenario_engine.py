from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from solarclean.domain.contamination.soiling import DailyEnvironment
from solarclean.domain.scenario.contracts import (
    AnnualScenarioResult,
    DailyScenarioInput,
    MitigationStrategy,
    ScenarioContext,
)


class ScenarioSimulationEngine:
    """Runs one shared annual daily loop for any mitigation strategy."""

    def __init__(self, strategy: MitigationStrategy) -> None:
        self.strategy = strategy

    def run(self, context: ScenarioContext, random_seed: int) -> AnnualScenarioResult:
        rng = np.random.default_rng(random_seed)
        state = self.strategy.initial_state(context, rng)
        weather_daily = _daily_environment(context.weather.hourly)
        panel_count = context.farm_config.total_panels if context.farm_config is not None else 1
        results = []
        for day_index, (raw_day, row) in enumerate(context.clean_energy.daily.iterrows()):
            day = pd.Timestamp(str(raw_day)).date()
            clean_energy = float(row["clean_ac_energy_kwh"])
            day_input = DailyScenarioInput(
                date=day,
                clean_energy_kwh=clean_energy,
                clean_energy_per_panel_kwh=clean_energy / panel_count,
                environment=weather_daily[day],
                event_inputs=context.event_tape.to_daily_inputs(day)
                if context.event_tape is not None
                else None,
                day_index=day_index,
            )
            step = self.strategy.simulate_day(day_input, state, context, rng)
            state = step.state
            results.append(step.result)
        return AnnualScenarioResult(
            scenario_name=self.strategy.name,
            daily_results=tuple(results),
        )


def _daily_environment(hourly_weather: pd.DataFrame) -> dict[date, DailyEnvironment]:
    index = pd.DatetimeIndex(hourly_weather.index)
    grouped = hourly_weather.groupby(index.date)
    result: dict[date, DailyEnvironment] = {}
    for raw_day, frame in grouped:
        day = raw_day if isinstance(raw_day, date) else pd.Timestamp(str(raw_day)).date()
        result[day] = DailyEnvironment(
            date=day,
            precipitation_mm=float(frame["precipitation_mm"].sum()),
            mean_relative_humidity_pct=float(frame["relative_humidity_pct"].mean()),
            max_relative_humidity_pct=float(frame["relative_humidity_pct"].max()),
        )
    return result
