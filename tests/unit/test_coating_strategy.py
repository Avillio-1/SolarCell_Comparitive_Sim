from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from tests.unit.test_weather import _request

from solarclean.application.use_cases import _weather_request
from solarclean.config.loader import load_config
from solarclean.config.models import CoatingConfig, CoatingPhysicsConfig, SolarCleanConfig
from solarclean.domain.coating.state import CoatingCohortState
from solarclean.domain.coating.strategy import (
    CoatingStrategy,
    _effective_multiplier,
    _effectiveness_after_degradation,
)
from solarclean.domain.events.tape import generate_event_tape
from solarclean.domain.scenario.contracts import ScenarioContext
from solarclean.domain.simulation.scenario_engine import ScenarioSimulationEngine
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.csv_provider import CsvWeatherProvider
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider


def _context(config: SolarCleanConfig | None = None) -> ScenarioContext:
    config = config or load_config(Path("configs/offline_fixture.yaml"))
    if config.weather.provider == "csv":
        assert config.weather.local_csv_path is not None
        weather = CsvWeatherProvider(
            csv_path=config.weather.local_csv_path,
            timestamp_column=config.weather.timestamp_column,
            column_mapping=config.weather.column_mapping,
            unit_mapping=config.weather.unit_mapping,
        ).load(_weather_request(config))
    else:
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


def _strategy(config: SolarCleanConfig | None = None) -> CoatingStrategy:
    config = config or load_config(Path("configs/offline_fixture.yaml"))
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
    assert first.operational.capex_cost == 0.0
    assert first.extensions["coating_cost_basis"]["total_coated_area_m2"] == pytest.approx(20000.0)
    assert first.extensions["coating_cost_basis"]["material_cost_total"] > 0.0
    assert "condensation_dew_eligible" in first.extensions
    assert "passive_cleaning_day" in first.extensions
    assert "retained_dust_fraction" in first.extensions
    assert "bird_loss_fraction" in first.extensions


def test_coating_passive_cleaning_events_include_dew_and_dust_metadata() -> None:
    config = load_config(
        Path("configs/coating_paper_calibration.yaml"),
        overrides={
            "bird_droppings": {
                "event_probability_per_cohort_day": 0.0,
                "coverage_min_fraction": 0.0,
                "coverage_max_fraction": 0.0,
            },
            "coating": {
                "physics": {
                    "passive_cleaning_base_efficiency": 0.55,
                }
            },
        },
    )

    result = ScenarioSimulationEngine(_strategy(config)).run(_context(config), random_seed=42)
    event = next(
        event for event in result.events if event.event_type == "coating_passive_dust_cleaning"
    )
    metadata = dict(event.metadata)

    assert metadata["condensation_dew_eligible"] is True
    assert metadata["ambient_temperature_c"] == pytest.approx(20.0)
    assert metadata["coated_surface_temperature_c"] < metadata["dew_point_c"]
    assert metadata["relative_humidity_pct"] == pytest.approx(82.0)
    assert metadata["condensed_liters_per_m2"] > 0.0
    assert metadata["coating_age_days"] == 0
    assert 0.0 < metadata["coating_effectiveness_fraction"] <= 1.0
    assert metadata["coating_degradation_multiplier"] == pytest.approx(
        metadata["coating_effectiveness_fraction"]
    )
    assert 0.0 <= metadata["dust_removed"] <= metadata["dust_before"]
    assert metadata["dust_after"] == pytest.approx(
        metadata["dust_before"] - metadata["dust_removed"]
    )
    assert 0.0 <= metadata["dust_removal_efficiency_used"] <= 1.0
    assert json.loads(event.to_record()["metadata"])["dust_removed"] == pytest.approx(
        metadata["dust_removed"]
    )
    assert event.effective_for_energy_date == event.date + timedelta(days=1)
    assert result.daily_results[0].extensions["cleanliness_ratio"] == pytest.approx(
        metadata["dust_soiling_ratio_before"]
    )


def test_coating_process_energy_is_recorded_once_at_deployment() -> None:
    config = load_config(Path("configs/offline_fixture.yaml"))
    result = ScenarioSimulationEngine(_strategy(config)).run(_context(config), random_seed=42)
    expected = result.daily_results[0].extensions["coating_cost_basis"]["process_energy_kwh"]

    assert result.daily_results[0].operational.energy_used_kwh == pytest.approx(expected)
    assert all(day.operational.energy_used_kwh == 0.0 for day in result.daily_results[1:])


def test_degradation_scales_dust_optical_and_cooling_mechanisms_to_neutral() -> None:
    coating = CoatingConfig(
        physics=CoatingPhysicsConfig(
            initial_effectiveness_fraction=1.0,
            annual_degradation_fraction=1.0,
        )
    )
    cohort = CoatingCohortState(
        cohort_id=0,
        panel_count=1,
        applied=True,
        age_days=365,
        effectiveness_fraction=1.0,
        degradation_fraction=0.0,
        dust_soiling_ratio=1.0,
        bird_drop_coverage_fraction=0.0,
        bird_drop_loss_fraction=0.0,
    )

    effectiveness = _effectiveness_after_degradation(cohort, coating)

    assert effectiveness == 0.0
    assert _effective_multiplier(effectiveness, 0.2) == pytest.approx(1.0)
    assert _effective_multiplier(effectiveness, 1.1) == pytest.approx(1.0)


def test_coating_bird_removal_events_include_bounded_metadata() -> None:
    config = load_config(
        Path("configs/coating_paper_calibration.yaml"),
        overrides={
            "bird_droppings": {
                "event_probability_per_cohort_day": 1.0,
                "coverage_min_fraction": 0.01,
                "coverage_max_fraction": 0.01,
            },
            "coating": {
                "physics": {
                    "passive_cleaning_base_efficiency": 0.0,
                    "bird_removal_efficiency": 1.0,
                    "max_bird_removal_fraction_per_day": 0.005,
                }
            },
        },
    )

    result = ScenarioSimulationEngine(_strategy(config)).run(_context(config), random_seed=42)
    dust_events = [
        event for event in result.events if event.event_type == "coating_passive_dust_cleaning"
    ]
    bird_event = next(
        event for event in result.events if event.event_type == "coating_bird_dropping_removal"
    )
    metadata = dict(bird_event.metadata)

    assert dust_events == []
    assert metadata["condensed_liters_per_m2"] > 0.0
    assert metadata["bird_contamination_before"] == pytest.approx(0.01)
    assert 0.0 < metadata["bird_removed"] <= 0.005
    assert metadata["bird_contamination_after"] == pytest.approx(
        metadata["bird_contamination_before"] - metadata["bird_removed"]
    )
    assert 0.0 <= metadata["bird_removal_efficiency_used"] <= 1.0
    assert json.loads(bird_event.to_record()["metadata"])["bird_removed"] == pytest.approx(
        metadata["bird_removed"]
    )
