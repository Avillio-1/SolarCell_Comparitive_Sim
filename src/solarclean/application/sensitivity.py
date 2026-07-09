"""T7 -- One-way sensitivity, two-way winner maps, and break-even analysis.

All three experiments reuse CompareAllScenarios as a black box (write_artifacts=False per
trial) and perturb exactly one axis of uncertainty at a time using the hand-verified override
catalog in ``domain.calibration.parameter_overrides`` -- never a blind path-walk over the
registry's ``configuration_path`` strings (see that module's docstring for why).

Every parameter range swept comes from the live T5 parameter registry (low_value/central_value/
high_value), never invented here, satisfying the T7 completion criterion that "parameter ranges
come from the shared registry".
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pandas as pd

from solarclean.application.comparison import (
    CANONICAL_SCENARIO_IDS,
    CompareAllScenarios,
    ComparisonResult,
)
from solarclean.config.models import SolarCleanConfig
from solarclean.domain.calibration.parameter_overrides import (
    ParameterOverrideSpec,
    apply_config_override,
    apply_economics_override,
    build_parameter_catalog,
)
from solarclean.domain.calibration.registry import ParameterRegistry
from solarclean.infrastructure.persistence.outputs import OutputWriter
from solarclean.infrastructure.persistence.plots import (
    write_breakeven_plot,
    write_sensitivity_tornado_plot,
    write_winner_map_plot,
)
from solarclean.infrastructure.persistence.reports import write_json_report

DEFAULT_ONE_WAY_STEPS = 5
DEFAULT_GRID_STEPS = 3
DEFAULT_MAX_BREAKEVEN_EVALUATIONS = 24
DEFAULT_BREAKEVEN_RELATIVE_TOLERANCE = 1e-3
DEFAULT_BREAKEVEN_SCAN_POINTS = 9


@dataclass(frozen=True)
class VariantResult:
    net_annual_benefit_sar: Mapping[str, float]
    winner: str | None
    reconciled: bool
    failed_reconciliation_checks: tuple[Mapping[str, object], ...]


def _failed_reconciliation_checks(
    comparison: ComparisonResult,
) -> tuple[Mapping[str, object], ...]:
    failed = [
        MappingProxyType(check.to_record())
        for check in comparison.reconciliation_report.checks
        if not check.passed
    ]
    if comparison.reconciliation_report.passed and not comparison.recommendation.valid:
        failed.append(
            MappingProxyType(
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
    return [dict(check) for check in checks]


def _sweep_points(spec: ParameterOverrideSpec, steps: int) -> tuple[float, ...]:
    if steps < 2:
        raise ValueError("steps must be at least 2")
    low, central, high = spec.low_value, spec.central_value, spec.high_value
    if low == high:
        return (central,)
    points: set[float] = {low, central, high}
    # Fill in evenly spaced points between low and high (excluding endpoints, already added),
    # so the sweep always includes low/central/high exactly plus intermediate resolution.
    if steps > 3:
        extra = steps - 3
        span = high - low
        for i in range(1, extra + 1):
            points.add(low + span * i / (extra + 1))
    return tuple(sorted(points))


def _apply_override(
    *,
    base_config: SolarCleanConfig,
    base_registry: ParameterRegistry,
    spec: ParameterOverrideSpec,
    value: float,
) -> tuple[SolarCleanConfig, ParameterRegistry]:
    if spec.kind == "config":
        return apply_config_override(base_config, spec, value), base_registry
    return base_config, apply_economics_override(base_registry, spec, value)


def _run_variant(
    *,
    config: SolarCleanConfig,
    registry: ParameterRegistry,
    scenario_order: Sequence[str] | None,
) -> VariantResult:
    comparison = (
        CompareAllScenarios(
            config,
            scenario_order=scenario_order,
            parameter_registry=registry,
            write_artifacts=False,
        )
        .run()
        .comparison
    )
    net_benefit = {
        scenario_id: comparison.economic_results[scenario_id].net_annual_benefit_sar
        for scenario_id in CANONICAL_SCENARIO_IDS
    }
    reconciled = comparison.reconciliation_report.passed and comparison.recommendation.valid
    winner = comparison.recommendation.winner if reconciled else None
    return VariantResult(
        net_annual_benefit_sar=MappingProxyType(net_benefit),
        winner=winner,
        reconciled=reconciled,
        failed_reconciliation_checks=_failed_reconciliation_checks(comparison),
    )


@dataclass(frozen=True)
class SweepPoint:
    value: float
    net_annual_benefit_sar: Mapping[str, float]
    winner: str | None
    reconciled: bool
    failed_reconciliation_checks: tuple[Mapping[str, object], ...] = ()

    def to_record(self, parameter_name: str) -> dict[str, object]:
        record: dict[str, object] = {
            "parameter_name": parameter_name,
            "value": self.value,
            "winner": self.winner,
            "reconciled": self.reconciled,
            "failed_reconciliation_check_names": list(
                _failed_check_names(self.failed_reconciliation_checks)
            ),
            "failed_reconciliation_check_messages": list(
                _failed_check_messages(self.failed_reconciliation_checks)
            ),
            "failed_reconciliation_checks": _check_records(self.failed_reconciliation_checks),
        }
        for scenario_id, value in self.net_annual_benefit_sar.items():
            record[f"{scenario_id}_net_annual_benefit_sar"] = value
        return record


@dataclass(frozen=True)
class OneWayParameterResult:
    spec: ParameterOverrideSpec
    points: tuple[SweepPoint, ...]
    winner_changed: bool
    swing_sar: Mapping[str, float]

    def to_record(self) -> dict[str, object]:
        return {
            "parameter_name": self.spec.name,
            "configuration_path": self.spec.configuration_path,
            "category": self.spec.category,
            "unit": self.spec.unit,
            "status": self.spec.status,
            "confidence": self.spec.confidence,
            "low_value": self.spec.low_value,
            "central_value": self.spec.central_value,
            "high_value": self.spec.high_value,
            "winner_changed": self.winner_changed,
            "swing_sar": dict(self.swing_sar),
            "points": [point.to_record(self.spec.name) for point in self.points],
        }


@dataclass(frozen=True)
class OneWaySensitivityResult:
    run_id: str
    output_directory: Path
    base_winner: str | None
    base_reconciled: bool
    base_net_annual_benefit_sar: Mapping[str, float]
    base_failed_reconciliation_checks: tuple[Mapping[str, object], ...]
    parameter_results: tuple[OneWayParameterResult, ...]
    skipped_parameters: tuple[str, ...]
    output_artifacts: tuple[str, ...]

    def ranked_by_swing(self, scenario_id: str | None = None) -> tuple[OneWayParameterResult, ...]:
        """Parameters ordered by how much they can move the outcome (largest swing first).

        This is exactly the ordering a tornado chart needs. If ``scenario_id`` is omitted, uses
        the max swing across all three scenarios.
        """

        def _key(result: OneWayParameterResult) -> float:
            if scenario_id is not None:
                return result.swing_sar.get(scenario_id, 0.0)
            return max(result.swing_sar.values(), default=0.0)

        return tuple(sorted(self.parameter_results, key=_key, reverse=True))

    def to_record(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "base_winner": self.base_winner,
            "base_reconciled": self.base_reconciled,
            "base_net_annual_benefit_sar": dict(self.base_net_annual_benefit_sar),
            "base_failed_reconciliation_checks": _check_records(
                self.base_failed_reconciliation_checks
            ),
            "skipped_parameters": list(self.skipped_parameters),
            "parameters_swept": len(self.parameter_results),
            "parameters_that_flip_the_winner": [
                result.spec.name for result in self.parameter_results if result.winner_changed
            ],
            "parameter_results": [result.to_record() for result in self.parameter_results],
        }


@dataclass(frozen=True)
class OneWaySensitivityOutcome:
    output_directory: Path
    result: OneWaySensitivityResult


class OneWaySensitivityExperiment:
    """Sweep one calibration parameter at a time, holding everything else at its central value."""

    def __init__(
        self,
        config: SolarCleanConfig,
        *,
        parameter_names: Sequence[str] | None = None,
        steps: int = DEFAULT_ONE_WAY_STEPS,
        scenario_order: Sequence[str] | None = None,
        parameter_registry_path: Path | None = None,
        write_artifacts: bool = True,
    ) -> None:
        self.config = config
        self.steps = steps
        self.scenario_order = scenario_order
        self.registry_path = parameter_registry_path or config.calibration.parameter_registry_path
        self.registry = ParameterRegistry.from_yaml(self.registry_path)
        supported, unsupported = build_parameter_catalog(self.registry)
        self._catalog_by_name = {spec.name: spec for spec in supported}
        self._unsupported_names = {entry.name for entry in unsupported}
        if parameter_names is None:
            self.parameter_names: tuple[str, ...] = tuple(self._catalog_by_name)
        else:
            self.parameter_names = tuple(parameter_names)
        self.write_artifacts = write_artifacts

    def run(self) -> OneWaySensitivityOutcome:
        base_variant = _run_variant(
            config=self.config, registry=self.registry, scenario_order=self.scenario_order
        )

        results: list[OneWayParameterResult] = []
        skipped: list[str] = []
        for name in self.parameter_names:
            spec = self._catalog_by_name.get(name)
            if spec is None:
                skipped.append(name)
                continue
            results.append(self._sweep_parameter(spec, base_variant))

        writer = OutputWriter(self.config)
        if self.write_artifacts:
            output_dir = writer.create_run_directory("sensitivity-oneway")
        else:
            output_dir = self.config.output.base_directory / writer.build_run_id(
                "sensitivity-oneway"
            )
        run_id = output_dir.name

        result = OneWaySensitivityResult(
            run_id=run_id,
            output_directory=output_dir,
            base_winner=base_variant.winner,
            base_reconciled=base_variant.reconciled,
            base_net_annual_benefit_sar=base_variant.net_annual_benefit_sar,
            base_failed_reconciliation_checks=base_variant.failed_reconciliation_checks,
            parameter_results=tuple(results),
            skipped_parameters=tuple(skipped),
            output_artifacts=(),
        )

        artifacts: tuple[str, ...] = ()
        if self.write_artifacts:
            artifacts = _write_oneway_package(output_dir=output_dir, writer=writer, result=result)
            result = OneWaySensitivityResult(
                run_id=result.run_id,
                output_directory=result.output_directory,
                base_winner=result.base_winner,
                base_reconciled=result.base_reconciled,
                base_net_annual_benefit_sar=result.base_net_annual_benefit_sar,
                base_failed_reconciliation_checks=result.base_failed_reconciliation_checks,
                parameter_results=result.parameter_results,
                skipped_parameters=result.skipped_parameters,
                output_artifacts=artifacts,
            )
        return OneWaySensitivityOutcome(output_directory=output_dir, result=result)

    def _sweep_parameter(
        self, spec: ParameterOverrideSpec, base_variant: VariantResult
    ) -> OneWayParameterResult:
        points: list[SweepPoint] = []
        for value in _sweep_points(spec, self.steps):
            config, registry = _apply_override(
                base_config=self.config, base_registry=self.registry, spec=spec, value=value
            )
            variant = _run_variant(
                config=config, registry=registry, scenario_order=self.scenario_order
            )
            points.append(
                SweepPoint(
                    value=value,
                    net_annual_benefit_sar=variant.net_annual_benefit_sar,
                    winner=variant.winner,
                    reconciled=variant.reconciled,
                    failed_reconciliation_checks=variant.failed_reconciliation_checks,
                )
            )
        winner_changed = any(
            base_variant.reconciled and point.reconciled and point.winner != base_variant.winner
            for point in points
        )
        reconciled_points = tuple(point for point in points if point.reconciled)
        swing = {
            scenario_id: _net_benefit_swing(reconciled_points, scenario_id)
            for scenario_id in CANONICAL_SCENARIO_IDS
        }
        return OneWayParameterResult(
            spec=spec, points=tuple(points), winner_changed=winner_changed, swing_sar=swing
        )


def _net_benefit_swing(points: Sequence[SweepPoint], scenario_id: str) -> float:
    if not points:
        return 0.0
    return max(point.net_annual_benefit_sar[scenario_id] for point in points) - min(
        point.net_annual_benefit_sar[scenario_id] for point in points
    )


def _write_oneway_package(
    *, output_dir: Path, writer: OutputWriter, result: OneWaySensitivityResult
) -> tuple[str, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[str] = []
    writer.write_config(output_dir)
    artifacts.append("config_resolved.yaml")

    records = [
        point.to_record(param_result.spec.name)
        for param_result in result.parameter_results
        for point in param_result.points
    ]
    frame = pd.DataFrame.from_records(records)
    frame.to_csv(output_dir / "sensitivity_oneway.csv", index=False)
    artifacts.append("sensitivity_oneway.csv")

    write_json_report(output_dir / "sensitivity_oneway_summary.json", result.to_record())
    artifacts.append("sensitivity_oneway_summary.json")

    if result.parameter_results:
        plot_path = output_dir / "sensitivity_tornado.png"
        focus_scenario = result.base_winner or "baseline"
        ranked = result.ranked_by_swing(focus_scenario)
        tornado_frame = pd.DataFrame.from_records(
            [
                {
                    "parameter_name": r.spec.name,
                    "min_benefit_sar": min(
                        p.net_annual_benefit_sar[focus_scenario] for p in r.points if p.reconciled
                    ),
                    "max_benefit_sar": max(
                        p.net_annual_benefit_sar[focus_scenario] for p in r.points if p.reconciled
                    ),
                }
                for r in ranked
                if any(p.reconciled for p in r.points)
            ]
        )
        write_sensitivity_tornado_plot(plot_path, tornado_frame, focus_scenario=focus_scenario)
        artifacts.append(plot_path.name)

    summary: dict[str, object] = {
        "command": "sensitivity-oneway",
        "run_id": result.run_id,
        "base_winner": result.base_winner,
        "base_reconciled": result.base_reconciled,
        "base_failed_reconciliation_check_names": list(
            _failed_check_names(result.base_failed_reconciliation_checks)
        ),
        "parameters_swept": len(result.parameter_results),
        "parameters_that_flip_the_winner": [
            r.spec.name for r in result.parameter_results if r.winner_changed
        ],
        "skipped_parameters": list(result.skipped_parameters),
        "output_artifacts": list(artifacts),
    }
    writer.write_summary(output_dir, summary)
    writer.write_text_summary(output_dir, summary)
    artifacts.extend(["summary.json", "summary.txt"])
    return tuple(artifacts)


@dataclass(frozen=True)
class WinnerMapGridPoint:
    value_a: float
    value_b: float
    winner: str | None
    reconciled: bool
    net_annual_benefit_sar: Mapping[str, float]
    failed_reconciliation_checks: tuple[Mapping[str, object], ...] = ()

    def to_record(self, name_a: str, name_b: str) -> dict[str, object]:
        record: dict[str, object] = {
            f"{name_a}_value": self.value_a,
            f"{name_b}_value": self.value_b,
            "winner": self.winner,
            "reconciled": self.reconciled,
            "failed_reconciliation_check_names": list(
                _failed_check_names(self.failed_reconciliation_checks)
            ),
            "failed_reconciliation_check_messages": list(
                _failed_check_messages(self.failed_reconciliation_checks)
            ),
            "failed_reconciliation_checks": _check_records(self.failed_reconciliation_checks),
        }
        for scenario_id, value in self.net_annual_benefit_sar.items():
            record[f"{scenario_id}_net_annual_benefit_sar"] = value
        return record


@dataclass(frozen=True)
class TwoWaySensitivityResult:
    run_id: str
    output_directory: Path
    parameter_a: str
    parameter_b: str
    grid: tuple[WinnerMapGridPoint, ...]
    output_artifacts: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "parameter_a": self.parameter_a,
            "parameter_b": self.parameter_b,
            "grid_points": len(self.grid),
            "failed_grid_point_count": sum(1 for point in self.grid if not point.reconciled),
            "grid": [point.to_record(self.parameter_a, self.parameter_b) for point in self.grid],
        }


@dataclass(frozen=True)
class TwoWaySensitivityOutcome:
    output_directory: Path
    result: TwoWaySensitivityResult


class TwoWaySensitivityExperiment:
    """Grid two parameters together to map which scenario wins across their joint range.

    Grid resolution is deliberately opt-in and explicit (both parameter names and grid size
    must be requested by the caller) rather than auto-selected, per the T7 plan's own risk
    note: two-way maps are the most expensive experiment (grid_steps^2 full comparison runs)
    and should only be run once one-way sensitivity has identified which parameters are worth
    the cost.
    """

    def __init__(
        self,
        config: SolarCleanConfig,
        *,
        parameter_name_a: str,
        parameter_name_b: str,
        grid_steps: int = DEFAULT_GRID_STEPS,
        scenario_order: Sequence[str] | None = None,
        parameter_registry_path: Path | None = None,
        write_artifacts: bool = True,
    ) -> None:
        if parameter_name_a == parameter_name_b:
            raise ValueError("parameter_name_a and parameter_name_b must differ")
        self.config = config
        self.grid_steps = grid_steps
        self.scenario_order = scenario_order
        self.registry_path = parameter_registry_path or config.calibration.parameter_registry_path
        self.registry = ParameterRegistry.from_yaml(self.registry_path)
        supported, _ = build_parameter_catalog(self.registry)
        catalog = {spec.name: spec for spec in supported}
        for name in (parameter_name_a, parameter_name_b):
            if name not in catalog:
                raise ValueError(
                    f"{name!r} is not a T7-supported sensitivity parameter "
                    "(see domain.calibration.parameter_overrides.build_parameter_catalog)"
                )
        self.spec_a = catalog[parameter_name_a]
        self.spec_b = catalog[parameter_name_b]
        self.write_artifacts = write_artifacts

    def run(self) -> TwoWaySensitivityOutcome:
        values_a = _sweep_points(self.spec_a, self.grid_steps)
        values_b = _sweep_points(self.spec_b, self.grid_steps)
        grid: list[WinnerMapGridPoint] = []
        for value_a in values_a:
            config_a, registry_a = _apply_override(
                base_config=self.config,
                base_registry=self.registry,
                spec=self.spec_a,
                value=value_a,
            )
            for value_b in values_b:
                config_ab, registry_ab = _apply_override(
                    base_config=config_a, base_registry=registry_a, spec=self.spec_b, value=value_b
                )
                variant = _run_variant(
                    config=config_ab, registry=registry_ab, scenario_order=self.scenario_order
                )
                grid.append(
                    WinnerMapGridPoint(
                        value_a=value_a,
                        value_b=value_b,
                        winner=variant.winner,
                        reconciled=variant.reconciled,
                        net_annual_benefit_sar=variant.net_annual_benefit_sar,
                        failed_reconciliation_checks=variant.failed_reconciliation_checks,
                    )
                )

        writer = OutputWriter(self.config)
        if self.write_artifacts:
            output_dir = writer.create_run_directory("sensitivity-winner-map")
        else:
            output_dir = self.config.output.base_directory / writer.build_run_id(
                "sensitivity-winner-map"
            )
        run_id = output_dir.name

        result = TwoWaySensitivityResult(
            run_id=run_id,
            output_directory=output_dir,
            parameter_a=self.spec_a.name,
            parameter_b=self.spec_b.name,
            grid=tuple(grid),
            output_artifacts=(),
        )
        artifacts: tuple[str, ...] = ()
        if self.write_artifacts:
            artifacts = _write_winner_map_package(
                output_dir=output_dir, writer=writer, result=result
            )
            result = TwoWaySensitivityResult(
                run_id=result.run_id,
                output_directory=result.output_directory,
                parameter_a=result.parameter_a,
                parameter_b=result.parameter_b,
                grid=result.grid,
                output_artifacts=artifacts,
            )
        return TwoWaySensitivityOutcome(output_directory=output_dir, result=result)


def _write_winner_map_package(
    *, output_dir: Path, writer: OutputWriter, result: TwoWaySensitivityResult
) -> tuple[str, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[str] = []
    writer.write_config(output_dir)
    artifacts.append("config_resolved.yaml")

    frame = pd.DataFrame.from_records(
        [point.to_record(result.parameter_a, result.parameter_b) for point in result.grid]
    )
    frame.to_csv(output_dir / "sensitivity_twoway.csv", index=False)
    artifacts.append("sensitivity_twoway.csv")

    write_json_report(output_dir / "sensitivity_twoway_summary.json", result.to_record())
    artifacts.append("sensitivity_twoway_summary.json")

    plot_path = output_dir / _winner_map_plot_filename(
        parameter_a=result.parameter_a,
        parameter_b=result.parameter_b,
    )
    write_winner_map_plot(
        plot_path,
        frame=frame,
        parameter_a=result.parameter_a,
        parameter_b=result.parameter_b,
    )
    artifacts.append(plot_path.name)

    summary: dict[str, object] = {
        "command": "sensitivity-winner-map",
        "run_id": result.run_id,
        "parameter_a": result.parameter_a,
        "parameter_b": result.parameter_b,
        "grid_points": len(result.grid),
        "failed_grid_point_count": sum(1 for point in result.grid if not point.reconciled),
        "output_artifacts": list(artifacts),
    }
    writer.write_summary(output_dir, summary)
    writer.write_text_summary(output_dir, summary)
    artifacts.extend(["summary.json", "summary.txt"])
    return tuple(artifacts)


def _winner_map_plot_filename(*, parameter_a: str, parameter_b: str) -> str:
    digest = hashlib.sha256(f"{parameter_a}|{parameter_b}".encode()).hexdigest()[:10]
    token_a = _short_parameter_token(parameter_a)
    token_b = _short_parameter_token(parameter_b)
    return f"sensitivity_winner_map_{token_a}_{token_b}_{digest}.png"


def _short_parameter_token(name: str) -> str:
    tail = name.rsplit(".", maxsplit=1)[-1]
    safe = re.sub(r"[^A-Za-z0-9]+", "_", tail).strip("_").lower()
    return safe[:28] or "parameter"


@dataclass(frozen=True)
class BreakEvenEvaluation:
    value: float
    margin_sar: float | None
    reconciled: bool
    net_annual_benefit_sar: Mapping[str, float]
    failed_reconciliation_checks: tuple[Mapping[str, object], ...] = ()

    def to_record(self) -> dict[str, object]:
        return {
            "value": self.value,
            "margin_sar": self.margin_sar,
            "reconciled": self.reconciled,
            "net_annual_benefit_sar": dict(self.net_annual_benefit_sar),
            "failed_reconciliation_check_names": list(
                _failed_check_names(self.failed_reconciliation_checks)
            ),
            "failed_reconciliation_check_messages": list(
                _failed_check_messages(self.failed_reconciliation_checks)
            ),
            "failed_reconciliation_checks": _check_records(self.failed_reconciliation_checks),
        }


@dataclass(frozen=True)
class BreakEvenResult:
    run_id: str
    output_directory: Path
    parameter_name: str
    scenario_a: str
    scenario_b: str
    crossover_found: bool
    crossover_value: float | None
    crossover_values: tuple[float, ...]
    crossing_status: str
    likely_non_monotonic: bool
    invalid_evaluation_count: int
    message: str
    evaluations: tuple[BreakEvenEvaluation, ...]
    output_artifacts: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "parameter_name": self.parameter_name,
            "scenario_a": self.scenario_a,
            "scenario_b": self.scenario_b,
            "objective_metric": "net_annual_benefit_sar",
            "crossover_found": self.crossover_found,
            "crossover_value": self.crossover_value,
            "crossover_values": list(self.crossover_values),
            "crossing_status": self.crossing_status,
            "likely_non_monotonic": self.likely_non_monotonic,
            "invalid_evaluation_count": self.invalid_evaluation_count,
            "message": self.message,
            "evaluations": [evaluation.to_record() for evaluation in self.evaluations],
        }


@dataclass(frozen=True)
class _BreakEvenSearchOutcome:
    crossover_values: tuple[float, ...]
    crossing_status: str
    likely_non_monotonic: bool
    message: str
    evaluations: tuple[BreakEvenEvaluation, ...]


@dataclass(frozen=True)
class BreakEvenOutcome:
    output_directory: Path
    result: BreakEvenResult


class BreakEvenExperiment:
    """Find the value of one parameter at which scenario_a and scenario_b tie.

    Searches only within [low_value, high_value] from the T5 registry -- per the T7 plan,
    ranges come from the shared registry rather than being invented here. If net benefit for
    scenario_a stays above (or below) scenario_b's across the entire registry range, that is
    reported explicitly as "no crossover within tested range" rather than extrapolated.
    """

    def __init__(
        self,
        config: SolarCleanConfig,
        *,
        parameter_name: str,
        scenario_a: str,
        scenario_b: str,
        max_evaluations: int = DEFAULT_MAX_BREAKEVEN_EVALUATIONS,
        relative_tolerance: float = DEFAULT_BREAKEVEN_RELATIVE_TOLERANCE,
        parameter_registry_path: Path | None = None,
        write_artifacts: bool = True,
    ) -> None:
        if scenario_a not in CANONICAL_SCENARIO_IDS or scenario_b not in CANONICAL_SCENARIO_IDS:
            raise ValueError("scenario_a/scenario_b must be baseline, reactive, or coating")
        if scenario_a == scenario_b:
            raise ValueError("scenario_a and scenario_b must differ")
        if max_evaluations < 2:
            raise ValueError("max_evaluations must be at least 2")
        self.config = config
        self.scenario_a = scenario_a
        self.scenario_b = scenario_b
        self.max_evaluations = max_evaluations
        self.relative_tolerance = relative_tolerance
        self.registry_path = parameter_registry_path or config.calibration.parameter_registry_path
        self.registry = ParameterRegistry.from_yaml(self.registry_path)
        supported, _ = build_parameter_catalog(self.registry)
        catalog = {spec.name: spec for spec in supported}
        if parameter_name not in catalog:
            raise ValueError(
                f"{parameter_name!r} is not a T7-supported sensitivity parameter "
                "(see domain.calibration.parameter_overrides.build_parameter_catalog)"
            )
        self.spec = catalog[parameter_name]
        self.write_artifacts = write_artifacts

    def _evaluate(self, value: float) -> BreakEvenEvaluation:
        config, registry = _apply_override(
            base_config=self.config, base_registry=self.registry, spec=self.spec, value=value
        )
        variant = _run_variant(config=config, registry=registry, scenario_order=None)
        margin = None
        if variant.reconciled:
            margin = (
                variant.net_annual_benefit_sar[self.scenario_a]
                - variant.net_annual_benefit_sar[self.scenario_b]
            )
        return BreakEvenEvaluation(
            value=value,
            margin_sar=margin,
            reconciled=variant.reconciled,
            net_annual_benefit_sar=variant.net_annual_benefit_sar,
            failed_reconciliation_checks=variant.failed_reconciliation_checks,
        )

    def _search(self) -> _BreakEvenSearchOutcome:
        evaluations: list[BreakEvenEvaluation] = []

        def evaluate(value: float) -> BreakEvenEvaluation:
            evaluation = self._evaluate(value)
            evaluations.append(evaluation)
            return evaluation

        low, high = self.spec.low_value, self.spec.high_value
        scan_values = _break_even_scan_points(
            low=low,
            central=self.spec.central_value,
            high=high,
            max_evaluations=self.max_evaluations,
        )
        scanned = tuple(evaluate(value) for value in scan_values)
        invalid = tuple(
            evaluation
            for evaluation in scanned
            if not evaluation.reconciled or evaluation.margin_sar is None
        )
        if invalid:
            first_invalid = invalid[0]
            failed_names = ", ".join(
                _failed_check_names(first_invalid.failed_reconciliation_checks)
            )
            message = (
                "Break-even analysis refused because at least one evaluation did not reconcile "
                f"at {self.spec.name}={first_invalid.value:g} {self.spec.unit}."
            )
            if failed_names:
                message += f" Failed checks: {failed_names}."
            return _BreakEvenSearchOutcome(
                crossover_values=(),
                crossing_status="invalid_evaluation",
                likely_non_monotonic=False,
                message=message,
                evaluations=tuple(evaluations),
            )

        likely_non_monotonic = _likely_non_monotonic(scanned)
        exact_roots = tuple(
            evaluation.value for evaluation in scanned if evaluation.margin_sar == 0.0
        )
        brackets = _crossing_brackets(scanned)
        remaining = self.max_evaluations - len(evaluations)
        roots: list[float] = list(exact_roots)
        bisection_invalid: BreakEvenEvaluation | None = None
        for lower, upper in brackets:
            root, remaining, invalid_evaluation = self._bisect_bracket(
                lower=lower,
                upper=upper,
                evaluate=evaluate,
                remaining_evaluations=remaining,
            )
            if invalid_evaluation is not None:
                bisection_invalid = invalid_evaluation
                break
            roots.append(root)
        if bisection_invalid is not None:
            failed_names = ", ".join(
                _failed_check_names(bisection_invalid.failed_reconciliation_checks)
            )
            message = (
                "Break-even analysis refused because bisection encountered an unreconciled "
                f"evaluation at {self.spec.name}={bisection_invalid.value:g} {self.spec.unit}."
            )
            if failed_names:
                message += f" Failed checks: {failed_names}."
            return _BreakEvenSearchOutcome(
                crossover_values=(),
                crossing_status="invalid_evaluation",
                likely_non_monotonic=likely_non_monotonic,
                message=message,
                evaluations=tuple(evaluations),
            )

        crossover_values = tuple(sorted(_dedupe_float_values(roots)))
        if not crossover_values:
            leader = _dominant_scenario(scanned, self.scenario_a, self.scenario_b)
            status = "no_crossing_non_monotonic" if likely_non_monotonic else "no_crossing"
            message = (
                f"No crossover detected within the registry range [{low}, {high}] "
                f"{self.spec.unit}; {leader} wins at all reconciled scan points."
            )
            if likely_non_monotonic:
                message += " The sampled margin is likely non-monotonic."
            return _BreakEvenSearchOutcome(
                crossover_values=(),
                crossing_status=status,
                likely_non_monotonic=likely_non_monotonic,
                message=message,
                evaluations=tuple(evaluations),
            )

        if len(crossover_values) == 1:
            status = "one_crossing_non_monotonic" if likely_non_monotonic else "one_crossing"
            message = (
                f"{self.scenario_a} vs {self.scenario_b} cross at "
                f"{self.spec.name} \u2248 {crossover_values[0]:g} {self.spec.unit} "
                f"on net_annual_benefit_sar."
            )
            if likely_non_monotonic:
                message += " The sampled margin is likely non-monotonic."
            return _BreakEvenSearchOutcome(
                crossover_values=crossover_values,
                crossing_status=status,
                likely_non_monotonic=likely_non_monotonic,
                message=message,
                evaluations=tuple(evaluations),
            )

        message = (
            f"Multiple crossovers detected for {self.scenario_a} vs {self.scenario_b} "
            f"on net_annual_benefit_sar: "
            + ", ".join(f"{value:g} {self.spec.unit}" for value in crossover_values)
            + ". The sampled margin is non-monotonic."
        )
        return _BreakEvenSearchOutcome(
            crossover_values=crossover_values,
            crossing_status="multiple_crossings",
            likely_non_monotonic=True,
            message=message,
            evaluations=tuple(evaluations),
        )

    def _bisect_bracket(
        self,
        *,
        lower: BreakEvenEvaluation,
        upper: BreakEvenEvaluation,
        evaluate: Callable[[float], BreakEvenEvaluation],
        remaining_evaluations: int,
    ) -> tuple[float, int, BreakEvenEvaluation | None]:
        if lower.margin_sar is None or upper.margin_sar is None:
            raise ValueError("break-even bracket endpoints must have margins")
        lo, hi, margin_at_lo = lower.value, upper.value, lower.margin_sar
        remaining = remaining_evaluations
        while remaining > 0:
            mid = (lo + hi) / 2.0
            mid_evaluation = evaluate(mid)
            remaining -= 1
            if not mid_evaluation.reconciled or mid_evaluation.margin_sar is None:
                return mid, remaining, mid_evaluation
            margin_mid = mid_evaluation.margin_sar
            if margin_mid == 0.0:
                return mid, remaining, None
            if (margin_mid > 0) == (margin_at_lo > 0):
                lo, margin_at_lo = mid, margin_mid
            else:
                hi = mid
            span = hi - lo
            reference = max(abs(lo), abs(hi), 1e-9)
            if span / reference < self.relative_tolerance:
                break
        return (lo + hi) / 2.0, remaining, None

    def run(self) -> BreakEvenOutcome:
        search = self._search()
        crossover_value = search.crossover_values[0] if search.crossover_values else None

        writer = OutputWriter(self.config)
        if self.write_artifacts:
            output_dir = writer.create_run_directory("break-even")
        else:
            output_dir = self.config.output.base_directory / writer.build_run_id("break-even")
        run_id = output_dir.name

        result = BreakEvenResult(
            run_id=run_id,
            output_directory=output_dir,
            parameter_name=self.spec.name,
            scenario_a=self.scenario_a,
            scenario_b=self.scenario_b,
            crossover_found=bool(search.crossover_values),
            crossover_value=crossover_value,
            crossover_values=search.crossover_values,
            crossing_status=search.crossing_status,
            likely_non_monotonic=search.likely_non_monotonic,
            invalid_evaluation_count=sum(1 for item in search.evaluations if not item.reconciled),
            message=search.message,
            evaluations=tuple(sorted(search.evaluations, key=lambda e: e.value)),
            output_artifacts=(),
        )
        artifacts: tuple[str, ...] = ()
        if self.write_artifacts:
            artifacts = _write_breakeven_package(
                output_dir=output_dir, writer=writer, result=result
            )
            result = BreakEvenResult(
                run_id=result.run_id,
                output_directory=result.output_directory,
                parameter_name=result.parameter_name,
                scenario_a=result.scenario_a,
                scenario_b=result.scenario_b,
                crossover_found=result.crossover_found,
                crossover_value=result.crossover_value,
                crossover_values=result.crossover_values,
                crossing_status=result.crossing_status,
                likely_non_monotonic=result.likely_non_monotonic,
                invalid_evaluation_count=result.invalid_evaluation_count,
                message=result.message,
                evaluations=result.evaluations,
                output_artifacts=artifacts,
            )
        return BreakEvenOutcome(output_directory=output_dir, result=result)


def _break_even_scan_points(
    *,
    low: float,
    central: float,
    high: float,
    max_evaluations: int,
) -> tuple[float, ...]:
    if low == high:
        return (central,)
    count = max(2, min(DEFAULT_BREAKEVEN_SCAN_POINTS, max_evaluations))
    points = [low + (high - low) * index / (count - 1) for index in range(count)]
    if count >= 3 and low < central < high:
        points[count // 2] = central
    return tuple(sorted(set(points)))


def _crossing_brackets(
    evaluations: Sequence[BreakEvenEvaluation],
) -> tuple[tuple[BreakEvenEvaluation, BreakEvenEvaluation], ...]:
    brackets: list[tuple[BreakEvenEvaluation, BreakEvenEvaluation]] = []
    for lower, upper in zip(evaluations, evaluations[1:], strict=False):
        if lower.margin_sar is None or upper.margin_sar is None:
            continue
        if lower.margin_sar == 0.0 or upper.margin_sar == 0.0:
            continue
        if (lower.margin_sar > 0) != (upper.margin_sar > 0):
            brackets.append((lower, upper))
    return tuple(brackets)


def _likely_non_monotonic(evaluations: Sequence[BreakEvenEvaluation]) -> bool:
    margins = [
        evaluation.margin_sar
        for evaluation in evaluations
        if evaluation.reconciled and evaluation.margin_sar is not None
    ]
    if len(margins) < 3:
        return False
    diffs = [
        right - left
        for left, right in zip(margins, margins[1:], strict=False)
        if abs(right - left) > 1e-9
    ]
    return any(diff > 0 for diff in diffs) and any(diff < 0 for diff in diffs)


def _dominant_scenario(
    evaluations: Sequence[BreakEvenEvaluation],
    scenario_a: str,
    scenario_b: str,
) -> str:
    margins = [
        evaluation.margin_sar for evaluation in evaluations if evaluation.margin_sar is not None
    ]
    if not margins:
        return "neither scenario"
    return scenario_a if sum(margins) >= 0.0 else scenario_b


def _dedupe_float_values(values: Sequence[float]) -> tuple[float, ...]:
    deduped: list[float] = []
    for value in sorted(values):
        if not deduped or abs(value - deduped[-1]) > 1e-9:
            deduped.append(value)
    return tuple(deduped)


def _write_breakeven_package(
    *, output_dir: Path, writer: OutputWriter, result: BreakEvenResult
) -> tuple[str, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[str] = []
    writer.write_config(output_dir)
    artifacts.append("config_resolved.yaml")

    write_json_report(output_dir / "breakeven_report.json", result.to_record())
    artifacts.append("breakeven_report.json")

    plot_path = output_dir / f"breakeven_{result.parameter_name}.png"
    evaluations_frame = pd.DataFrame.from_records([e.to_record() for e in result.evaluations])
    if "margin_sar" in evaluations_frame:
        evaluations_frame["margin_sar"] = pd.to_numeric(
            evaluations_frame["margin_sar"], errors="coerce"
        )
    write_breakeven_plot(
        plot_path,
        frame=evaluations_frame,
        parameter_name=result.parameter_name,
        scenario_a=result.scenario_a,
        scenario_b=result.scenario_b,
        crossover_value=result.crossover_value,
    )
    artifacts.append(plot_path.name)

    summary: dict[str, object] = {
        "command": "break-even",
        "run_id": result.run_id,
        "parameter_name": result.parameter_name,
        "scenario_a": result.scenario_a,
        "scenario_b": result.scenario_b,
        "crossover_found": result.crossover_found,
        "crossover_value": result.crossover_value,
        "crossover_values": list(result.crossover_values),
        "crossing_status": result.crossing_status,
        "likely_non_monotonic": result.likely_non_monotonic,
        "invalid_evaluation_count": result.invalid_evaluation_count,
        "message": result.message,
        "output_artifacts": list(artifacts),
    }
    writer.write_summary(output_dir, summary)
    writer.write_text_summary(output_dir, summary)
    artifacts.extend(["summary.json", "summary.txt"])
    return tuple(artifacts)
