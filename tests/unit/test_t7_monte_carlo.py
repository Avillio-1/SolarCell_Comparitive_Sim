from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pandas as pd
import pytest
from tests.config_factory import fixture_config

import solarclean.application.monte_carlo as monte_carlo_module
from solarclean.application.comparison import CANONICAL_SCENARIO_IDS
from solarclean.application.monte_carlo import (
    MonteCarloExperiment,
    MonteCarloTrialRecord,
    _majority_winner,
)
from solarclean.domain.calibration.parameter_overrides import build_parameter_catalog
from solarclean.domain.calibration.registry import ParameterRegistry


def _fixture_config(output_dir: Path):
    return fixture_config(overrides={"output": {"base_directory": output_dir}})


def test_monte_carlo_requires_at_least_two_trials(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 2"):
        MonteCarloExperiment(_fixture_config(tmp_path), trial_count=1)


def test_monte_carlo_prepares_weather_and_pv_profile_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _fixture_config(tmp_path)
    original_load = monte_carlo_module._load_weather
    original_calculate = monte_carlo_module.PVWattsPowerModel.calculate_hourly
    calls = {"weather": 0, "pv": 0}

    def counted_load(config_arg):
        calls["weather"] += 1
        return original_load(config_arg)

    def counted_calculate(model, weather, system=None):
        calls["pv"] += 1
        return original_calculate(model, weather, system)

    monkeypatch.setattr(monte_carlo_module, "_load_weather", counted_load)
    monkeypatch.setattr(monte_carlo_module.PVWattsPowerModel, "calculate_hourly", counted_calculate)
    MonteCarloExperiment(config, trial_count=2, write_artifacts=False).run()

    assert calls == {"weather": 1, "pv": 1}


def test_majority_winner_requires_a_unique_absolute_majority() -> None:
    def trial(index: int, winner: str | None) -> MonteCarloTrialRecord:
        return MonteCarloTrialRecord(
            trial_index=index,
            seed=index + 1,
            reconciled=True,
            winner=winner,
            net_annual_benefit_sar=MappingProxyType({}),
            annual_actual_energy_kwh=MappingProxyType({}),
            energy_gain_vs_baseline_kwh=MappingProxyType({}),
        )

    assert _majority_winner((trial(0, None), trial(1, None))) is None
    assert _majority_winner((trial(0, "reactive"), trial(1, "coating"))) is None
    assert (
        _majority_winner((trial(0, "reactive"), trial(1, "reactive"), trial(2, "coating")))
        == "reactive"
    )


def test_monte_carlo_is_reproducible_for_a_fixed_base_seed(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    first = MonteCarloExperiment(config, trial_count=5, base_seed=7, write_artifacts=False).run()
    second = MonteCarloExperiment(config, trial_count=5, base_seed=7, write_artifacts=False).run()

    seeds_first = [trial.seed for trial in first.result.trials]
    seeds_second = [trial.seed for trial in second.result.trials]
    assert seeds_first == seeds_second

    benefits_first = [trial.net_annual_benefit_sar for trial in first.result.trials]
    benefits_second = [trial.net_annual_benefit_sar for trial in second.result.trials]
    assert benefits_first == benefits_second


def test_seed_only_default_matches_explicit_legacy_mode(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    implicit = MonteCarloExperiment(
        config, trial_count=2, base_seed=17, write_artifacts=False
    ).run()
    explicit = MonteCarloExperiment(
        config,
        trial_count=2,
        base_seed=17,
        uncertainty_mode="stochastic_seed_only",
        write_artifacts=False,
    ).run()

    assert [trial.seed for trial in implicit.result.trials] == [1120951905, 889418966]
    assert [trial.to_record() for trial in implicit.result.trials] == [
        trial.to_record() for trial in explicit.result.trials
    ]
    assert implicit.result.scenario_summaries == explicit.result.scenario_summaries


def test_monte_carlo_different_base_seeds_can_produce_different_trial_seeds(
    tmp_path: Path,
) -> None:
    config = _fixture_config(tmp_path)
    a = MonteCarloExperiment(config, trial_count=5, base_seed=1, write_artifacts=False).run()
    b = MonteCarloExperiment(config, trial_count=5, base_seed=2, write_artifacts=False).run()
    seeds_a = [trial.seed for trial in a.result.trials]
    seeds_b = [trial.seed for trial in b.result.trials]
    assert seeds_a != seeds_b


def test_monte_carlo_writes_full_artifact_package(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = MonteCarloExperiment(config, trial_count=6, base_seed=42).run()
    result = outcome.result

    assert result.trial_count == 6
    assert result.reconciled_trial_count + result.failed_trial_count == result.trial_count
    assert set(result.scenario_summaries) == set(CANONICAL_SCENARIO_IDS)

    expected_artifacts = {
        "config_resolved.yaml",
        "monte_carlo_trials.csv",
        "monte_carlo_summary.json",
        "monte_carlo_outcome_distributions.png",
        "monte_carlo_win_probability.png",
        "summary.json",
        "summary.txt",
    }
    assert expected_artifacts <= {path.name for path in result.output_directory.iterdir()}

    trials = pd.read_csv(result.output_directory / "monte_carlo_trials.csv")
    assert len(trials) == 6
    for scenario_id in CANONICAL_SCENARIO_IDS:
        assert f"{scenario_id}_net_annual_benefit_sar" in trials.columns

    summary = json.loads(
        (result.output_directory / "monte_carlo_summary.json").read_text(encoding="utf-8")
    )
    assert summary["trial_count"] == 6
    assert summary["uncertainty_mode"] == "stochastic_seed_only"
    assert summary["sampled_parameter_uncertainty"] is False
    assert "central_t6_winner" in summary
    assert "majority_trial_winner" in summary
    assert "central_winner" not in summary
    assert set(summary["scenario_summaries"]) == set(CANONICAL_SCENARIO_IDS)


def test_monte_carlo_win_probabilities_sum_to_one_when_fully_reconciled(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = MonteCarloExperiment(config, trial_count=8, base_seed=99, write_artifacts=False).run()
    result = outcome.result
    if result.reconciled_trial_count == 0:
        pytest.skip("no reconciled trials to check win probabilities against")
    total_probability = sum(
        summary.win_probability for summary in result.scenario_summaries.values()
    )
    assert total_probability == pytest.approx(1.0)


def test_monte_carlo_no_artifact_mode_does_not_create_output_directory(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = MonteCarloExperiment(config, trial_count=3, base_seed=5, write_artifacts=False).run()
    assert not outcome.output_directory.exists()
    assert outcome.result.output_artifacts == ()


def test_monte_carlo_separates_central_t6_and_majority_trial_winners(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = MonteCarloExperiment(config, trial_count=4, base_seed=11, write_artifacts=False).run()
    result = outcome.result

    assert result.uncertainty_mode == "stochastic_seed_only"
    assert result.central_t6_winner in (*CANONICAL_SCENARIO_IDS, None)
    assert result.majority_trial_winner in (*CANONICAL_SCENARIO_IDS, None)
    assert isinstance(result.central_t6_reconciled, bool)
    for trial in result.trials:
        record = trial.to_record()
        assert "failed_reconciliation_check_names" in record
        assert "failed_reconciliation_checks" in record


def test_parameter_and_seed_mode_is_deterministic_and_within_catalog_bounds(
    tmp_path: Path,
) -> None:
    config = _fixture_config(tmp_path)
    first = MonteCarloExperiment(
        config,
        trial_count=4,
        base_seed=73,
        uncertainty_mode="parameters_and_seed",
        write_artifacts=False,
    ).run()
    second = MonteCarloExperiment(
        config,
        trial_count=4,
        base_seed=73,
        uncertainty_mode="parameters_and_seed",
        write_artifacts=False,
    ).run()
    registry = ParameterRegistry.from_yaml(config.calibration.parameter_registry_path)
    catalog, _ = build_parameter_catalog(registry)
    specs = {spec.name: spec for spec in catalog}

    assert [dict(trial.sampled_parameters) for trial in first.result.trials] == [
        dict(trial.sampled_parameters) for trial in second.result.trials
    ]
    assert first.result.scenario_summaries == second.result.scenario_summaries
    first_record = first.result.to_record()
    second_record = second.result.to_record()
    first_record.pop("run_id")
    second_record.pop("run_id")
    assert first_record == second_record
    for trial in first.result.trials:
        assert set(trial.sampled_parameters) == set(specs)
        for name, value in trial.sampled_parameters.items():
            spec = specs[name]
            assert spec.low_value <= value <= spec.high_value


def test_parameter_and_seed_mode_writes_samples_and_extended_summary(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    outcome = MonteCarloExperiment(
        config,
        trial_count=4,
        base_seed=91,
        uncertainty_mode="parameters_and_seed",
    ).run()
    result = outcome.result
    registry = ParameterRegistry.from_yaml(config.calibration.parameter_registry_path)
    catalog, _ = build_parameter_catalog(registry)
    parameter_names = {spec.name for spec in catalog}

    samples_path = result.output_directory / "monte_carlo_parameter_samples.csv"
    assert samples_path.exists()
    samples = pd.read_csv(samples_path)
    assert len(samples) == 4
    assert parameter_names <= set(samples.columns)
    for scenario_id in CANONICAL_SCENARIO_IDS:
        assert f"{scenario_id}_net_annual_benefit_sar" in samples.columns

    summary = json.loads(
        (result.output_directory / "monte_carlo_summary.json").read_text(encoding="utf-8")
    )
    assert summary["uncertainty_mode"] == "parameters_and_seed"
    assert summary["sampled_parameter_uncertainty"] is True
    for scenario_summary in summary["scenario_summaries"].values():
        for percentile in (5, 25, 50, 75, 95):
            assert f"p{percentile}_net_annual_benefit_sar" in scenario_summary
            assert f"p{percentile}_energy_gain_vs_baseline_kwh" in scenario_summary
        assert "win_probability" in scenario_summary

    total_probability = sum(
        scenario_summary["win_probability"]
        for scenario_summary in summary["scenario_summaries"].values()
    )
    if result.reconciled_trial_count:
        assert total_probability == pytest.approx(1.0)
    else:
        assert total_probability == 0.0
