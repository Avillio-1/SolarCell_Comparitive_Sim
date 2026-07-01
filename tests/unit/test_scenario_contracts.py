from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pandas as pd
import pytest
from tests.unit.test_weather import _request

from solarclean.config.loader import load_config
from solarclean.domain.events.tape import generate_event_tape
from solarclean.domain.scenario.contracts import (
    DailyScenarioInput,
    DailyScenarioResult,
    DomainEvent,
    OperationalQuantities,
    ScenarioContext,
    StrategyStep,
)
from solarclean.domain.simulation.scenario_engine import ScenarioSimulationEngine
from solarclean.infrastructure.persistence.outputs import OutputWriter
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider


class MockFutureStrategy:
    name = "mock_future"

    def initial_state(self, context: ScenarioContext, rng: np.random.Generator) -> dict[str, int]:
        del context, rng
        return {"days_seen": 0}

    def simulate_day(
        self,
        day_input: DailyScenarioInput,
        state: object,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> StrategyStep:
        del context, rng
        typed_state = dict(state) if isinstance(state, dict) else {"days_seen": 0}
        actual = day_input.clean_energy_kwh - 1.0
        event = DomainEvent(
            date=day_input.date,
            event_type="mock_future_marker",
            magnitude=1.0,
            description="Mock strategy marker proving extension contract.",
            scenario_name=self.name,
            metadata={"source": "contract-test"},
        )
        result = DailyScenarioResult(
            date=day_input.date,
            scenario_name=self.name,
            clean_energy_kwh=day_input.clean_energy_kwh,
            actual_energy_kwh=actual,
            operational=OperationalQuantities(inspections_count=1, drone_flight_hours=0.25),
            events=(event,),
            extensions={"mock_metric": day_input.day_index, "note": "kept"},
        )
        return StrategyStep(state={"days_seen": typed_state["days_seen"] + 1}, result=result)


def _scenario_context() -> ScenarioContext:
    weather = FixtureWeatherProvider().load(_request())
    clean = PVWattsPowerModel().calculate_hourly(weather, system=None)
    config = load_config(Path("configs/offline_fixture.yaml"))
    dates = [date.fromisoformat(str(day)) for day in clean.daily.index.astype(str)]
    event_tape = generate_event_tape(
        dates=dates,
        seed=config.soiling.random_seed,
        soiling=config.soiling,
        rainfall=config.rainfall_cleaning,
        farm=config.farm,
        birds=config.bird_droppings,
    )
    return ScenarioContext.from_inputs(
        weather=weather,
        clean_energy=clean,
        event_tape=event_tape,
        farm_config=config.farm,
        metadata={"weather_checksum": weather.metadata["checksum"]},
    )


def test_mock_future_strategy_runs_through_shared_engine() -> None:
    context = _scenario_context()

    result = ScenarioSimulationEngine(MockFutureStrategy()).run(context, random_seed=123)

    assert result.scenario_name == "mock_future"
    assert len(result.daily_results) == len(context.clean_energy.daily)
    assert result.annual_actual_energy_kwh == pytest.approx(
        result.annual_clean_energy_kwh - len(result.daily_results)
    )
    assert result.summary()["scenario_name"] == "mock_future"
    assert result.summary()["annual_energy_loss_kwh"] == pytest.approx(
        float(len(result.daily_results))
    )
    assert result.events[0].metadata["source"] == "contract-test"


def test_shared_context_and_extensions_are_immutable_or_copy_protected() -> None:
    context = _scenario_context()

    with pytest.raises(FrozenInstanceError):
        context.event_tape = None  # type: ignore[misc]
    with pytest.raises(TypeError):
        context.metadata["new"] = "blocked"  # type: ignore[index]
    with pytest.raises(TypeError):
        context.event_tape.to_daily_inputs(date(2025, 1, 1)).cohort_variation_multipliers[0] = 1.0

    first_ghi = float(context.weather.hourly.iloc[0]["ghi_w_m2"])
    modified = context.weather.hourly
    modified.iloc[0, modified.columns.get_loc("ghi_w_m2")] = -999.0
    assert float(context.weather.hourly.iloc[0]["ghi_w_m2"]) == first_ghi

    daily = DailyScenarioResult(
        date=date(2025, 1, 1),
        scenario_name="mock",
        clean_energy_kwh=10.0,
        actual_energy_kwh=9.0,
        extensions={"scenario_specific": 5},
    )
    with pytest.raises(TypeError):
        daily.extensions["scenario_specific"] = 6  # type: ignore[index]
    event = DomainEvent(
        date=date(2025, 1, 1),
        event_type="x",
        magnitude=1.0,
        description="x",
        scenario_name="mock",
        metadata=MappingProxyType({"a": 1}),
    )
    with pytest.raises(TypeError):
        event.metadata["b"] = 2  # type: ignore[index]


def test_above_clean_reference_requires_explicit_opt_in() -> None:
    with pytest.raises(ValueError, match="above-reference"):
        DailyScenarioResult(
            date=date(2025, 1, 1),
            scenario_name="cleaning_only",
            clean_energy_kwh=10.0,
            actual_energy_kwh=10.1,
        )

    daily = DailyScenarioResult(
        date=date(2025, 1, 1),
        scenario_name="coating",
        clean_energy_kwh=10.0,
        actual_energy_kwh=10.1,
        allow_above_clean_reference=True,
    )

    assert daily.energy_loss_kwh == pytest.approx(-0.1)


def test_scenario_specific_fields_survive_common_result_handling() -> None:
    result = ScenarioSimulationEngine(MockFutureStrategy()).run(_scenario_context(), random_seed=1)

    frame = result.to_daily_frame()
    summary = result.summary()

    assert "extension_mock_metric" in frame.columns
    assert "extension_note" in frame.columns
    assert frame["actual_energy_kwh"].sum() == pytest.approx(result.annual_actual_energy_kwh)
    assert summary["annual_clean_energy_kwh"] == pytest.approx(result.annual_clean_energy_kwh)
    assert summary["extension_keys"] == ["mock_metric", "note"]


def test_output_writer_persists_generic_scenario_result(tmp_path: Path) -> None:
    config = load_config(
        Path("configs/offline_fixture.yaml"), overrides={"output": {"base_directory": tmp_path}}
    )
    output_dir = OutputWriter(config).create_run_directory("scenario-contract")
    result = ScenarioSimulationEngine(MockFutureStrategy()).run(_scenario_context(), random_seed=1)

    OutputWriter(config).write_scenario_result(output_dir, result)

    daily = pd.read_csv(output_dir / "scenario_daily_results.csv")
    summary = (output_dir / "scenario_summary.json").read_text(encoding="utf-8")
    assert "extension_mock_metric" in daily.columns
    assert "annual_actual_energy_kwh" in summary
    assert (output_dir / "scenario_events.csv").exists()
