from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import solarclean.application.comparison as comparison_module
from solarclean.application.comparison import (
    CANONICAL_SCENARIO_IDS,
    CompareAllScenarios,
    build_reconciliation_report,
)
from solarclean.config.loader import load_config
from solarclean.domain.economics import evaluate_annual_scenario_outputs
from solarclean.domain.scenario.contracts import ScenarioContext
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider


def _fixture_config(output_dir: Path):
    return load_config(
        Path("configs/offline_fixture.yaml"),
        overrides={"output": {"base_directory": output_dir}},
    )


def test_compare_all_scenarios_writes_one_reconciled_ranked_package(tmp_path: Path) -> None:
    result = CompareAllScenarios(_fixture_config(tmp_path)).run()
    comparison = result.comparison

    assert set(comparison.scenario_results) == set(CANONICAL_SCENARIO_IDS)
    assert comparison.reconciliation_report.passed
    assert len(comparison.ranking) == 3
    assert comparison.recommendation.valid
    assert result.summary["reconciled"] is True

    check_by_name = {check.name: check for check in comparison.reconciliation_report.checks}
    assert check_by_name["same_weather_checksum"].passed
    assert check_by_name["same_event_tape_checksum"].passed
    assert check_by_name["exactly_one_ranking_produced_for_valid_run"].passed
    assert check_by_name["ranking_sorted_by_net_annual_benefit"].passed
    assert check_by_name["assumption_warnings_present"].passed

    annual = pd.read_csv(result.output_directory / "scenario_annual_summary.csv")
    daily = pd.read_csv(result.output_directory / "scenario_daily_summary.csv")
    cost = pd.read_csv(result.output_directory / "scenario_cost_summary.csv")
    ranking = json.loads(
        (result.output_directory / "scenario_ranking.json").read_text(encoding="utf-8")
    )
    recommendation = json.loads(
        (result.output_directory / "recommendation.json").read_text(encoding="utf-8")
    )
    reconciliation = json.loads(
        (result.output_directory / "reconciliation_report.json").read_text(encoding="utf-8")
    )

    assert set(annual["scenario_id"]) == set(CANONICAL_SCENARIO_IDS)
    assert set(daily["scenario_id"]) == set(CANONICAL_SCENARIO_IDS)
    assert set(cost["scenario_id"]) == set(CANONICAL_SCENARIO_IDS)
    assert len(ranking["ranking"]) == 3
    assert recommendation["valid"] is True
    assert reconciliation["passed"] is True
    assert annual["weather_checksum"].nunique() == 1
    assert annual["event_tape_checksum"].nunique() == 1
    assert "net_annual_benefit_sar" in annual.columns
    assert "cost_reconciliation_messages" in cost.columns

    expected_artifacts = {
        "config_resolved.yaml",
        "comparison_metadata.json",
        "scenario_annual_summary.csv",
        "scenario_daily_summary.csv",
        "scenario_cost_summary.csv",
        "scenario_ranking.json",
        "recommendation.json",
        "reconciliation_report.json",
        "scenario_events.csv",
        "event_tape.json",
        "comparison_daily_energy.png",
        "comparison_normalized_performance.png",
        "comparison_daily_loss_percent.png",
        "comparison_cumulative_energy.png",
        "comparison_cumulative_loss.png",
        "comparison_soiling_cleanliness.png",
        "comparison_coating_diagnostics.png",
        "comparison_annual_kpi_breakdown.png",
    }
    assert expected_artifacts <= {path.name for path in result.output_directory.iterdir()}
    assert any(
        warning.get("code") == "non_validated_economic_parameter" for warning in comparison.warnings
    )
    assert any(
        warning.get("code") == "simulation_period_not_full_year" for warning in comparison.warnings
    )


