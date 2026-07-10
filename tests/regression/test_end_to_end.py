from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from tests.config_factory import fixture_config

from solarclean.application.comparison import CompareAllScenarios
from solarclean.application.use_cases import (
    FetchWeather,
    RunBaselineSimulation,
    RunCleanPVSimulation,
)


def test_standalone_baseline_matches_comparison_event_tape_path(tmp_path: Path) -> None:
    config = fixture_config(overrides={"output": {"base_directory": tmp_path}})

    standalone = RunBaselineSimulation(config).run()
    comparison = CompareAllScenarios(config, write_artifacts=False).run().comparison

    assert (
        standalone.summary["annual_actual_energy_kwh"]
        == comparison.scenario_results["baseline"].annual_actual_energy_kwh
    )
    assert (standalone.output_directory / "event_tape.json").exists()


def test_standalone_baseline_matches_comparison_event_tape_path(tmp_path: Path) -> None:
    config = load_config(
        Path("configs/offline_fixture.yaml"),
        overrides={"output": {"base_directory": tmp_path}},
    )

    standalone = RunBaselineSimulation(config).run()
    comparison = CompareAllScenarios(config, write_artifacts=False).run().comparison

    assert (
        standalone.summary["annual_actual_energy_kwh"]
        == comparison.scenario_results["baseline"].annual_actual_energy_kwh
    )
    assert (standalone.output_directory / "event_tape.json").exists()


def test_offline_fixture_runs_phase_1_and_writes_outputs(tmp_path: Path) -> None:
    config = fixture_config(overrides={"output": {"base_directory": tmp_path}})

    result = RunCleanPVSimulation(config).run()

    assert result.output_directory.exists()
    assert (result.output_directory / "weather_hourly.csv").exists()
    assert (result.output_directory / "clean_energy_hourly.csv").exists()
    assert (result.output_directory / "daily_results.csv").exists()
    assert (result.output_directory / "summary.json").exists()
    summary = json.loads((result.output_directory / "summary.json").read_text(encoding="utf-8"))
    assert summary["annual_clean_energy_kwh"] > 0


def test_offline_fixture_runs_baseline_and_cohort_phase_3(tmp_path: Path) -> None:
    config = fixture_config(overrides={"output": {"base_directory": tmp_path}})
    expected = json.loads(
        Path("data/fixtures/regression_expected_offline_summary.json").read_text(encoding="utf-8")
    )

    result = RunBaselineSimulation(config).run()

    assert (result.output_directory / "events.csv").exists()
    assert (result.output_directory / "cohort_daily_results.csv").exists()
    assert (result.output_directory / "diagnostic_plot.png").exists()
    daily = pd.read_csv(result.output_directory / "daily_results.csv")
    assert np.isfinite(daily.select_dtypes(include=["number"]).to_numpy()).all()
    assert (daily["actual_energy_kwh"] <= daily["clean_energy_kwh"] + 1e-9).all()
    summary = json.loads((result.output_directory / "summary.json").read_text(encoding="utf-8"))
    assert summary["annual_actual_energy_kwh"] <= summary["annual_clean_energy_kwh"]
    assert summary["farm_representation"] == "cohort"
    assert summary["annual_clean_energy_kwh"] == expected["annual_clean_energy_kwh"]
    assert summary["annual_actual_energy_kwh"] == expected["annual_actual_energy_kwh"]
    assert summary["annual_soiling_loss_kwh"] == expected["annual_soiling_loss_kwh"]
    assert summary["event_count"] == expected["event_count"]


def test_fetch_weather_writes_normalized_fixture(tmp_path: Path) -> None:
    config = fixture_config(overrides={"output": {"base_directory": tmp_path}})

    result = FetchWeather(config).run()

    assert (result.output_directory / "weather_hourly.csv").exists()
    weather = pd.read_csv(result.output_directory / "weather_hourly.csv")
    assert {"ghi_w_m2", "temp_air_c", "precipitation_mm"}.issubset(weather.columns)
