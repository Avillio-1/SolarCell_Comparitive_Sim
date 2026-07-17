"""T7 -- Monte Carlo trials over the T6 three-scenario comparison.

Repeats CompareAllScenarios across many seeded trials to turn the single deterministic T6
result into an outcome distribution per scenario: mean, spread, downside outcome, and the
probability that each scenario actually wins once stochastic noise (dust events, CV
observation error, bird strikes, ...) is taken into account.

Every trial reuses the *same* single point-of-entropy the rest of the codebase already uses --
``config.soiling.random_seed`` -- which seeds both the exogenous event tape and the
``ScenarioSimulationEngine`` (see ``domain/simulation/scenario_engine.py``). Trial seeds are
themselves generated deterministically from one ``base_seed`` via ``random.Random``, so a fixed
experiment configuration reproduces identical results (T7 completion criterion).

Trials never write their own artifact package (``write_artifacts=False`` on
``CompareAllScenarios``) -- only the aggregated experiment result is persisted, one run
directory, at the end.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal

import pandas as pd

from solarclean.application.comparison import (
    CANONICAL_SCENARIO_IDS,
    CompareAllScenarios,
    ComparisonResult,
    ProgressCallback,
    _load_weather,
)
from solarclean.config.models import SolarCleanConfig
from solarclean.domain.calibration.parameter_overrides import (
    ParameterOverrideSpec,
    apply_parameter_override,
    build_parameter_catalog,
)
from solarclean.domain.calibration.registry import ParameterRegistry
from solarclean.domain.environment.weather import WeatherDataset
from solarclean.domain.pv.model import CleanEnergyProfile
from solarclean.infrastructure.persistence.outputs import OutputWriter
from solarclean.infrastructure.persistence.plots import write_monte_carlo_plots
from solarclean.infrastructure.persistence.reports import write_json_report
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel

DEFAULT_TRIAL_COUNT = 100
UncertaintyMode = Literal["stochastic_seed_only", "parameters_and_seed"]
DEFAULT_UNCERTAINTY_MODE: UncertaintyMode = "stochastic_seed_only"


def _freeze_check_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_check_value(item) for key, item in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_check_value(item) for item in value)
    return value


def _freeze_check_record(record: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({str(key): _freeze_check_value(value) for key, value in record.items()})


def _copy_check_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _copy_check_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_copy_check_value(item) for item in value]
    return value


def _copy_check_record(record: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _copy_check_value(value) for key, value in record.items()}


def _failed_reconciliation_checks(
    comparison: ComparisonResult,
) -> tuple[Mapping[str, object], ...]:
    failed = [
        _freeze_check_record(check.to_record())
        for check in comparison.reconciliation_report.checks
        if not check.passed
    ]
    if comparison.reconciliation_report.passed and not comparison.recommendation.calculation_valid:
        failed.append(
            _freeze_check_record(
                {
                    "name": "recommendation_invalid",
                    "message": comparison.recommendation.message,
                    "details": {},
                }
            )
        )
    return tuple(failed)


def _failed_check_names(checks: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    return tuple(str(check.get("name", "")) for check in checks if check.get("name"))


def _failed_check_messages(checks: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    return tuple(str(check.get("message", "")) for check in checks if check.get("message"))


def _check_records(checks: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [_copy_check_record(check) for check in checks]


@dataclass(frozen=True)
class MonteCarloTrialRecord:
    trial_index: int
    seed: int
    reconciled: bool
    winner: str | None
    net_annual_benefit_sar: Mapping[str, float]
    annual_actual_energy_kwh: Mapping[str, float]
    energy_gain_vs_baseline_kwh: Mapping[str, float]
    failed_reconciliation_checks: tuple[Mapping[str, object], ...] = ()
    sampled_parameters: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))

    def to_flat_record(self) -> dict[str, object]:
        record: dict[str, object] = {
            "trial_index": self.trial_index,
            "seed": self.seed,
            "reconciled": self.reconciled,
            "winner": self.winner,
            "failed_reconciliation_check_names": "; ".join(
                _failed_check_names(self.failed_reconciliation_checks)
            ),
            "failed_reconciliation_check_messages": "; ".join(
                _failed_check_messages(self.failed_reconciliation_checks)
            ),
        }
        for scenario_id in CANONICAL_SCENARIO_IDS:
            record[f"{scenario_id}_net_annual_benefit_sar"] = self.net_annual_benefit_sar[
                scenario_id
            ]
            record[f"{scenario_id}_annual_actual_energy_kwh"] = self.annual_actual_energy_kwh[
                scenario_id
            ]
            record[f"{scenario_id}_energy_gain_vs_baseline_kwh"] = self.energy_gain_vs_baseline_kwh[
                scenario_id
            ]
        return record

    def to_record(self) -> dict[str, object]:
        record = self.to_flat_record()
        record["failed_reconciliation_checks"] = _check_records(self.failed_reconciliation_checks)
        if self.sampled_parameters:
            record["sampled_parameters"] = dict(self.sampled_parameters)
        return record


@dataclass(frozen=True)
class ScenarioMonteCarloSummary:
    scenario_id: str
    trial_count: int
    mean_net_annual_benefit_sar: float
    std_net_annual_benefit_sar: float
    median_net_annual_benefit_sar: float
    p5_net_annual_benefit_sar: float
    p25_net_annual_benefit_sar: float
    p50_net_annual_benefit_sar: float
    p75_net_annual_benefit_sar: float
    p95_net_annual_benefit_sar: float
    min_net_annual_benefit_sar: float
    max_net_annual_benefit_sar: float
    p5_energy_gain_vs_baseline_kwh: float
    p25_energy_gain_vs_baseline_kwh: float
    p50_energy_gain_vs_baseline_kwh: float
    p75_energy_gain_vs_baseline_kwh: float
    p95_energy_gain_vs_baseline_kwh: float
    win_probability: float

    def to_record(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "trial_count": self.trial_count,
            "mean_net_annual_benefit_sar": self.mean_net_annual_benefit_sar,
            "std_net_annual_benefit_sar": self.std_net_annual_benefit_sar,
            "median_net_annual_benefit_sar": self.median_net_annual_benefit_sar,
            "p5_net_annual_benefit_sar": self.p5_net_annual_benefit_sar,
            "p25_net_annual_benefit_sar": self.p25_net_annual_benefit_sar,
            "p50_net_annual_benefit_sar": self.p50_net_annual_benefit_sar,
            "p75_net_annual_benefit_sar": self.p75_net_annual_benefit_sar,
            "p95_net_annual_benefit_sar": self.p95_net_annual_benefit_sar,
            "min_net_annual_benefit_sar": self.min_net_annual_benefit_sar,
            "max_net_annual_benefit_sar": self.max_net_annual_benefit_sar,
            "p5_energy_gain_vs_baseline_kwh": self.p5_energy_gain_vs_baseline_kwh,
            "p25_energy_gain_vs_baseline_kwh": self.p25_energy_gain_vs_baseline_kwh,
            "p50_energy_gain_vs_baseline_kwh": self.p50_energy_gain_vs_baseline_kwh,
            "p75_energy_gain_vs_baseline_kwh": self.p75_energy_gain_vs_baseline_kwh,
            "p95_energy_gain_vs_baseline_kwh": self.p95_energy_gain_vs_baseline_kwh,
            "win_probability": self.win_probability,
        }


@dataclass(frozen=True)
class MonteCarloResult:
    run_id: str
    output_directory: Path
    base_seed: int
    trial_count: int
    reconciled_trial_count: int
    failed_trial_count: int
    trials: tuple[MonteCarloTrialRecord, ...]
    scenario_summaries: Mapping[str, ScenarioMonteCarloSummary]
    central_t6_winner: str | None
    central_t6_reconciled: bool
    central_t6_failed_reconciliation_checks: tuple[Mapping[str, object], ...]
    majority_trial_winner: str | None
    uncertainty_mode: UncertaintyMode
    output_artifacts: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "base_seed": self.base_seed,
            "uncertainty_mode": self.uncertainty_mode,
            "sampled_parameter_uncertainty": self.uncertainty_mode == "parameters_and_seed",
            "seed_only": self.uncertainty_mode == "stochastic_seed_only",
            "trial_count": self.trial_count,
            "reconciled_trial_count": self.reconciled_trial_count,
            "failed_trial_count": self.failed_trial_count,
            "central_t6_winner": self.central_t6_winner,
            "central_t6_reconciled": self.central_t6_reconciled,
            "central_t6_failed_reconciliation_checks": _check_records(
                self.central_t6_failed_reconciliation_checks
            ),
            "majority_trial_winner": self.majority_trial_winner,
            "failed_trials": [trial.to_record() for trial in self.trials if not trial.reconciled],
            "scenario_summaries": {
                scenario_id: summary.to_record()
                for scenario_id, summary in self.scenario_summaries.items()
            },
        }


@dataclass(frozen=True)
class MonteCarloExperimentOutcome:
    output_directory: Path
    result: MonteCarloResult


class MonteCarloExperiment:
    """Run the T6 comparison across many seeded trials and summarize the outcome spread."""

    def __init__(
        self,
        config: SolarCleanConfig,
        *,
        trial_count: int = DEFAULT_TRIAL_COUNT,
        base_seed: int | None = None,
        scenario_order: Sequence[str] | None = None,
        parameter_registry_path: Path | None = None,
        uncertainty_mode: UncertaintyMode = DEFAULT_UNCERTAINTY_MODE,
        write_artifacts: bool = True,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        if trial_count < 2:
            raise ValueError("trial_count must be at least 2 to compute a spread")
        if uncertainty_mode not in ("stochastic_seed_only", "parameters_and_seed"):
            raise ValueError(f"unsupported uncertainty_mode: {uncertainty_mode}")
        self.config = config
        self.trial_count = trial_count
        self.base_seed = base_seed if base_seed is not None else config.soiling.random_seed
        self.scenario_order = scenario_order
        self.parameter_registry_path = (
            parameter_registry_path or config.calibration.parameter_registry_path
        )
        self.uncertainty_mode = uncertainty_mode
        self.write_artifacts = write_artifacts
        # Trial-level progress reporting for callers such as the dashboard.
        # One unit = the central comparison or one seeded trial; observational only.
        self.progress_callback = progress_callback

    def trial_seeds(self) -> tuple[int, ...]:
        # A fixed base_seed always produces the same trial seeds, independent of everything
        # else about the run -- this is what makes the experiment reproducible.
        rng = random.Random(self.base_seed)
        return tuple(rng.randrange(1, 2**31 - 1) for _ in range(self.trial_count))

    def _report_progress(self, done: int, total: int, stage: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(done, total, stage)

    def run(self) -> MonteCarloExperimentOutcome:
        total_units = 1 + self.trial_count  # central comparison + each seeded trial
        self._report_progress(0, total_units, "Running central comparison")
        weather = _load_weather(self.config)
        clean_energy = PVWattsPowerModel().calculate_hourly(weather, self.config.pv_system)
        registry = ParameterRegistry.from_yaml(self.parameter_registry_path)
        parameter_catalog: tuple[ParameterOverrideSpec, ...] = ()
        if self.uncertainty_mode == "parameters_and_seed":
            parameter_catalog, _ = build_parameter_catalog(registry)
        central_comparison = (
            CompareAllScenarios(
                self.config,
                weather=weather,
                clean_energy=clean_energy,
                scenario_order=self.scenario_order,
                parameter_registry_path=self.parameter_registry_path,
                parameter_registry=registry,
                write_artifacts=False,
            )
            .run()
            .comparison
        )
        central_reconciled = (
            central_comparison.reconciliation_report.passed
            and central_comparison.recommendation.calculation_valid
        )
        central_t6_winner = central_comparison.recommendation.winner if central_reconciled else None
        central_failed_checks = _failed_reconciliation_checks(central_comparison)

        seeds = self.trial_seeds()
        trial_list = []
        for index, seed in enumerate(seeds):
            self._report_progress(
                1 + index, total_units, f"Running trial {index + 1} of {self.trial_count}"
            )
            trial_list.append(
                self._run_trial(
                    trial_index=index,
                    seed=seed,
                    weather=weather,
                    clean_energy=clean_energy,
                    registry=registry,
                    parameter_catalog=parameter_catalog,
                )
            )
        self._report_progress(total_units, total_units, "Trials complete; summarizing")
        trials = tuple(trial_list)
        reconciled_trials = tuple(trial for trial in trials if trial.reconciled)
        failed_count = len(trials) - len(reconciled_trials)

        scenario_summaries = {
            scenario_id: _summarize_scenario(scenario_id, trials, reconciled_trials)
            for scenario_id in CANONICAL_SCENARIO_IDS
        }
        majority_trial_winner = _majority_winner(reconciled_trials)

        writer = OutputWriter(self.config)
        if self.write_artifacts:
            output_dir = writer.create_run_directory("monte-carlo")
        else:
            output_dir = self.config.output.base_directory / writer.build_run_id("monte-carlo")
        run_id = output_dir.name

        result = MonteCarloResult(
            run_id=run_id,
            output_directory=output_dir,
            base_seed=self.base_seed,
            trial_count=len(trials),
            reconciled_trial_count=len(reconciled_trials),
            failed_trial_count=failed_count,
            trials=trials,
            scenario_summaries=MappingProxyType(scenario_summaries),
            central_t6_winner=central_t6_winner,
            central_t6_reconciled=central_reconciled,
            central_t6_failed_reconciliation_checks=central_failed_checks,
            majority_trial_winner=majority_trial_winner,
            uncertainty_mode=self.uncertainty_mode,
            output_artifacts=(),
        )

        artifacts: tuple[str, ...] = ()
        if self.write_artifacts:
            artifacts = _write_monte_carlo_package(
                output_dir=output_dir, writer=writer, config=self.config, result=result
            )
            result = _replace_artifacts(result, artifacts)
        return MonteCarloExperimentOutcome(output_directory=output_dir, result=result)

    def _run_trial(
        self,
        *,
        trial_index: int,
        seed: int,
        weather: WeatherDataset,
        clean_energy: CleanEnergyProfile,
        registry: ParameterRegistry,
        parameter_catalog: tuple[ParameterOverrideSpec, ...],
    ) -> MonteCarloTrialRecord:
        trial_config = self.config
        trial_registry = registry
        sampled_parameters: dict[str, float] = {}
        if self.uncertainty_mode == "parameters_and_seed":
            parameter_rng = random.Random(f"{self.base_seed}-params-{trial_index}")
            for spec in parameter_catalog:
                value = _sample_parameter(parameter_rng, spec)
                sampled_parameters[spec.name] = value
                trial_config, trial_registry = _apply_parameter_override(
                    config=trial_config,
                    registry=trial_registry,
                    spec=spec,
                    value=value,
                )
        trial_config = trial_config.model_copy(
            update={"soiling": trial_config.soiling.model_copy(update={"random_seed": seed})}
        )
        comparison = (
            CompareAllScenarios(
                trial_config,
                weather=weather,
                clean_energy=clean_energy,
                scenario_order=self.scenario_order,
                parameter_registry_path=self.parameter_registry_path,
                parameter_registry=trial_registry,
                write_artifacts=False,
            )
            .run()
            .comparison
        )

        net_benefit = {
            scenario_id: comparison.economic_results[scenario_id].net_annual_benefit_sar
            for scenario_id in CANONICAL_SCENARIO_IDS
        }
        actual_energy = {
            scenario_id: comparison.scenario_results[scenario_id].annual_actual_energy_kwh
            for scenario_id in CANONICAL_SCENARIO_IDS
        }
        energy_gain = {
            scenario_id: _as_float(
                comparison.energy_gain_vs_baseline[scenario_id]["energy_gain_vs_baseline_kwh"]
            )
            for scenario_id in CANONICAL_SCENARIO_IDS
        }
        reconciled = (
            comparison.reconciliation_report.passed and comparison.recommendation.calculation_valid
        )
        winner = comparison.recommendation.winner if reconciled else None
        if reconciled and self.uncertainty_mode == "parameters_and_seed":
            winner = _unique_net_benefit_winner(net_benefit)
        return MonteCarloTrialRecord(
            trial_index=trial_index,
            seed=seed,
            reconciled=reconciled,
            winner=winner,
            net_annual_benefit_sar=MappingProxyType(net_benefit),
            annual_actual_energy_kwh=MappingProxyType(actual_energy),
            energy_gain_vs_baseline_kwh=MappingProxyType(energy_gain),
            failed_reconciliation_checks=_failed_reconciliation_checks(comparison),
            sampled_parameters=MappingProxyType(sampled_parameters),
        )


def _sample_parameter(rng: random.Random, spec: ParameterOverrideSpec) -> float:
    if spec.low_value == spec.high_value:
        return spec.central_value
    return rng.triangular(spec.low_value, spec.high_value, spec.central_value)


def _apply_parameter_override(
    *,
    config: SolarCleanConfig,
    registry: ParameterRegistry,
    spec: ParameterOverrideSpec,
    value: float,
) -> tuple[SolarCleanConfig, ParameterRegistry]:
    return apply_parameter_override(
        config=config,
        registry=registry,
        spec=spec,
        value=value,
    )


def _unique_net_benefit_winner(net_benefit: Mapping[str, float]) -> str | None:
    highest = max(net_benefit.values())
    winners = [scenario_id for scenario_id, value in net_benefit.items() if value == highest]
    return winners[0] if len(winners) == 1 else None


def _as_float(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    raise TypeError(f"expected a numeric value, got {type(value).__name__}: {value!r}")


def _summarize_scenario(
    scenario_id: str,
    all_trials: tuple[MonteCarloTrialRecord, ...],
    reconciled_trials: tuple[MonteCarloTrialRecord, ...],
) -> ScenarioMonteCarloSummary:
    values = [trial.net_annual_benefit_sar[scenario_id] for trial in reconciled_trials]
    energy_gains = [trial.energy_gain_vs_baseline_kwh[scenario_id] for trial in reconciled_trials]
    if not values:
        return ScenarioMonteCarloSummary(
            scenario_id=scenario_id,
            trial_count=0,
            mean_net_annual_benefit_sar=0.0,
            std_net_annual_benefit_sar=0.0,
            median_net_annual_benefit_sar=0.0,
            p5_net_annual_benefit_sar=0.0,
            p25_net_annual_benefit_sar=0.0,
            p50_net_annual_benefit_sar=0.0,
            p75_net_annual_benefit_sar=0.0,
            p95_net_annual_benefit_sar=0.0,
            min_net_annual_benefit_sar=0.0,
            max_net_annual_benefit_sar=0.0,
            p5_energy_gain_vs_baseline_kwh=0.0,
            p25_energy_gain_vs_baseline_kwh=0.0,
            p50_energy_gain_vs_baseline_kwh=0.0,
            p75_energy_gain_vs_baseline_kwh=0.0,
            p95_energy_gain_vs_baseline_kwh=0.0,
            win_probability=0.0,
        )
    wins = sum(1 for trial in reconciled_trials if trial.winner == scenario_id)
    return ScenarioMonteCarloSummary(
        scenario_id=scenario_id,
        trial_count=len(values),
        mean_net_annual_benefit_sar=statistics.fmean(values),
        std_net_annual_benefit_sar=statistics.stdev(values) if len(values) > 1 else 0.0,
        median_net_annual_benefit_sar=statistics.median(values),
        p5_net_annual_benefit_sar=_percentile(values, 0.05),
        p25_net_annual_benefit_sar=_percentile(values, 0.25),
        p50_net_annual_benefit_sar=_percentile(values, 0.50),
        p75_net_annual_benefit_sar=_percentile(values, 0.75),
        p95_net_annual_benefit_sar=_percentile(values, 0.95),
        min_net_annual_benefit_sar=min(values),
        max_net_annual_benefit_sar=max(values),
        p5_energy_gain_vs_baseline_kwh=_percentile(energy_gains, 0.05),
        p25_energy_gain_vs_baseline_kwh=_percentile(energy_gains, 0.25),
        p50_energy_gain_vs_baseline_kwh=_percentile(energy_gains, 0.50),
        p75_energy_gain_vs_baseline_kwh=_percentile(energy_gains, 0.75),
        p95_energy_gain_vs_baseline_kwh=_percentile(energy_gains, 0.95),
        win_probability=wins / len(reconciled_trials),
    )


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _majority_winner(reconciled_trials: tuple[MonteCarloTrialRecord, ...]) -> str | None:
    if not reconciled_trials:
        return None
    tally: dict[str, int] = {scenario_id: 0 for scenario_id in CANONICAL_SCENARIO_IDS}
    for trial in reconciled_trials:
        if trial.winner is not None:
            tally[trial.winner] += 1
    highest = max(tally.values())
    leaders = [scenario_id for scenario_id, wins in tally.items() if wins == highest]
    if highest <= len(reconciled_trials) / 2 or len(leaders) != 1:
        return None
    return leaders[0]


def _replace_artifacts(result: MonteCarloResult, artifacts: tuple[str, ...]) -> MonteCarloResult:
    return MonteCarloResult(
        run_id=result.run_id,
        output_directory=result.output_directory,
        base_seed=result.base_seed,
        trial_count=result.trial_count,
        reconciled_trial_count=result.reconciled_trial_count,
        failed_trial_count=result.failed_trial_count,
        trials=result.trials,
        scenario_summaries=result.scenario_summaries,
        central_t6_winner=result.central_t6_winner,
        central_t6_reconciled=result.central_t6_reconciled,
        central_t6_failed_reconciliation_checks=result.central_t6_failed_reconciliation_checks,
        majority_trial_winner=result.majority_trial_winner,
        uncertainty_mode=result.uncertainty_mode,
        output_artifacts=artifacts,
    )


def _write_monte_carlo_package(
    *,
    output_dir: Path,
    writer: OutputWriter,
    config: SolarCleanConfig,
    result: MonteCarloResult,
) -> tuple[str, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[str] = []

    writer.write_config(output_dir)
    artifacts.append("config_resolved.yaml")

    trials_frame = pd.DataFrame.from_records([trial.to_flat_record() for trial in result.trials])
    trials_frame.to_csv(
        output_dir / "monte_carlo_trials.csv",
        index=False,
        float_format=config.output.csv_float_format,
    )
    artifacts.append("monte_carlo_trials.csv")

    if result.uncertainty_mode == "parameters_and_seed":
        parameter_samples_frame = pd.DataFrame.from_records(
            [_parameter_sample_record(trial) for trial in result.trials]
        )
        parameter_samples_frame.to_csv(
            output_dir / "monte_carlo_parameter_samples.csv",
            index=False,
            float_format=config.output.csv_float_format,
        )
        artifacts.append("monte_carlo_parameter_samples.csv")

    write_json_report(output_dir / "monte_carlo_summary.json", result.to_record())
    artifacts.append("monte_carlo_summary.json")

    if result.uncertainty_mode == "stochastic_seed_only":
        plot_paths = write_monte_carlo_plots(output_dir=output_dir, trials_frame=trials_frame)
        artifacts.extend(path.name for path in plot_paths)

    summary: dict[str, object] = {
        "command": "monte-carlo",
        "run_id": result.run_id,
        "uncertainty_mode": result.uncertainty_mode,
        "sampled_parameter_uncertainty": result.uncertainty_mode == "parameters_and_seed",
        "trial_count": result.trial_count,
        "reconciled_trial_count": result.reconciled_trial_count,
        "failed_trial_count": result.failed_trial_count,
        "central_t6_winner": result.central_t6_winner,
        "central_t6_reconciled": result.central_t6_reconciled,
        "central_t6_failed_reconciliation_check_names": list(
            _failed_check_names(result.central_t6_failed_reconciliation_checks)
        ),
        "majority_trial_winner": result.majority_trial_winner,
        "output_artifacts": list(artifacts),
    }
    writer.write_summary(output_dir, summary)
    writer.write_text_summary(output_dir, summary)
    artifacts.extend(["summary.json", "summary.txt"])
    return tuple(artifacts)


def _parameter_sample_record(trial: MonteCarloTrialRecord) -> dict[str, object]:
    record: dict[str, object] = {
        "trial_index": trial.trial_index,
        **trial.sampled_parameters,
    }
    for scenario_id in CANONICAL_SCENARIO_IDS:
        record[f"{scenario_id}_net_annual_benefit_sar"] = trial.net_annual_benefit_sar[scenario_id]
    record["winner"] = trial.winner
    return record
