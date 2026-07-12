from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import cast

import pandas as pd
import pytest
from tests.config_factory import fixture_config

import solarclean.application.monte_carlo as monte_carlo_module
import solarclean.application.sensitivity as sensitivity_module
from solarclean.application.comparison import CANONICAL_SCENARIO_IDS
from solarclean.application.monte_carlo import MonteCarloExperiment, MonteCarloTrialRecord
from solarclean.application.sensitivity import (
    BreakEvenExperiment,
    OneWaySensitivityExperiment,
    SweepPoint,
    TwoWaySensitivityExperiment,
    VariantResult,
)
from solarclean.config.models import SolarCleanConfig
from solarclean.domain.calibration.registry import ParameterRegistry

REVERSED_SCENARIO_ORDER = tuple(reversed(CANONICAL_SCENARIO_IDS))


def _fixture_config(output_dir: Path) -> SolarCleanConfig:
    return fixture_config(overrides={"output": {"base_directory": output_dir}})


def _trial_payload(trial: MonteCarloTrialRecord) -> dict[str, object]:
    payload = trial.to_record()
    payload.pop("trial_index")
    return payload


def _oneway_payload(outcome: object) -> dict[str, object]:
    result = cast(sensitivity_module.OneWaySensitivityOutcome, outcome).result
    return {
        "base_winner": result.base_winner,
        "base_reconciled": result.base_reconciled,
        "base_net_annual_benefit_sar": dict(result.base_net_annual_benefit_sar),
        "base_failed_reconciliation_checks": [
            dict(check) for check in result.base_failed_reconciliation_checks
        ],
        "parameters": {
            parameter.spec.name: {
                "winner_changed": parameter.winner_changed,
                "swing_sar": dict(parameter.swing_sar),
                "points": [point.to_record(parameter.spec.name) for point in parameter.points],
            }
            for parameter in result.parameter_results
        },
        "skipped_parameters": result.skipped_parameters,
    }


def _assert_failed_check_details_are_immutable(
    checks: Sequence[Mapping[str, object]],
) -> None:
    assert checks, "the short fixture should expose its blocking partial-period warning"
    details = cast(Mapping[str, object], checks[0]["details"])
    with pytest.raises(TypeError):
        details["adversarial_mutation"] = True  # type: ignore[index]
    warning_codes = details.get("warning_codes")
    if warning_codes is not None:
        assert isinstance(warning_codes, tuple)


def test_monte_carlo_trials_are_seed_local_across_trial_and_scenario_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _fixture_config(tmp_path)
    seeds = (101, 202, 303)

    forward = MonteCarloExperiment(
        config,
        trial_count=len(seeds),
        base_seed=77,
        scenario_order=CANONICAL_SCENARIO_IDS,
        write_artifacts=False,
    )
    monkeypatch.setattr(forward, "trial_seeds", lambda: seeds)
    forward_result = forward.run().result
    forward_by_seed = {trial.seed: _trial_payload(trial) for trial in forward_result.trials}

    reverse = MonteCarloExperiment(
        config,
        trial_count=len(seeds),
        base_seed=77,
        scenario_order=REVERSED_SCENARIO_ORDER,
        write_artifacts=False,
    )
    monkeypatch.setattr(reverse, "trial_seeds", lambda: tuple(reversed(seeds)))
    reverse_result = reverse.run().result
    reverse_by_seed = {trial.seed: _trial_payload(trial) for trial in reverse_result.trials}

    assert reverse_by_seed == forward_by_seed
    assert {trial.seed: _trial_payload(trial) for trial in forward_result.trials} == forward_by_seed
    assert dict(reverse_result.scenario_summaries) == dict(forward_result.scenario_summaries)
    assert reverse_result.central_t6_winner == forward_result.central_t6_winner
    assert reverse_result.central_t6_reconciled == forward_result.central_t6_reconciled


def test_monte_carlo_repeated_seed_is_isolated_from_an_intervening_trial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _fixture_config(tmp_path)
    experiment = MonteCarloExperiment(
        config,
        trial_count=3,
        base_seed=19,
        write_artifacts=False,
    )
    monkeypatch.setattr(experiment, "trial_seeds", lambda: (991, 443, 991))

    result = experiment.run().result
    first, _, repeated = result.trials

    assert _trial_payload(repeated) == _trial_payload(first)
    assert repeated is not first
    assert repeated.net_annual_benefit_sar is not first.net_annual_benefit_sar
    assert repeated.annual_actual_energy_kwh is not first.annual_actual_energy_kwh
    with pytest.raises(TypeError):
        first.net_annual_benefit_sar["baseline"] = -1.0  # type: ignore[index]
    _assert_failed_check_details_are_immutable(first.failed_reconciliation_checks)


