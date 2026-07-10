from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from tests.config_factory import (
    config_from_default,
    endpoint_calibration_config,
    fixture_config,
    full_year_fixture_config,
    kaust_strong_config,
    paper_calibration_config,
)

from solarclean.application.use_cases import RunCoatingSimulation, _coating_summary
from solarclean.domain.scenario.contracts import AnnualScenarioResult, DailyScenarioResult
from solarclean.domain.simulation.baseline import BaselineSimulationResult


def test_run_coating_writes_scenario_outputs() -> None:
    config = fixture_config(
        overrides={"output": {"base_directory": Path("outputs/test-t3-coating")}}
    )

    result = RunCoatingSimulation(config).run()

    daily = pd.read_csv(result.output_directory / "scenario_daily_results.csv")
    events = pd.read_csv(result.output_directory / "scenario_events.csv")
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
    assert result.summary["annual_remaining_soiling_loss_kwh"] == pytest.approx(
        -result.summary["annual_cleanliness_effect_kwh"]
    )
    assert result.summary["period_remaining_soiling_loss_kwh"] == pytest.approx(
        result.summary["annual_remaining_soiling_loss_kwh"]
    )
    assert result.summary["period_remaining_soiling_loss_percent"] == pytest.approx(
        result.summary["annual_remaining_soiling_loss_percent"]
    )
    warning_codes = {warning["code"] for warning in result.summary["coating_warnings"]}
    assert {
        "optical_effect_zero_or_disabled",
        "temperature_effect_zero_or_disabled",
        "weather_limited_or_provisional",
        "not_guaranteed_kaust_paper_field_performance",
        "annualized_capex_not_included",
        "water_revenue_not_included",
    } <= warning_codes
    assert result.summary["coating_readiness_notes"] == result.summary["coating_warnings"]
    assert "condensed, potentially collectable, and actually collected water" in str(
        result.summary["water_accounting_basis"]
    )
    assert "extension_optical_effect_kwh" in daily.columns
    assert "extension_temperature_effect_kwh" in daily.columns
    assert "extension_cleanliness_effect_kwh" in daily.columns
    assert all(isinstance(json.loads(value), dict) for value in events["metadata"])
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
    scenario_summary = json.loads(
        (result.output_directory / "scenario_summary.json").read_text(encoding="utf-8")
    )
    comparison_summary = json.loads(
        (result.output_directory / "coating_comparison_summary.json").read_text(encoding="utf-8")
    )
    for persisted in (scenario_summary, comparison_summary):
        assert persisted["annual_cleanliness_effect_kwh"] == pytest.approx(
            result.summary["annual_cleanliness_effect_kwh"]
        )
        assert persisted["annual_remaining_soiling_loss_kwh"] == pytest.approx(
            result.summary["annual_remaining_soiling_loss_kwh"]
        )
        assert persisted["annual_remaining_soiling_loss_percent"] == pytest.approx(
            result.summary["annual_remaining_soiling_loss_percent"]
        )
        assert persisted["period_remaining_soiling_loss_kwh"] == pytest.approx(
            result.summary["period_remaining_soiling_loss_kwh"]
        )
        assert persisted["period_remaining_soiling_loss_percent"] == pytest.approx(
            result.summary["period_remaining_soiling_loss_percent"]
        )
        assert persisted["annual_cleanliness_improvement_vs_baseline_kwh"] == pytest.approx(
            result.summary["annual_cleanliness_improvement_vs_baseline_kwh"]
        )
        assert persisted["annual_actual_energy_kwh"] == pytest.approx(
            result.summary["annual_coating_actual_energy_kwh"]
        )
        assert persisted["coating_readiness"]["annualized_capex_included"] is False
        assert persisted["coating_readiness"]["water_revenue_included"] is False
        assert persisted["coating_readiness"]["warnings"] == persisted["coating_warnings"]


def test_default_and_test_calibration_presets_load() -> None:
    for config, preset in [
        (config_from_default(), "weak"),
        (paper_calibration_config(), "paper_calibration"),
        (endpoint_calibration_config(), "paper_endpoint_calibration"),
        (kaust_strong_config(), "kaust_paper_strong"),
    ]:
        assert config.coating.preset == preset
        assert config.coating.costs.material_cost_per_m2 > 0.0
    paper = paper_calibration_config()
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
    config = paper_calibration_config(
        overrides={"output": {"base_directory": Path("outputs/test-t3-coating-calibration")}}
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
    assert result.summary["annual_condensed_water_liters"] > 0.0
    assert result.summary["annual_potentially_collectable_water_liters"] > 0.0
    assert result.summary["annual_actually_collected_water_liters"] == pytest.approx(0.0)
    assert result.summary["water_revenue_included"] is False
    assert result.summary["paper_source_status"] == "prompt_quoted_values_only"


def test_endpoint_calibration_reproduces_six_month_power_loss_targets() -> None:
    config = endpoint_calibration_config(
        overrides={"output": {"base_directory": Path("outputs/test-t3-coating-endpoint")}}
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


def test_kaust_paper_strong_preset_improves_under_favorable_dew() -> None:
    config = kaust_strong_config(
        overrides={"output": {"base_directory": Path("outputs/test-t3-coating-kaust-strong")}}
    )

    result = RunCoatingSimulation(config).run()
    daily = pd.read_csv(result.output_directory / "scenario_daily_results.csv")

    assert result.summary["period_day_count"] == len(daily)
    assert result.summary["period_dew_eligible_day_count"] > 0
    assert result.summary["period_passive_cleaning_day_count"] > 0
    assert (
        result.summary["period_final_coating_loss_percent"]
        < result.summary["period_final_baseline_loss_percent"]
    )
    assert (
        result.summary["period_final_coating_normalized_performance"]
        > result.summary["period_final_baseline_normalized_performance"]
    )
    assert result.summary["period_final_average_dust_soiling_ratio"] <= 1.0
    assert result.summary["period_final_cleanliness_ratio"] <= 1.0
    assert (result.output_directory / "coating_normalized_performance.png").exists()
    assert (result.output_directory / "coating_daily_loss_percent.png").exists()
    assert (result.output_directory / "coating_contamination_diagnostics.png").exists()


def test_kaust_paper_strong_preset_does_not_create_dew_cleaning_in_dry_weather() -> None:
    config = kaust_strong_config(
        overrides={
            "weather": {"fixture_profile": "riyadh_dry"},
            "output": {"base_directory": Path("outputs/test-t3-coating-kaust-dry")},
        },
    )

    result = RunCoatingSimulation(config).run()
    daily = pd.read_csv(result.output_directory / "scenario_daily_results.csv")

    assert result.summary["period_dew_eligible_day_count"] == 0
    assert result.summary["period_condensed_water_liters"] == pytest.approx(0.0)
    assert not daily["extension_condensation_dew_eligible"].any()


def test_endpoint_calibration_rejects_clipping_soiling_floor() -> None:
    with pytest.raises(ValueError, match="soiling floor clips"):
        endpoint_calibration_config(overrides={"soiling": {"minimum_soiling_ratio": 0.80}})


def test_cleanliness_improvement_vs_baseline_is_positive_in_dusty_case() -> None:
    config = fixture_config(
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
    config = config_from_default()
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
    config = full_year_fixture_config(
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
