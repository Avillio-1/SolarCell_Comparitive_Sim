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

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pandas as pd

from solarclean.application.comparison import CANONICAL_SCENARIO_IDS, CompareAllScenarios
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
) -> tuple[Mapping[str, float], str | None, bool]:
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
    return MappingProxyType(net_benefit), winner, reconciled


@dataclass(frozen=True)
class SweepPoint:
    value: float
    net_annual_benefit_sar: Mapping[str, float]
    winner: str | None
    reconciled: bool

    def to_record(self, parameter_name: str) -> dict[str, object]:
        record: dict[str, object] = {
            "parameter_name": parameter_name,
            "value": self.value,
            "winner": self.winner,
            "reconciled": self.reconciled,
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
    base_net_annual_benefit_sar: Mapping[str, float]
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
            "base_net_annual_benefit_sar": dict(self.base_net_annual_benefit_sar),
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
        base_net_benefit, base_winner, _ = _run_variant(
            config=self.config, registry=self.registry, scenario_order=self.scenario_order
        )

        results: list[OneWayParameterResult] = []
        skipped: list[str] = []
        for name in self.parameter_names:
            spec = self._catalog_by_name.get(name)
            if spec is None:
                skipped.append(name)
                continue
            results.append(self._sweep_parameter(spec, base_winner))

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
            base_winner=base_winner,
            base_net_annual_benefit_sar=base_net_benefit,
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
                base_net_annual_benefit_sar=result.base_net_annual_benefit_sar,
                parameter_results=result.parameter_results,
                skipped_parameters=result.skipped_parameters,
                output_artifacts=artifacts,
            )
        return OneWaySensitivityOutcome(output_directory=output_dir, result=result)

    def _sweep_parameter(
        self, spec: ParameterOverrideSpec, base_winner: str | None
    ) -> OneWayParameterResult:
        points: list[SweepPoint] = []
        for value in _sweep_points(spec, self.steps):
            config, registry = _apply_override(
                base_config=self.config, base_registry=self.registry, spec=spec, value=value
            )
            net_benefit, winner, reconciled = _run_variant(
                config=config, registry=registry, scenario_order=self.scenario_order
            )
            points.append(
                SweepPoint(
                    value=value,
                    net_annual_benefit_sar=net_benefit,
                    winner=winner,
                    reconciled=reconciled,
                )
            )
        winner_changed = any(point.reconciled and point.winner != base_winner for point in points)
        swing = {
            scenario_id: (
                max(point.net_annual_benefit_sar[scenario_id] for point in points)
                - min(point.net_annual_benefit_sar[scenario_id] for point in points)
            )
            for scenario_id in CANONICAL_SCENARIO_IDS
        }
        return OneWayParameterResult(
            spec=spec, points=tuple(points), winner_changed=winner_changed, swing_sar=swing
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
                        p.net_annual_benefit_sar[focus_scenario] for p in r.points
                    ),
                    "max_benefit_sar": max(
                        p.net_annual_benefit_sar[focus_scenario] for p in r.points
                    ),
                }
                for r in ranked
            ]
        )
        write_sensitivity_tornado_plot(plot_path, tornado_frame, focus_scenario=focus_scenario)
        artifacts.append(plot_path.name)

    summary: dict[str, object] = {
        "command": "sensitivity-oneway",
        "run_id": result.run_id,
        "base_winner": result.base_winner,
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

    def to_record(self, name_a: str, name_b: str) -> dict[str, object]:
        record: dict[str, object] = {
            f"{name_a}_value": self.value_a,
            f"{name_b}_value": self.value_b,
            "winner": self.winner,
            "reconciled": self.reconciled,
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
                net_benefit, winner, reconciled = _run_variant(
                    config=config_ab, registry=registry_ab, scenario_order=self.scenario_order
                )
                grid.append(
                    WinnerMapGridPoint(
                        value_a=value_a,
                        value_b=value_b,
                        winner=winner,
                        reconciled=reconciled,
                        net_annual_benefit_sar=net_benefit,
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

    plot_path = output_dir / f"sensitivity_winner_map_{result.parameter_a}_{result.parameter_b}.png"
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
        "output_artifacts": list(artifacts),
    }
    writer.write_summary(output_dir, summary)
    writer.write_text_summary(output_dir, summary)
    artifacts.extend(["summary.json", "summary.txt"])
    return tuple(artifacts)


@dataclass(frozen=True)
class BreakEvenEvaluation:
    value: float
    margin_sar: float

    def to_record(self) -> dict[str, object]:
        return {"value": self.value, "margin_sar": self.margin_sar}


@dataclass(frozen=True)
class BreakEvenResult:
    run_id: str
    output_directory: Path
    parameter_name: str
    scenario_a: str
    scenario_b: str
    crossover_found: bool
    crossover_value: float | None
    message: str
    evaluations: tuple[BreakEvenEvaluation, ...]
    output_artifacts: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "parameter_name": self.parameter_name,
            "scenario_a": self.scenario_a,
            "scenario_b": self.scenario_b,
            "crossover_found": self.crossover_found,
            "crossover_value": self.crossover_value,
            "message": self.message,
            "evaluations": [evaluation.to_record() for evaluation in self.evaluations],
        }


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

    def _margin(self, value: float) -> float:
        config, registry = _apply_override(
            base_config=self.config, base_registry=self.registry, spec=self.spec, value=value
        )
        net_benefit, _, _ = _run_variant(config=config, registry=registry, scenario_order=None)
        return net_benefit[self.scenario_a] - net_benefit[self.scenario_b]

    def _search(self) -> tuple[bool, float | None, str, list[BreakEvenEvaluation]]:
        evaluations: list[BreakEvenEvaluation] = []

        def evaluate(value: float) -> float:
            margin = self._margin(value)
            evaluations.append(BreakEvenEvaluation(value=value, margin_sar=margin))
            return margin

        low, high = self.spec.low_value, self.spec.high_value
        margin_low = evaluate(low)
        margin_high = evaluate(high)

        if margin_low == 0.0:
            message = f"{self.scenario_a} and {self.scenario_b} tie exactly at the low bound."
            return True, low, message, evaluations
        if margin_high == 0.0:
            message = f"{self.scenario_a} and {self.scenario_b} tie exactly at the high bound."
            return True, high, message, evaluations
        if (margin_low > 0) == (margin_high > 0):
            leader = self.scenario_a if margin_low > 0 else self.scenario_b
            message = (
                f"No crossover within the registry range [{low}, {high}] {self.spec.unit}: "
                f"{leader} wins across the entire tested range."
            )
            return False, None, message, evaluations

        crossover_value = self._bisect(
            low=low, high=high, margin_at_low=margin_low, evaluate=evaluate
        )
        message = (
            f"{self.scenario_a} vs {self.scenario_b} cross at "
            f"{self.spec.name} \u2248 {crossover_value:g} {self.spec.unit} "
            f"(searched within registry range [{low}, {high}])."
        )
        return True, crossover_value, message, evaluations

    def _bisect(
        self,
        *,
        low: float,
        high: float,
        margin_at_low: float,
        evaluate: Callable[[float], float],
    ) -> float:
        lo, hi, margin_at_lo = low, high, margin_at_low
        remaining = self.max_evaluations - 2
        while remaining > 0:
            mid = (lo + hi) / 2.0
            margin_mid = evaluate(mid)
            remaining -= 1
            if margin_mid == 0.0:
                return mid
            if (margin_mid > 0) == (margin_at_lo > 0):
                lo, margin_at_lo = mid, margin_mid
            else:
                hi = mid
            span = hi - lo
            reference = max(abs(lo), abs(hi), 1e-9)
            if span / reference < self.relative_tolerance:
                break
        return (lo + hi) / 2.0

    def run(self) -> BreakEvenOutcome:
        crossover_found, crossover_value, message, evaluations = self._search()

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
            crossover_found=crossover_found,
            crossover_value=crossover_value,
            message=message,
            evaluations=tuple(sorted(evaluations, key=lambda e: e.value)),
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
                message=result.message,
                evaluations=result.evaluations,
                output_artifacts=artifacts,
            )
        return BreakEvenOutcome(output_directory=output_dir, result=result)


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
        "message": result.message,
        "output_artifacts": list(artifacts),
    }
    writer.write_summary(output_dir, summary)
    writer.write_text_summary(output_dir, summary)
    artifacts.extend(["summary.json", "summary.txt"])
    return tuple(artifacts)
