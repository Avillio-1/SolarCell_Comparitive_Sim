from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from solarclean.application.use_cases import RunCoatingSimulation, _coating_summary
from solarclean.config.loader import load_config
from solarclean.domain.scenario.contracts import AnnualScenarioResult, DailyScenarioResult
from solarclean.domain.simulation.baseline import BaselineSimulationResult


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
    assert result.summary["period_day_count"] == 2
    assert result.summary["period_is_full_year"] is False
    assert result.summary["period_clean_energy_kwh"] == pytest.approx(
        result.summary["annual_clean_energy_kwh"]
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
    assert daily["allow_above_clean_reference"].all()
    reconciled = (
        daily["clean_energy_kwh"]
        + daily["extension_optical_effect_kwh"]
        + daily["extension_cleanliness_effect_kwh"]
        + daily["extension_temperature_effect_kwh"]
    )
    assert (reconciled - daily["actual_energy_kwh"]).abs().max() <= 1e-9
    assert (result.output_directory / "scenario_summary.json").exists()
    assert (result.output_directory / "coating_comparison_summary.json").exists()


def test_coating_presets_load() -> None:
    for path, preset in [
        ("configs/coating_weak.yaml", "weak"),
        ("configs/coating_central.yaml", "central"),
        ("configs/coating_strong.yaml", "strong"),
        ("configs/coating_paper_calibration.yaml", "paper_calibration"),
        ("configs/coating_endpoint_calibration.yaml", "paper_endpoint_calibration"),
    ]:
        config = load_config(Path(path))
        assert config.coating.preset == preset
        assert config.coating.costs.material_cost_per_m2 > 0.0
    paper = load_config(Path("configs/coating_paper_calibration.yaml"))
    assert paper.coating.physics.optical_transmittance_multiplier == pytest.approx(1.0)
    assert paper.coating.physics.source_optical_transmittance_absolute_fraction == pytest.approx(
        0.913
    )
    assert paper.coating.physics.daytime_cooling_fraction == pytest.approx(0.0)
    assert paper.coating.physics.passive_cleaning_base_efficiency == pytest.approx(0.0)
    assert paper.coating.water.actual_collection_efficiency_fraction == pytest.approx(0.0)
    assert paper.coating.deployment.reapplication_supported is False
    assert paper.coating.deployment.reapplication_interval_years is None


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
    assert result.summary["period_day_count"] == 1
    assert result.summary["period_is_full_year"] is False
    assert result.summary["calibration_fixture"] is True
    assert result.summary["annual_optical_effect_kwh"] == pytest.approx(0.0)
    assert result.summary["source_optical_transmittance_absolute_fraction"] == pytest.approx(0.913)
    assert result.summary["coated_area_m2"] == pytest.approx(20000.0)
    one_night_scale_liters = (
        config.farm.total_panels * config.coating.deployment.area_per_panel_m2 * 0.128
    )
    assert one_night_scale_liters == pytest.approx(2560.0)
    assert result.summary["period_condensed_water_liters"] == pytest.approx(
        one_night_scale_liters, abs=700.0
    )
    assert result.summary["period_condensed_water_liters_per_m2"] == pytest.approx(
        result.summary["period_condensed_water_liters"] / result.summary["coated_area_m2"]
    )
    assert result.summary["period_potentially_collectable_water_liters"] == pytest.approx(
        result.summary["period_condensed_water_liters"]
        * config.coating.water.collectable_water_efficiency_fraction
    )
    assert result.summary["period_actually_collected_water_liters"] == pytest.approx(
        result.summary["period_potentially_collectable_water_liters"]
        * config.coating.water.actual_collection_efficiency_fraction
    )
    assert result.summary["period_actually_collected_water_liters"] == pytest.approx(0.0)
    assert result.summary["paper_source_status"] == "prompt_quoted_values_only"


def test_endpoint_calibration_reproduces_six_month_power_loss_targets() -> None:
    config = load_config(
        Path("configs/coating_endpoint_calibration.yaml"),
        overrides={"output": {"base_directory": Path("outputs/test-t3-coating-endpoint")}},
    )

    result = RunCoatingSimulation(config).run()
    daily = pd.read_csv(result.output_directory / "scenario_daily_results.csv")
    last = daily.iloc[-1]

    assert result.summary["period_day_count"] == 180
    assert config.soiling.base_daily_soiling_loss_fraction == pytest.approx(0.28 / 180)
    assert config.coating.physics.dust_accumulation_multiplier == pytest.approx(0.015 / 0.28)
    assert last["extension_average_dust_soiling_ratio"] == pytest.approx(0.985)
    assert last["extension_cleanliness_ratio"] == pytest.approx(0.985)
    baseline_endpoint_ratio = 1.0 - config.soiling.base_daily_soiling_loss_fraction * 180
    assert baseline_endpoint_ratio == pytest.approx(0.72)


def test_endpoint_calibration_rejects_clipping_soiling_floor() -> None:
    with pytest.raises(ValueError, match="soiling floor clips"):
        load_config(
            Path("configs/coating_endpoint_calibration.yaml"),
            overrides={"soiling": {"minimum_soiling_ratio": 0.80}},
        )


def test_cleanliness_improvement_vs_baseline_is_positive_in_dusty_case() -> None:
    config = load_config(
        Path("configs/offline_fixture.yaml"),
        overrides={
            "output": {"base_directory": Path("outputs/test-t3-coating-dusty")},
            "soiling": {
                "base_daily_soiling_loss_fraction": 0.05,
                "dust_event_probability": 0.0,
                "dust_event_loss_min_fraction": 0.0,
                "dust_event_loss_max_fraction": 0.0,
                "stochastic_std_fraction": 0.0,
            },
            "bird_droppings": {
                "event_probability_per_cohort_day": 0.0,
                "coverage_min_fraction": 0.0,
                "coverage_max_fraction": 0.0,
            },
            "coating": {
                "physics": {
                    "optical_transmittance_multiplier": 1.0,
                    "max_surface_cooling_c": 0.0,
                }
            },
        },
    )

    result = RunCoatingSimulation(config).run()

    assert result.summary["period_cleanliness_improvement_vs_baseline_kwh"] > 0.0
    assert result.summary["period_optical_effect_kwh"] == pytest.approx(0.0)
    assert result.summary["period_temperature_effect_kwh"] == pytest.approx(0.0)


def test_full_year_summary_reports_annual_period_metadata() -> None:
    config = load_config(Path("configs/riyadh_2025.yaml"))
    start = date(2025, 1, 1)
    dates = [start + timedelta(days=offset) for offset in range(365)]
    daily_results = tuple(
        DailyScenarioResult(
            date=day,
            scenario_name="coating",
            clean_energy_kwh=1.0,
            actual_energy_kwh=1.0,
            allow_above_clean_reference=True,
            extensions={
                "optical_effect_kwh": 0.0,
                "temperature_effect_kwh": 0.0,
                "cleanliness_effect_kwh": 0.0,
                "cleanliness_ratio": 1.0,
                "condensed_water_liters": 0.0,
                "potentially_collectable_water_liters": 0.0,
                "actually_collected_water_liters": 0.0,
                "coated_area_m2": 20000.0,
            },
        )
        for day in dates
    )
    coating = AnnualScenarioResult(scenario_name="coating", daily_results=daily_results)
    baseline_daily = pd.DataFrame(
        {
            "clean_energy_kwh": [1.0] * 365,
            "actual_energy_kwh": [1.0] * 365,
        },
        index=[day.isoformat() for day in dates],
    )
    baseline = BaselineSimulationResult(
        daily=baseline_daily,
        events=[],
        annual_clean_energy_kwh=365.0,
        annual_actual_energy_kwh=365.0,
        annual_soiling_loss_kwh=0.0,
        annual_soiling_loss_percent=0.0,
    )

    summary = _coating_summary(
        coating,
        baseline,
        config=config,
        event_tape_checksum="synthetic",
    )

    assert summary["period_day_count"] == 365
    assert summary["period_start_date"] == "2025-01-01"
    assert summary["period_end_date"] == "2025-12-31"
    assert summary["period_is_full_year"] is True


def test_coating_full_year_boundary_excludes_next_year_contamination_update() -> None:
    config = load_config(
        Path("configs/coating_central.yaml"),
        overrides={
            "simulation": {
                "start": "2025-01-01T00:00:00+03:00",
                "end": "2025-12-31T23:00:00+03:00",
                "run_id_prefix": "test-t3-coating-full-year",
            },
            "output": {"base_directory": Path("outputs/test-t3-coating-full-year")},
        },
    )

    result = RunCoatingSimulation(config).run()
    daily = pd.read_csv(result.output_directory / "scenario_daily_results.csv")
    events = pd.read_csv(result.output_directory / "scenario_events.csv")

    assert result.summary["period_day_count"] == 365
    assert result.summary["period_start_date"] == "2025-01-01"
    assert result.summary["period_end_date"] == "2025-12-31"
    assert result.summary["period_is_full_year"] is True
    assert set(daily["date"]) == {
        (date(2025, 1, 1) + timedelta(days=offset)).isoformat() for offset in range(365)
    }
    assert "2026-01-01" not in set(daily["date"])
    assert (
        events.loc[events["event_type"] == "dust_accumulation", "date"].drop_duplicates().count()
        == 365
    )
