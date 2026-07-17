from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from tests.config_factory import fixture_config

import solarclean.application.sensitivity as sensitivity_module
import solarclean.domain.calibration.parameter_overrides as parameter_overrides_module
from solarclean.application.comparison import CANONICAL_SCENARIO_IDS, CompareAllScenarios
from solarclean.application.sensitivity import (
    BreakEvenEvaluation,
    BreakEvenExperiment,
    OneWaySensitivityExperiment,
    TwoWaySensitivityExperiment,
    VariantResult,
)


def _fixture_config(output_dir: Path):
    return fixture_config(overrides={"output": {"base_directory": output_dir}})


def test_oneway_prepares_weather_and_pv_profile_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _fixture_config(tmp_path)
    original_prepare = sensitivity_module._prepare_shared_inputs
    calls = 0

    def counted_prepare(config_arg):
        nonlocal calls
        calls += 1
        return original_prepare(config_arg)

    monkeypatch.setattr(sensitivity_module, "_prepare_shared_inputs", counted_prepare)
    OneWaySensitivityExperiment(
        config,
        parameter_names=("coating.useful_life_years",),
        steps=3,
        write_artifacts=False,
    ).run()

    assert calls == 1


def test_lightweight_variant_keeps_core_outcome_and_skips_report_frames(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    weather, clean_energy = sensitivity_module._prepare_shared_inputs(config)
    detailed = (
        CompareAllScenarios(
            config,
            weather=weather,
            clean_energy=clean_energy,
            write_artifacts=False,
        )
        .run()
        .comparison
    )
    lightweight = (
        CompareAllScenarios(
            config,
            weather=weather,
            clean_energy=clean_energy,
            write_artifacts=False,
            include_reporting_summaries=False,
        )
        .run()
        .comparison
    )

    assert lightweight.scenario_results == detailed.scenario_results
    assert lightweight.economic_results == detailed.economic_results
    assert lightweight.energy_gain_vs_baseline == detailed.energy_gain_vs_baseline
    assert lightweight.reconciliation_report == detailed.reconciliation_report
    assert lightweight.recommendation.winner == detailed.recommendation.winner
    assert lightweight.recommendation.calculation_valid == (
        detailed.recommendation.calculation_valid
    )
    assert lightweight.daily_summaries == {}
    assert lightweight.annual_summaries == {}
    assert lightweight.event_summaries == {}
    assert lightweight.economic_summaries == {}


def test_economics_only_variant_reuses_physics_without_changing_outcome(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    weather, clean_energy = sensitivity_module._prepare_shared_inputs(config)
    registry = sensitivity_module.ParameterRegistry.from_yaml(
        config.calibration.parameter_registry_path
    )
    base = sensitivity_module._run_variant(
        config=config,
        registry=registry,
        scenario_order=None,
        weather=weather,
        clean_energy=clean_energy,
    )
    spec = next(
        item
        for item in sensitivity_module.build_parameter_catalog(registry)[0]
        if item.name == "economics.electricity_tariff_sar_per_kwh"
    )
    variant_config, variant_registry = sensitivity_module._apply_override(
        base_config=config,
        base_registry=registry,
        spec=spec,
        value=spec.high_value,
    )
    full = sensitivity_module._run_variant(
        config=variant_config,
        registry=variant_registry,
        scenario_order=None,
        weather=weather,
        clean_energy=clean_energy,
    )
    reused = sensitivity_module._run_variant(
        config=variant_config,
        registry=variant_registry,
        scenario_order=None,
        weather=weather,
        clean_energy=clean_energy,
        event_tape=base.event_tape,
        precomputed_scenario_results=base.scenario_results,
        precomputed_scenario_config_checksum=base.config_checksum,
    )

    assert reused == full


def test_oneway_reuses_reference_result_for_an_identical_central_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _fixture_config(tmp_path)
    original = sensitivity_module._run_variant
    calls = 0

    def counted_run_variant(**kwargs):
        nonlocal calls
        calls += 1
        return original(**kwargs)

    monkeypatch.setattr(sensitivity_module, "_run_variant", counted_run_variant)
    result = (
        OneWaySensitivityExperiment(
            config,
            parameter_names=("economics.electricity_tariff_sar_per_kwh",),
            steps=3,
            write_artifacts=False,
        )
        .run()
        .result
    )

    assert len(result.parameter_results[0].points) == 3
    assert calls == 3  # one base plus low/high; central reuses the exact base


# --- One-way ----------------------------------------------------------------


def test_oneway_sweeps_requested_parameters_only(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    names = ["soiling.base_daily_loss_fraction", "economics.electricity_tariff_sar_per_kwh"]
    outcome = OneWaySensitivityExperiment(
        config, parameter_names=names, steps=3, write_artifacts=False
    ).run()
    result = outcome.result
    assert {r.spec.name for r in result.parameter_results} == set(names)
    assert result.skipped_parameters == ()
    assert result.base_mode == "reference_config"


def test_central_preset_config_sweep_reconciles_registry_guarded_points(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = fixture_config(
        overrides={
            "simulation": {"end": "2025-12-31T23:00:00+03:00"},
            "weather": {"provider": "fixture"},
            "pv_system": {"panel_count": 100},
            "farm": {
                "total_panels": 100,
                "cohort_count": 1,
                "panels_per_cohort": 100,
            },
            "coating": {
                "preset": "central",
                "physics": {"dust_accumulation_multiplier": 0.7},
            },
            "calibration": {"assumption_set": "riyadh_central_v2"},
            "output": {"base_directory": tmp_path},
        }
    )
    original = sensitivity_module._run_variant
    calls = 0

    def counted_run_variant(**kwargs):
        nonlocal calls
        calls += 1
        return original(**kwargs)

    monkeypatch.setattr(sensitivity_module, "_run_variant", counted_run_variant)
    result = (
        OneWaySensitivityExperiment(
            config,
            parameter_names=("coating.dust_accumulation_multiplier",),
            steps=3,
            write_artifacts=False,
        )
        .run()
        .result
    )

    points = result.parameter_results[0].points
    assert {point.value for point in points} == {0.5, 0.7, 0.85}
    assert all(point.reconciled for point in points)
    assert calls == 3  # base plus low/high; equal config and registry reuse the central result


def test_sensitivity_revalidates_completed_config_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _fixture_config(tmp_path)
    supported, _ = sensitivity_module.build_parameter_catalog(
        sensitivity_module.ParameterRegistry.from_yaml(config.calibration.parameter_registry_path)
    )
    spec = next(item for item in supported if item.kind == "config")

    def invalid_override(base_config, _value):
        invalid_farm = base_config.farm.model_copy(update={"total_panels": 9999})
        return base_config.model_copy(update={"farm": invalid_farm})

    monkeypatch.setitem(
        parameter_overrides_module._CONFIG_OVERRIDES,
        spec.name,
        invalid_override,
    )
    with pytest.raises(ValueError):
        sensitivity_module._apply_override(
            base_config=config,
            base_registry=sensitivity_module.ParameterRegistry.from_yaml(
                config.calibration.parameter_registry_path
            ),
            spec=spec,
            value=spec.central_value,
        )


def test_oneway_rejects_unknown_parameter_names(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    with pytest.raises(ValueError, match="not.a.real.parameter"):
        OneWaySensitivityExperiment(
            config,
            parameter_names=["soiling.base_daily_loss_fraction", "not.a.real.parameter"],
            steps=3,
            write_artifacts=False,
        )


def test_oneway_sweep_points_include_low_central_high(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = OneWaySensitivityExperiment(
        config,
        parameter_names=["soiling.base_daily_loss_fraction"],
        steps=5,
        write_artifacts=False,
    ).run()
    parameter_result = outcome.result.parameter_results[0]
    swept_values = {point.value for point in parameter_result.points}
    assert parameter_result.spec.low_value in swept_values
    assert parameter_result.spec.central_value in swept_values
    assert parameter_result.spec.high_value in swept_values
    assert len(swept_values) == 5


def test_sweep_point_count_is_exact_when_central_equals_endpoint(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    experiment = OneWaySensitivityExperiment(
        config,
        parameter_names=["economics.electricity_tariff_sar_per_kwh"],
        steps=5,
        write_artifacts=False,
    )
    spec = experiment._catalog_by_name["economics.electricity_tariff_sar_per_kwh"]
    points = sensitivity_module._sweep_points(spec, 5)
    assert len(points) == 5
    assert {spec.low_value, spec.central_value, spec.high_value} <= set(points)


def test_oneway_default_parameter_set_uses_full_supported_catalog(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = OneWaySensitivityExperiment(
        config, parameter_names=None, steps=3, write_artifacts=False
    ).run()
    # Every registry parameter this catalog supports should have been swept exactly once.
    names = [r.spec.name for r in outcome.result.parameter_results]
    assert len(names) == len(set(names))
    assert len(names) >= 30  # 35 supported at time of writing; loose bound to avoid brittleness


def test_oneway_partial_period_points_are_reported_invalid(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = OneWaySensitivityExperiment(
        config,
        parameter_names=["coating.useful_life_years"],
        steps=5,
        write_artifacts=False,
    ).run()
    swing = outcome.result.parameter_results[0].swing_sar
    assert swing == {"baseline": 0.0, "reactive": 0.0, "coating": 0.0}
    assert all(not point.reconciled for point in outcome.result.parameter_results[0].points)


def test_oneway_writes_full_artifact_package(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = OneWaySensitivityExperiment(
        config,
        parameter_names=["soiling.base_daily_loss_fraction", "coating.useful_life_years"],
        steps=3,
    ).run()
    result = outcome.result
    expected = {
        "config_resolved.yaml",
        "sensitivity_oneway.csv",
        "sensitivity_oneway_summary.json",
        "sensitivity_tornado.png",
        "summary.json",
        "summary.txt",
    }
    assert expected <= {p.name for p in result.output_directory.iterdir()}

    frame = pd.read_csv(result.output_directory / "sensitivity_oneway.csv")
    assert set(frame["parameter_name"]) == {
        "soiling.base_daily_loss_fraction",
        "coating.useful_life_years",
    }
    for scenario_id in CANONICAL_SCENARIO_IDS:
        assert f"{scenario_id}_net_annual_benefit_sar" in frame.columns

    summary = json.loads(
        (result.output_directory / "sensitivity_oneway_summary.json").read_text(encoding="utf-8")
    )
    assert summary["parameters_swept"] == 2
    assert summary["base_mode"] == "reference_config"


def test_ranked_by_swing_is_sorted_descending(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = OneWaySensitivityExperiment(
        config,
        parameter_names=[
            "soiling.base_daily_loss_fraction",
            "coating.useful_life_years",
            "economics.electricity_tariff_sar_per_kwh",
        ],
        steps=3,
        write_artifacts=False,
    ).run()
    ranked = outcome.result.ranked_by_swing("coating")
    swings = [r.swing_sar["coating"] for r in ranked]
    assert swings == sorted(swings, reverse=True)


# --- Two-way ------------------------------------------------------------


def test_twoway_rejects_identical_parameters(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    with pytest.raises(ValueError, match="must differ"):
        TwoWaySensitivityExperiment(
            config,
            parameter_name_a="soiling.base_daily_loss_fraction",
            parameter_name_b="soiling.base_daily_loss_fraction",
        )


def test_twoway_rejects_unsupported_parameter(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    with pytest.raises(ValueError, match="not a T7-supported"):
        TwoWaySensitivityExperiment(
            config,
            parameter_name_a="soiling.base_daily_loss_fraction",
            parameter_name_b="coating.installed_capex_sar",
        )


def test_twoway_grid_covers_full_cartesian_product(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = TwoWaySensitivityExperiment(
        config,
        parameter_name_a="soiling.base_daily_loss_fraction",
        parameter_name_b="coating.useful_life_years",
        grid_steps=3,
        write_artifacts=False,
    ).run()
    grid = outcome.result.grid
    values_a = {point.value_a for point in grid}
    values_b = {point.value_b for point in grid}
    assert len(grid) == len(values_a) * len(values_b)


def test_twoway_writes_full_artifact_package(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = TwoWaySensitivityExperiment(
        config,
        parameter_name_a="soiling.base_daily_loss_fraction",
        parameter_name_b="coating.useful_life_years",
        grid_steps=3,
    ).run()
    result = outcome.result
    names = {p.name for p in result.output_directory.iterdir()}
    assert "sensitivity_twoway.csv" in names
    assert "sensitivity_twoway_summary.json" in names
    plot_names = [
        n for n in names if n.startswith("sensitivity_winner_map_") and n.endswith(".png")
    ]
    assert plot_names
    assert all(len(name) < 100 for name in plot_names)

    summary = json.loads(
        (result.output_directory / "sensitivity_twoway_summary.json").read_text(encoding="utf-8")
    )
    assert summary["parameter_a"] == "soiling.base_daily_loss_fraction"
    assert summary["parameter_b"] == "coating.useful_life_years"
    assert summary["failed_grid_point_count"] == 9


# --- Break-even -----------------------------------------------------------


def test_breakeven_rejects_same_scenario_twice(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    with pytest.raises(ValueError, match="must differ"):
        BreakEvenExperiment(
            config,
            parameter_name="coating.useful_life_years",
            scenario_a="coating",
            scenario_b="coating",
        )


def test_breakeven_rejects_unknown_scenario(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    with pytest.raises(ValueError, match="baseline, reactive, or coating"):
        BreakEvenExperiment(
            config,
            parameter_name="coating.useful_life_years",
            scenario_a="coating",
            scenario_b="not_a_scenario",
        )


def _synthetic_breakeven_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, margin_fn):
    config = _fixture_config(tmp_path)
    experiment = BreakEvenExperiment(
        config,
        parameter_name="coating.useful_life_years",
        scenario_a="reactive",
        scenario_b="baseline",
        max_evaluations=30,
        write_artifacts=False,
    )

    def fake_evaluate(value: float) -> BreakEvenEvaluation:
        margin = float(margin_fn(value))
        return BreakEvenEvaluation(
            value=value,
            margin_sar=margin,
            reconciled=True,
            net_annual_benefit_sar={
                "baseline": 0.0,
                "reactive": margin,
                "coating": 0.0,
            },
        )

    monkeypatch.setattr(experiment, "_evaluate", fake_evaluate)
    return experiment.run().result


def test_breakeven_scan_reports_one_crossing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _synthetic_breakeven_result(
        tmp_path,
        monkeypatch,
        lambda value: value - 3.5,
    )

    assert result.crossover_found is True
    assert result.crossing_status == "one_crossing"
    assert len(result.crossover_values) == 1
    assert result.crossover_values[0] == pytest.approx(3.5, rel=1e-2)
    assert result.likely_non_monotonic is False


def test_breakeven_scan_reports_multiple_non_monotonic_crossings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _synthetic_breakeven_result(
        tmp_path,
        monkeypatch,
        lambda value: (value - 2.0) * (value - 5.0),
    )

    assert result.crossover_found is True
    assert result.crossing_status == "multiple_crossings"
    assert result.likely_non_monotonic is True
    assert len(result.crossover_values) == 2
    assert result.crossover_values[0] == pytest.approx(2.0, rel=1e-2)
    assert result.crossover_values[1] == pytest.approx(5.0, rel=1e-2)


def test_breakeven_refuses_unreconciled_evaluations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _fixture_config(tmp_path)

    def fake_run_variant(**_kwargs):
        return VariantResult(
            net_annual_benefit_sar={
                "baseline": 0.0,
                "reactive": 10.0,
                "coating": 0.0,
            },
            winner=None,
            reconciled=False,
            failed_reconciliation_checks=(
                {
                    "name": "same_weather_checksum",
                    "message": "Scenarios did not share exactly one weather checksum.",
                    "details": {},
                },
            ),
        )

    monkeypatch.setattr(sensitivity_module, "_run_variant", fake_run_variant)
    result = (
        BreakEvenExperiment(
            config,
            parameter_name="coating.useful_life_years",
            scenario_a="reactive",
            scenario_b="baseline",
            write_artifacts=False,
        )
        .run()
        .result
    )

    assert result.crossover_found is False
    assert result.crossing_status == "invalid_evaluation"
    assert result.invalid_evaluation_count > 0
    assert "same_weather_checksum" in result.message
    assert result.evaluations[0].margin_sar is None
    assert result.evaluations[0].failed_reconciliation_checks


def test_breakeven_refuses_partial_period_economics(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = BreakEvenExperiment(
        config,
        parameter_name="coating.useful_life_years",
        scenario_a="coating",
        scenario_b="baseline",
        write_artifacts=False,
    ).run()
    result = outcome.result
    assert result.crossover_found is False
    assert result.crossover_value is None
    assert result.crossing_status == "invalid_evaluation"
    assert "did not reconcile" in result.message


def test_breakeven_evaluations_are_bounded_by_max_evaluations(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = BreakEvenExperiment(
        config,
        parameter_name="coating.useful_life_years",
        scenario_a="coating",
        scenario_b="baseline",
        max_evaluations=6,
        write_artifacts=False,
    ).run()
    assert len(outcome.result.evaluations) <= 6


def test_breakeven_writes_full_artifact_package(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = BreakEvenExperiment(
        config,
        parameter_name="coating.useful_life_years",
        scenario_a="coating",
        scenario_b="baseline",
    ).run()
    result = outcome.result
    expected = {
        "config_resolved.yaml",
        "breakeven_report.json",
        f"breakeven_{result.parameter_name}.png",
        "summary.json",
        "summary.txt",
    }
    assert expected <= {p.name for p in result.output_directory.iterdir()}
    report = json.loads(
        (result.output_directory / "breakeven_report.json").read_text(encoding="utf-8")
    )
    assert report["parameter_name"] == "coating.useful_life_years"
    assert report["scenario_a"] == "coating"
    assert report["scenario_b"] == "baseline"
    assert report["objective_metric"] == "net_annual_benefit_sar"
    assert "crossing_status" in report
    assert "evaluations" in report