def test_monte_carlo_and_sensitivity_leave_reused_weather_and_pv_inputs_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _fixture_config(tmp_path)
    weather = monte_carlo_module._load_weather(config)
    clean_energy = monte_carlo_module.PVWattsPowerModel().calculate_hourly(
        weather, config.pv_system
    )
    weather_hourly_before = weather.hourly.copy(deep=True)
    weather_metadata_before = dict(weather.metadata)
    clean_hourly_before = clean_energy.hourly.copy(deep=True)
    clean_daily_before = clean_energy.daily.copy(deep=True)
    clean_metadata_before = dict(clean_energy.metadata)

    monkeypatch.setattr(monte_carlo_module, "_load_weather", lambda _config: weather)

    def reuse_clean_energy(_model: object, weather_arg: object, _system: object = None) -> object:
        assert weather_arg is weather
        return clean_energy

    monkeypatch.setattr(
        monte_carlo_module.PVWattsPowerModel,
        "calculate_hourly",
        reuse_clean_energy,
    )
    monkeypatch.setattr(
        sensitivity_module,
        "_prepare_shared_inputs",
        lambda _config: (weather, clean_energy),
    )

    MonteCarloExperiment(config, trial_count=2, base_seed=7, write_artifacts=False).run()
    OneWaySensitivityExperiment(
        config,
        parameter_names=("soiling.base_daily_loss_fraction",),
        steps=3,
        write_artifacts=False,
    ).run()

    pd.testing.assert_frame_equal(weather.hourly, weather_hourly_before, check_exact=True)
    pd.testing.assert_frame_equal(clean_energy.hourly, clean_hourly_before, check_exact=True)
    pd.testing.assert_frame_equal(clean_energy.daily, clean_daily_before, check_exact=True)
    assert weather.metadata == weather_metadata_before
    assert clean_energy.metadata == clean_metadata_before