def test_full_year_offline_comparison_config_covers_2025() -> None:
    config = load_config(Path("configs/offline_fixture_full_year.yaml"))

    assert config.weather.provider == "fixture"
    assert config.simulation.start.isoformat() == "2025-01-01T00:00:00+03:00"
    assert config.simulation.end.isoformat() == "2025-12-31T23:00:00+03:00"
    assert config.calibration.assumption_set == "riyadh_central_v2"
    assert 0.0 < config.soiling.base_daily_soiling_loss_fraction < 0.01
    assert config.reactive_cv.inspection.interval_days > 0
    assert config.reactive_cv.drone.cohorts_per_flight > 0
    assert config.reactive_cv.drone.flights_per_day > 0
    assert 0.0 <= config.reactive_cv.observer.recall_fraction <= 1.0
    assert 0.0 <= config.reactive_cv.dispatch.estimated_loss_threshold_fraction <= 1.0
    assert config.reactive_cv.crew.water_liters_per_cohort >= 0.0
    assert config.coating.preset == "central"
    assert 0.0 <= config.coating.physics.dust_accumulation_multiplier <= 1.0
    assert config.coating.costs.maintenance_cost_per_year >= 0.0
    assert config.coating.costs.useful_life_years > 0.0
    assert 0.0 <= config.coating.water.actual_collection_efficiency_fraction <= 1.0
    assert comparison_module._simulation_period_is_full_year(config)


def test_reactive_annual_summary_splits_survey_units_and_dispatch_counts(
    tmp_path: Path,
) -> None:
    config = _fixture_config(tmp_path)
    result = CompareAllScenarios(config).run()
    annual = pd.read_csv(result.output_directory / "scenario_annual_summary.csv")
    reactive = annual.set_index("scenario_id").loc["reactive"]

    assert "annual_operational_whole_farm_survey_count" in annual.columns
    assert "annual_operational_block_or_cohort_inspection_count" in annual.columns
    assert "annual_operational_cleaning_dispatch_count" in annual.columns
    assert "annual_operational_panels_cleaned" in annual.columns
    assert reactive["annual_operational_block_or_cohort_inspection_count"] == pytest.approx(
        reactive["annual_operational_inspections_count"]
    )
    assert reactive["annual_operational_whole_farm_survey_count"] == pytest.approx(
        reactive["annual_operational_inspections_count"] / config.farm.cohort_count
    )
    assert reactive["annual_operational_cleaning_dispatch_count"] == pytest.approx(
        reactive["annual_operational_cleaning_actions_count"]
    )


def test_corrected_t6_economics_include_reactive_overhead_and_coating_life(
    tmp_path: Path,
) -> None:
    result = CompareAllScenarios(_fixture_config(tmp_path)).run()
    cost = pd.read_csv(result.output_directory / "scenario_cost_summary.csv")
    annual = pd.read_csv(result.output_directory / "scenario_annual_summary.csv").set_index(
        "scenario_id"
    )

    reactive_components = set(cost.loc[cost["scenario_id"] == "reactive", "component_name"])
    assert "reactive annual overhead opex" in reactive_components
    assert "reactive drone flight operations" in reactive_components
    assert "reactive energy use" in reactive_components

    coating = annual.loc["coating"]
    assert coating["total_capex_sar"] == pytest.approx(350_000.0)
    assert coating["annual_opex_sar"] == pytest.approx(20_000.0)
    assert coating["capital_recovery_life_years"] == pytest.approx(3.0)
    assert coating["roi_payback_basis"] == "incremental_vs_baseline"
    assert "incremental_roi_vs_baseline" in annual.columns
    assert "incremental_payback_years_vs_baseline" in annual.columns


def test_scenario_execution_order_does_not_change_outputs_or_ranking(tmp_path: Path) -> None:
    first = CompareAllScenarios(
        _fixture_config(tmp_path / "first"),
        scenario_order=("baseline", "reactive", "coating"),
    ).run()
    second = CompareAllScenarios(
        _fixture_config(tmp_path / "second"),
        scenario_order=("coating", "reactive", "baseline"),
    ).run()

    for scenario_id in CANONICAL_SCENARIO_IDS:
        pd.testing.assert_frame_equal(
            first.comparison.scenario_results[scenario_id].to_daily_frame(),
            second.comparison.scenario_results[scenario_id].to_daily_frame(),
        )
        assert (
            first.comparison.economic_summaries[scenario_id]
            == second.comparison.economic_summaries[scenario_id]
        )

    assert [entry.to_record() for entry in first.comparison.ranking] == [
        entry.to_record() for entry in second.comparison.ranking
    ]
    assert first.comparison.recommendation.winner == second.comparison.recommendation.winner
    assert (
        first.comparison.recommendation.ordered_scenario_ids
        == second.comparison.recommendation.ordered_scenario_ids
    )


