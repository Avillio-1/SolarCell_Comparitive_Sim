from __future__ import annotations

from datetime import date

import pytest
from tests.unit.test_weather import _request

from solarclean.config.models import (
    BirdDroppingConfig,
    FarmConfig,
    RainfallCleaningConfig,
    SoilingConfig,
)
from solarclean.domain.contamination.soiling import KimberStyleSoilingModel
from solarclean.domain.events.tape import ExogenousEventTape, generate_event_tape
from solarclean.domain.random.streams import RngStream, RngStreamFactory
from solarclean.domain.simulation.baseline import BaselineSimulationEngine
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider


def test_event_tape_is_immutable_and_json_round_trips() -> None:
    tape = generate_event_tape(
        dates=[date(2025, 1, 1), date(2025, 1, 2)],
        seed=123,
        soiling=SoilingConfig(dust_event_probability=1.0),
        rainfall=RainfallCleaningConfig(),
        farm=FarmConfig(
            total_panels=10000, panel_capacity_w=400, cohort_count=2, panels_per_cohort=5000
        ),
        birds=BirdDroppingConfig(event_probability_per_cohort_day=0.5),
    )

    with pytest.raises(AttributeError):
        tape.events = ()

    restored = ExogenousEventTape.from_json(tape.to_json())

    assert restored == tape
    assert restored.checksum() == tape.checksum()
    assert restored.to_daily_inputs(date(2025, 1, 1)).date == date(2025, 1, 1)


def test_rng_streams_are_independent_and_reproducible() -> None:
    first = RngStreamFactory(seed=55)
    second = RngStreamFactory(seed=55)

    dust_before = first.generator(RngStream.DUST).random(3).tolist()
    _ = first.generator(RngStream.FUTURE_SCENARIO).random(500).tolist()
    dust_after = first.generator(RngStream.DUST_EVENT).random(3).tolist()

    assert dust_before == second.generator(RngStream.DUST).random(3).tolist()
    assert dust_after == second.generator(RngStream.DUST_EVENT).random(3).tolist()


def test_baseline_event_tape_is_unaffected_by_future_scenario_rng_use() -> None:
    weather = FixtureWeatherProvider().load(_request())
    clean = PVWattsPowerModel().calculate_hourly(weather, system=None)
    dates = [date.fromisoformat(str(day)) for day in clean.daily.index.astype(str)]
    soiling = SoilingConfig(
        base_daily_soiling_loss_fraction=0.005,
        dust_event_probability=0.8,
        dust_event_loss_min_fraction=0.01,
        dust_event_loss_max_fraction=0.03,
        random_seed=77,
    )
    farm = FarmConfig(
        total_panels=10000,
        panel_capacity_w=400,
        cohort_count=2,
        panels_per_cohort=5000,
        cohort_soiling_variation_fraction=0.05,
    )
    birds = BirdDroppingConfig(event_probability_per_cohort_day=0.4)
    base_tape = generate_event_tape(
        dates=dates,
        seed=77,
        soiling=soiling,
        rainfall=RainfallCleaningConfig(),
        farm=farm,
        birds=birds,
    )
    factory = RngStreamFactory(seed=77)
    _ = factory.generator(RngStream.FUTURE_SCENARIO).normal(size=1000)
    after_future_use = generate_event_tape(
        dates=dates,
        seed=77,
        soiling=soiling,
        rainfall=RainfallCleaningConfig(),
        farm=farm,
        birds=birds,
    )

    engine = BaselineSimulationEngine(
        KimberStyleSoilingModel(soiling, RainfallCleaningConfig()),
        farm=None,
    )
    first = engine.run(clean, weather, random_seed=77, event_tape=base_tape)
    second = engine.run(clean, weather, random_seed=999, event_tape=after_future_use)

    assert base_tape.checksum() == after_future_use.checksum()
    assert first.annual_actual_energy_kwh == pytest.approx(second.annual_actual_energy_kwh)
    assert [event.to_record() for event in first.events] == [
        event.to_record() for event in second.events
    ]
