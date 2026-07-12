from __future__ import annotations

from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

from solarclean.domain.contamination.soiling import DailyEnvironment
from solarclean.domain.scenario.contracts import (
    AnnualScenarioResult,
    DailyScenarioInput,
    DailyScenarioResult,
    MitigationStrategy,
    ScenarioContext,
)


class ScenarioSimulationEngine:
    """Runs one shared annual daily loop for any mitigation strategy."""

    def __init__(self, strategy: MitigationStrategy) -> None:
        self.strategy = strategy

    def run(self, context: ScenarioContext, random_seed: int) -> AnnualScenarioResult:
        run_context = _isolate_run_context(context)
        rng = np.random.default_rng(random_seed)
        panel_count = (
            run_context.farm_config.total_panels if run_context.farm_config is not None else 1
        )
        state = self.strategy.initial_state(run_context, rng)
        weather_daily = _daily_environment(run_context.weather.hourly)
        results = []
        for day_index, (raw_day, row) in enumerate(run_context.clean_energy.daily.iterrows()):
            day = pd.Timestamp(str(raw_day)).date()
            clean_energy = float(row["clean_ac_energy_kwh"])
            day_input = DailyScenarioInput(
                date=day,
                clean_energy_kwh=clean_energy,
                clean_energy_per_panel_kwh=clean_energy / panel_count,
                environment=weather_daily[day],
                event_inputs=run_context.event_tape.to_daily_inputs(day)
                if run_context.event_tape is not None
                else None,
                day_index=day_index,
            )
            step = self.strategy.simulate_day(day_input, state, run_context, rng)
            _validate_strategy_result(
                strategy_name=self.strategy.name,
                day_input=day_input,
                result=step.result,
            )
            state = step.state
            results.append(step.result)
        return AnnualScenarioResult(
            scenario_name=self.strategy.name,
            daily_results=tuple(results),
        )


def _isolate_run_context(context: ScenarioContext) -> ScenarioContext:
    farm_config = (
        context.farm_config.model_copy(deep=True) if context.farm_config is not None else None
    )
    return replace(context, farm_config=farm_config)


def _validate_strategy_result(
    *,
    strategy_name: str,
    day_input: DailyScenarioInput,
    result: object,
) -> None:
    if not isinstance(result, DailyScenarioResult):
        raise TypeError("strategy result must be a DailyScenarioResult")
    if result.date != day_input.date:
        raise ValueError(
            "strategy result date must echo DailyScenarioInput.date "
            f"({result.date.isoformat()} != {day_input.date.isoformat()})"
        )
    if result.scenario_name != strategy_name:
        raise ValueError(
            "strategy result scenario_name must match the strategy name "
            f"({result.scenario_name!r} != {strategy_name!r})"
        )
    if result.clean_energy_kwh != day_input.clean_energy_kwh:
        raise ValueError(
            "strategy result clean_energy_kwh must echo the shared daily clean reference "
            f"({result.clean_energy_kwh!r} != {day_input.clean_energy_kwh!r})"
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
