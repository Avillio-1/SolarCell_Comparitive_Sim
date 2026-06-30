from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from solarclean.application.use_cases import RunCoatingSimulation
from solarclean.config.loader import load_config


def test_run_coating_writes_scenario_outputs() -> None:
    config = load_config(
        Path("configs/offline_fixture.yaml"),
        overrides={"output": {"base_directory": Path("outputs/test-t3-coating")}},
    )

    result = RunCoatingSimulation(config).run()

    daily = pd.read_csv(result.output_directory / "scenario_daily_results.csv")
    assert result.summary["command"] == "run-coating"
    assert result.summary["scenario_name"] == "coating"
    assert result.summary["event_tape_checksum"]
    assert (
        result.summary["annual_coating_actual_energy_kwh"]
        <= result.summary["annual_clean_energy_kwh"]
    )
    assert (
        result.summary["annual_baseline_actual_energy_kwh"]
        <= result.summary["annual_clean_energy_kwh"]
    )
    assert "coating_minus_baseline_energy_kwh" in result.summary
    assert (
        result.summary["annual_condensed_water_liters"]
        >= result.summary["annual_potentially_collectable_water_liters"]
    )
    assert (
        result.summary["annual_potentially_collectable_water_liters"]
        >= result.summary["annual_actually_collected_water_liters"]
    )
    assert "extension_optical_effect_kwh" in daily.columns
    assert "extension_temperature_effect_kwh" in daily.columns
    assert "extension_cleanliness_effect_kwh" in daily.columns
    assert (result.output_directory / "scenario_summary.json").exists()
    assert (result.output_directory / "coating_comparison_summary.json").exists()


def test_coating_presets_load() -> None:
    for path, preset in [
        ("configs/coating_weak.yaml", "weak"),
        ("configs/coating_central.yaml", "central"),
        ("configs/coating_strong.yaml", "strong"),
        ("configs/coating_paper_calibration.yaml", "paper_calibration"),
    ]:
        config = load_config(Path(path))
        assert config.coating.preset == preset
        assert config.coating.costs.material_cost_per_m2 > 0.0


def test_paper_calibration_reproduces_water_target() -> None:
    config = load_config(
        Path("configs/coating_paper_calibration.yaml"),
        overrides={"output": {"base_directory": Path("outputs/test-t3-coating-calibration")}},
    )

    result = RunCoatingSimulation(config).run()

    condensed_per_m2 = (
        result.summary["annual_condensed_water_liters"]
        / config.farm.total_panels
        / config.coating.deployment.area_per_panel_m2
    )
    assert condensed_per_m2 == pytest.approx(0.128, abs=0.035)
    assert result.summary["paper_source_status"] == "prompt_quoted_values_only"
