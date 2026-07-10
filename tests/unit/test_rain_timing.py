from __future__ import annotations

from datetime import date

from tests.config_factory import fixture_config

from solarclean.application.use_cases import _weather_request
from solarclean.domain.contamination.soiling import KimberStyleSoilingModel
from solarclean.domain.events.tape import generate_event_tape
from solarclean.domain.farm.representation import CohortFarm
from solarclean.domain.scenario.contracts import ScenarioContext
from solarclean.domain.simulation.baseline_strategy import BaselineStrategy
from solarclean.domain.simulation.scenario_engine import ScenarioSimulationEngine
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider


def test_rain_cleaning_changes_next_day_energy_not_same_day() -> None:
    config = fixture_config(
        overrides={
            "simulation": {"end": "2025-01-03T23:00:00+03:00"},
            "soiling": {"dust_event_probability": 0.0},
            "bird_droppings": {"event_probability_per_cohort_day": 0.0},
        }
    )
    weather = FixtureWeatherProvider().load(_weather_request(config))
    clean = PVWattsPowerModel().calculate_hourly(weather, config.pv_system)
    dates = tuple(date.fromisoformat(str(day)) for day in clean.daily.index)
    tape = generate_event_tape(
        dates=dates,
        seed=config.soiling.random_seed,
        soiling=config.soiling,
        rainfall=config.rainfall_cleaning,
        farm=config.farm,
        birds=config.bird_droppings,
    )
    context = ScenarioContext.from_inputs(
        weather=weather,
        clean_energy=clean,
        event_tape=tape,
        farm_config=config.farm,
    )
    result = ScenarioSimulationEngine(
        BaselineStrategy(
            KimberStyleSoilingModel(config.soiling, config.rainfall_cleaning),
            farm=CohortFarm(config.farm, config.bird_droppings),
            farm_config=config.farm,
        )
    ).run(context, random_seed=config.soiling.random_seed)

    jan_2 = result.daily_results[1]
    jan_3 = result.daily_results[2]
    assert jan_2.extensions["dust_soiling_ratio"] < jan_3.extensions["dust_soiling_ratio"]
    rain = next(event for event in jan_2.events if event.event_type == "full_rain_cleaning")
    assert rain.effective_for_energy_date == jan_3.date
