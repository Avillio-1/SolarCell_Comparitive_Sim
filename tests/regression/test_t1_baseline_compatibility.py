from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.unit.test_weather import _request

from solarclean.config.loader import load_config
from solarclean.domain.contamination.soiling import KimberStyleSoilingModel
from solarclean.domain.farm.representation import CohortFarm
from solarclean.domain.simulation.baseline import BaselineSimulationEngine
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider


def test_t1_shared_engine_preserves_offline_baseline_results() -> None:
    config = load_config(Path("configs/offline_fixture.yaml"))
    expected = json.loads(
        Path("data/fixtures/regression_expected_offline_summary.json").read_text(encoding="utf-8")
    )
    weather = FixtureWeatherProvider().load(_request())
    clean = PVWattsPowerModel().calculate_hourly(weather, config.pv_system)
    engine = BaselineSimulationEngine(
        KimberStyleSoilingModel(config.soiling, config.rainfall_cleaning),
        farm=CohortFarm(config.farm, config.bird_droppings),
        farm_config=config.farm,
    )

    result = engine.run(clean, weather, config.soiling.random_seed)

    assert result.annual_clean_energy_kwh == pytest.approx(expected["annual_clean_energy_kwh"])
    assert result.annual_actual_energy_kwh == pytest.approx(expected["annual_actual_energy_kwh"])
    assert result.annual_soiling_loss_kwh == pytest.approx(expected["annual_soiling_loss_kwh"])
    assert len(result.events) == expected["event_count"]
    assert result.cohort_daily is not None
    assert len(result.cohort_daily) == expected["cohort_daily_rows"]
