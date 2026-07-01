from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from tests.unit.test_weather import _request

from solarclean.config.loader import load_config
from solarclean.domain.coating.strategy import CoatingStrategy
from solarclean.domain.events.tape import generate_event_tape
from solarclean.domain.scenario.contracts import ScenarioContext
from solarclean.domain.simulation.scenario_engine import ScenarioSimulationEngine
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider


def _context() -> ScenarioContext:
    config = load_config(Path("configs/offline_fixture.yaml"))
    weather = FixtureWeatherProvider().load(_request())
    clean = PVWattsPowerModel().calculate_hourly(weather, config.pv_system)
    dates = [date.fromisoformat(str(day)) for day in clean.daily.index.astype(str)]
    tape = generate_event_tape(
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
        event_tape=tape,
        farm_config=config.farm,
        metadata={"event_tape_checksum": tape.checksum()},
    )


def _strategy() -> CoatingStrategy:
    config = load_config(Path("configs/offline_fixture.yaml"))
    return CoatingStrategy(
        coating=config.coating,
        soiling=config.soiling,
        rainfall=config.rainfall_cleaning,
        birds=config.bird_droppings,
        farm=config.farm,
        pv_system=config.pv_system,
    )


def test_coating_strategy_runs_through_shared_engine_and_preserves_tape_checksum() -> None:
    context = _context()
    assert context.event_tape is not None

    result = ScenarioSimulationEngine(_strategy()).run(context, random_seed=42)

    frame = result.to_daily_frame()
    assert result.scenario_name == "coating"
    assert len(result.daily_results) == len(context.clean_energy.daily)
    assert frame["allow_above_clean_reference"].all()
    assert "extension_event_tape_checksum" in frame.columns
    assert frame["extension_event_tape_checksum"].iloc[0] == context.event_tape.checksum()
    assert "optical_effect_kwh" in result.extension_keys()
    assert "temperature_effect_kwh" in result.extension_keys()
    assert "cleanliness_effect_kwh" in result.extension_keys()
    reconciled = (
        frame["clean_energy_kwh"]
        + frame["extension_optical_effect_kwh"]
        + frame["extension_cleanliness_effect_kwh"]
        + frame["extension_temperature_effect_kwh"]
    )
    assert (reconciled - frame["actual_energy_kwh"]).abs().max() <= 1e-9


def test_coating_strategy_is_reproducible() -> None:
    context = _context()
    strategy = _strategy()

    first = ScenarioSimulationEngine(strategy).run(context, random_seed=42)
    second = ScenarioSimulationEngine(strategy).run(context, random_seed=42)

    pd.testing.assert_frame_equal(first.to_daily_frame(), second.to_daily_frame())
    assert [event.to_record() for event in first.events] == [
        event.to_record() for event in second.events
    ]


def test_coating_outputs_water_and_cost_quantities_separately() -> None:
    result = ScenarioSimulationEngine(_strategy()).run(_context(), random_seed=42)

    first = result.daily_results[0]
    assert (
        first.extensions["condensed_water_liters"]
        >= first.extensions["potentially_collectable_water_liters"]
    )
    assert (
        first.extensions["potentially_collectable_water_liters"]
        >= first.extensions["actually_collected_water_liters"]
    )
    assert first.operational.coated_panel_count == 10000
    assert first.extensions["coating_cost_basis"]["total_coated_area_m2"] == pytest.approx(20000.0)
    assert first.extensions["coating_cost_basis"]["material_cost_total"] > 0.0