@pytest.mark.parametrize(
    "parameter_name",
    [
        "soiling.base_daily_loss_fraction",
        "economics.electricity_tariff_sar_per_kwh",
    ],
)
def test_oneway_repeated_point_is_isolated_for_config_and_registry_overrides(
    parameter_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _fixture_config(tmp_path)
    experiment = OneWaySensitivityExperiment(
        config,
        parameter_names=(parameter_name,),
        steps=3,
        write_artifacts=False,
    )
    config_before = config.model_dump(mode="python")
    registry_checksum_before = experiment.registry.checksum()

    def repeated_endpoints(
        spec: sensitivity_module.ParameterOverrideSpec,
        _steps: int,
    ) -> tuple[float, ...]:
        return (spec.low_value, spec.high_value, spec.low_value)

    monkeypatch.setattr(sensitivity_module, "_sweep_points", repeated_endpoints)
    result = experiment.run().result.parameter_results[0]
    first, _, repeated = result.points

    assert repeated.to_record(parameter_name) == first.to_record(parameter_name)
    assert repeated is not first
    assert repeated.net_annual_benefit_sar is not first.net_annual_benefit_sar
    with pytest.raises(TypeError):
        first.net_annual_benefit_sar["baseline"] = -1.0  # type: ignore[index]
    _assert_failed_check_details_are_immutable(first.failed_reconciliation_checks)
    assert config.model_dump(mode="python") == config_before
    assert experiment.registry.checksum() == registry_checksum_before


def test_oneway_is_independent_of_parameter_and_scenario_order_and_reusable(
    tmp_path: Path,
) -> None:
    config = _fixture_config(tmp_path)
    names = (
        "soiling.base_daily_loss_fraction",
        "economics.electricity_tariff_sar_per_kwh",
    )
    experiment = OneWaySensitivityExperiment(
        config,
        parameter_names=names,
        steps=3,
        scenario_order=CANONICAL_SCENARIO_IDS,
        write_artifacts=False,
    )
    registry_checksum_before = experiment.registry.checksum()

    first = experiment.run()
    first_payload = _oneway_payload(first)
    reversed_outcome = OneWaySensitivityExperiment(
        config,
        parameter_names=tuple(reversed(names)),
        steps=3,
        scenario_order=REVERSED_SCENARIO_ORDER,
        write_artifacts=False,
    ).run()
    repeated = experiment.run()

    assert _oneway_payload(reversed_outcome) == first_payload
    assert _oneway_payload(repeated) == first_payload
    assert repeated.result is not first.result
    assert repeated.result.parameter_results[0] is not first.result.parameter_results[0]
    assert experiment.registry.checksum() == registry_checksum_before


def test_twoway_axis_order_does_not_change_grid_or_mutate_registry(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    name_a = "soiling.base_daily_loss_fraction"
    name_b = "economics.electricity_tariff_sar_per_kwh"
    forward = TwoWaySensitivityExperiment(
        config,
        parameter_name_a=name_a,
        parameter_name_b=name_b,
        grid_steps=3,
        scenario_order=CANONICAL_SCENARIO_IDS,
        write_artifacts=False,
    )
    checksum_before = forward.registry.checksum()
    forward_result = forward.run().result
    reverse_result = (
        TwoWaySensitivityExperiment(
            config,
            parameter_name_a=name_b,
            parameter_name_b=name_a,
            grid_steps=3,
            scenario_order=REVERSED_SCENARIO_ORDER,
            write_artifacts=False,
        )
        .run()
        .result
    )

    forward_grid = {
        (point.value_a, point.value_b): (
            point.winner,
            point.reconciled,
            dict(point.net_annual_benefit_sar),
            [dict(check) for check in point.failed_reconciliation_checks],
        )
        for point in forward_result.grid
    }
    reverse_grid = {
        (point.value_b, point.value_a): (
            point.winner,
            point.reconciled,
            dict(point.net_annual_benefit_sar),
            [dict(check) for check in point.failed_reconciliation_checks],
        )
        for point in reverse_result.grid
    }

    assert reverse_grid == forward_grid
    assert forward.registry.checksum() == checksum_before


def test_breakeven_rebuilds_shared_inputs_and_does_not_reuse_evaluations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _fixture_config(tmp_path)
    prepared_pairs = ((object(), object()), (object(), object()))
    prepare_calls = 0
    variant_inputs: list[tuple[object | None, object | None]] = []

    def fake_prepare(_config: SolarCleanConfig) -> tuple[object, object]:
        nonlocal prepare_calls
        pair = prepared_pairs[prepare_calls]
        prepare_calls += 1
        return pair

    def fake_run_variant(
        *,
        config: SolarCleanConfig,
        registry: ParameterRegistry,
        scenario_order: Sequence[str] | None,
        weather: object | None = None,
        clean_energy: object | None = None,
    ) -> VariantResult:
        del registry, scenario_order
        variant_inputs.append((weather, clean_energy))
        useful_life = float(config.coating.costs.useful_life_years)
        return VariantResult(
            net_annual_benefit_sar=MappingProxyType(
                {"baseline": 0.0, "reactive": 0.0, "coating": useful_life}
            ),
            winner="coating",
            reconciled=True,
            failed_reconciliation_checks=(),
        )

    monkeypatch.setattr(sensitivity_module, "_prepare_shared_inputs", fake_prepare)
    monkeypatch.setattr(sensitivity_module, "_run_variant", fake_run_variant)
    experiment = BreakEvenExperiment(
        config,
        parameter_name="coating.useful_life_years",
        scenario_a="coating",
        scenario_b="baseline",
        max_evaluations=3,
        write_artifacts=False,
    )

    first = experiment.run().result
    first_call_count = len(variant_inputs)
    first_payload = [evaluation.to_record() for evaluation in first.evaluations]
    repeated = experiment.run().result

    assert prepare_calls == 2
    assert variant_inputs[:first_call_count]
    assert all(pair == prepared_pairs[0] for pair in variant_inputs[:first_call_count])
    assert all(pair == prepared_pairs[1] for pair in variant_inputs[first_call_count:])
    assert [evaluation.to_record() for evaluation in repeated.evaluations] == first_payload
    assert repeated is not first
    assert all(
        right.net_annual_benefit_sar is not left.net_annual_benefit_sar
        for left, right in zip(first.evaluations, repeated.evaluations, strict=True)
    )


@pytest.mark.parametrize("kind", ["monte_carlo", "sensitivity"])
def test_serialized_failure_checks_do_not_alias_frozen_result_details(kind: str) -> None:
    source_details: dict[str, object] = {"codes": ["original"]}
    check = MappingProxyType(
        {
            "name": "adversarial_check",
            "message": "synthetic",
            "details": source_details,
        }
    )
    if kind == "monte_carlo":
        zero_by_scenario = MappingProxyType(
            {scenario_id: 0.0 for scenario_id in CANONICAL_SCENARIO_IDS}
        )
        result_object: MonteCarloTrialRecord | SweepPoint = MonteCarloTrialRecord(
            trial_index=0,
            seed=1,
            reconciled=False,
            winner=None,
            net_annual_benefit_sar=zero_by_scenario,
            annual_actual_energy_kwh=zero_by_scenario,
            energy_gain_vs_baseline_kwh=zero_by_scenario,
            failed_reconciliation_checks=(check,),
        )
        record = result_object.to_record()
    else:
        result_object = SweepPoint(
            value=1.0,
            net_annual_benefit_sar=MappingProxyType({}),
            winner=None,
            reconciled=False,
            failed_reconciliation_checks=(check,),
        )
        record = result_object.to_record("synthetic.parameter")

    serialized_checks = cast(list[dict[str, object]], record["failed_reconciliation_checks"])
    serialized_details = cast(dict[str, object], serialized_checks[0]["details"])
    serialized_codes = cast(list[str], serialized_details["codes"])
    serialized_codes.append("mutated-through-record")
    serialized_details["new_key"] = True

    assert source_details == {"codes": ["original"]}