def test_each_strategy_receives_an_independent_initial_state(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    weather = FixtureWeatherProvider().load(comparison_module._weather_request(config))
    clean = PVWattsPowerModel().calculate_hourly(weather, config.pv_system)
    tape = comparison_module._generate_event_tape(config, clean)
    context = ScenarioContext.from_inputs(
        weather=weather,
        clean_energy=clean,
        event_tape=tape,
        farm_config=config.farm,
    )

    states = []
    for scenario_id in CANONICAL_SCENARIO_IDS:
        strategy = comparison_module._build_strategy(scenario_id, config)
        states.append(strategy.initial_state(context, np.random.default_rng(42)))

    assert len({id(state) for state in states}) == 3
    baseline_a = comparison_module._build_strategy("baseline", config)
    baseline_b = comparison_module._build_strategy("baseline", config)
    state_a = baseline_a.initial_state(context, np.random.default_rng(42))
    state_b = baseline_b.initial_state(context, np.random.default_rng(42))
    assert state_a is not state_b
    assert state_a.farm_state is not state_b.farm_state


def test_comparison_uses_common_t4_economic_engine(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def spy(*, outputs, config):
        calls.append(tuple(output.scenario_name for output in outputs))
        return evaluate_annual_scenario_outputs(outputs=outputs, config=config)

    monkeypatch.setattr(comparison_module, "evaluate_annual_scenario_outputs", spy)

    CompareAllScenarios(_fixture_config(tmp_path)).run()

    assert calls == [CANONICAL_SCENARIO_IDS]


def test_reconciliation_failure_message_identifies_mismatched_weather_checksum(
    tmp_path: Path,
) -> None:
    result = CompareAllScenarios(_fixture_config(tmp_path)).run().comparison
    economics = comparison_module._load_economics(comparison_module.DEFAULT_PARAMETER_REGISTRY_PATH)
    operational = {
        scenario_id: comparison_module._annual_operational_quantities(
            result.scenario_results[scenario_id]
        )
        for scenario_id in CANONICAL_SCENARIO_IDS
    }
    annual_outputs = comparison_module._build_annual_economic_outputs(
        scenario_results=result.scenario_results,
        operational_by_scenario=operational,
        economics=economics,
    )
    cost_checks = comparison_module._cost_reconciliation_checks(
        annual_outputs=annual_outputs,
        economic_results=result.economic_results,
        economics=economics,
    )
    bad_checksums = {
        "baseline": {
            "weather_checksum": "weather-a",
            "event_tape_checksum": result.event_tape_checksum,
        },
        "reactive": {
            "weather_checksum": "weather-b",
            "event_tape_checksum": result.event_tape_checksum,
        },
        "coating": {
            "weather_checksum": "weather-a",
            "event_tape_checksum": result.event_tape_checksum,
        },
    }

    report = build_reconciliation_report(
        scenario_results=result.scenario_results,
        annual_outputs=annual_outputs,
        economic_results=result.economic_results,
        energy_gain_vs_baseline=result.energy_gain_vs_baseline,
        scenario_input_checksums=bad_checksums,
        warnings=result.warnings,
        cost_reconciliation_checks=cost_checks,
        ranking=(),
        preliminary_reconciliation_passed=None,
    )

    check = next(item for item in report.checks if item.name == "same_weather_checksum")
    assert not check.passed
    assert "weather checksum" in check.message


def test_invalid_scenario_order_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="scenario_order"):
        CompareAllScenarios(
            _fixture_config(tmp_path),
            scenario_order=("baseline", "reactive", "reactive"),
        )
