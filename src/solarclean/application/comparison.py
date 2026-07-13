from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import pandas as pd

from solarclean.config.models import SolarCleanConfig
from solarclean.domain.calibration.registry import ParameterRegistry, build_validation_status
from solarclean.domain.coating.strategy import CoatingStrategy
from solarclean.domain.contamination.soiling import KimberStyleSoilingModel
from solarclean.domain.economics import (
    AnnualScenarioOutput,
    CostComponent,
    CostReconciliationCheck,
    CostReconciliationRule,
    EconomicResult,
    EconomicsCalibration,
    ReactiveCostRates,
    build_coating_cost_components_from_basis,
    build_economics_from_parameter_registry,
    build_reactive_cost_components,
    evaluate_annual_scenario_outputs,
    reconcile_operational_costs,
)
from solarclean.domain.environment.weather import WeatherDataset
from solarclean.domain.events.tape import ExogenousEventTape, generate_event_tape
from solarclean.domain.farm.representation import CohortFarm
from solarclean.domain.pv.model import CleanEnergyProfile
from solarclean.domain.reactive_cv.strategy import ReactiveCVStrategy
from solarclean.domain.scenario.contracts import (
    AnnualScenarioResult,
    DomainEvent,
    MitigationStrategy,
    OperationalQuantities,
    ScenarioContext,
    ordered_domain_events,
)
from solarclean.domain.simulation.baseline_strategy import BaselineStrategy
from solarclean.domain.simulation.scenario_engine import ScenarioSimulationEngine
from solarclean.infrastructure.persistence.outputs import OutputWriter, code_version_metadata
from solarclean.infrastructure.persistence.plots import write_comparison_diagnostic_plots
from solarclean.infrastructure.persistence.reports import write_json_report
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel

from .use_cases import _weather_provider, _weather_request

CANONICAL_SCENARIO_IDS: tuple[str, ...] = ("baseline", "reactive", "coating")
DEFAULT_PARAMETER_REGISTRY_PATH = Path("data/calibration/parameter_registry.yaml")
# Optional coarse progress reporting: (completed_units, total_units, stage_label).
# Units are whole scenario simulations -- no sub-scenario estimation is invented.
ProgressCallback = Callable[[int, int, str], None]
ENERGY_TOLERANCE_KWH = 1e-6
COST_TOLERANCE_SAR = 1e-6
RANKING_TOLERANCE_SAR = 1e-6
KEY_ASSUMPTION_REGISTRY_KEYS: tuple[str, ...] = (
    "soiling.base_daily_loss_fraction",
    "soiling.no_clean_annual_loss_target_fraction",
    "inspection.whole_farm_surveys_per_year",
    "inspection.drone_flight_hours_per_year_target",
    "cv.true_positive_rate",
    "cleaning.trigger_loss_fraction",
    "cleaning.water_liters_per_panel",
    "economics.drone_equipment_cost_sar",
    "economics.reactive_overhead_opex_sar_per_year",
    "coating.residual_annual_loss_target_fraction",
    "coating.dust_adhesion_reduction_fraction",
    "coating.dust_accumulation_multiplier",
    "coating.optical_relative_energy_effect_fraction",
    "coating.installed_capex_sar",
    "coating.annual_opex_reserve_sar_per_year",
    "coating.useful_life_years",
    "economics.electricity_tariff_sar_per_kwh",
)


@dataclass(frozen=True)
class ReconciliationCheckResult:
    name: str
    passed: bool
    message: str
    details: Mapping[str, object] = field(default_factory=dict)

    def to_record(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "details": _json_safe_mapping(self.details),
        }


@dataclass(frozen=True)
class ReconciliationReport:
    passed: bool
    checks: tuple[ReconciliationCheckResult, ...]

    def to_record(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "checks": [check.to_record() for check in self.checks],
        }


@dataclass(frozen=True)
class ScenarioRankingEntry:
    rank: int
    scenario_id: str
    net_annual_benefit_sar: float
    annual_actual_energy_kwh: float
    energy_gain_vs_baseline_kwh: float
    tied_with_previous: bool = False

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class Recommendation:
    valid: bool
    calculation_valid: bool
    recommendation_tier: str
    decision_grade: bool
    parameter_status_counts: Mapping[str, int]
    winner: str | None
    ordered_scenario_ids: tuple[str, ...]
    tied_winners: tuple[str, ...]
    decisive_margin_sar: float | None
    kpi_snapshot: Mapping[str, Mapping[str, object]]
    assumptions: tuple[Mapping[str, object], ...]
    warnings: tuple[Mapping[str, object], ...]
    traceability: Mapping[str, object]
    message: str

    def to_record(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "calculation_valid": self.calculation_valid,
            "recommendation_tier": self.recommendation_tier,
            "decision_grade": self.decision_grade,
            "parameter_status_counts": dict(self.parameter_status_counts),
            "winner": self.winner,
            "ordered_scenario_ids": list(self.ordered_scenario_ids),
            "tied_winners": list(self.tied_winners),
            "decisive_margin_sar": self.decisive_margin_sar,
            "kpi_snapshot": _json_safe_mapping(self.kpi_snapshot),
            "assumptions": [_json_safe_mapping(item) for item in self.assumptions],
            "warnings": [_json_safe_mapping(item) for item in self.warnings],
            "traceability": _json_safe_mapping(self.traceability),
            "message": self.message,
        }


@dataclass(frozen=True)
class ComparisonResult:
    run_id: str
    output_directory: Path
    config_checksum: str
    config_metadata: Mapping[str, object]
    weather_checksum: str
    event_tape_checksum: str
    scenario_results: Mapping[str, AnnualScenarioResult]
    economic_results: Mapping[str, EconomicResult]
    daily_summaries: Mapping[str, tuple[Mapping[str, object], ...]]
    annual_summaries: Mapping[str, Mapping[str, object]]
    event_summaries: Mapping[str, Mapping[str, object]]
    economic_summaries: Mapping[str, Mapping[str, object]]
    energy_gain_vs_baseline: Mapping[str, Mapping[str, object]]
    ranking: tuple[ScenarioRankingEntry, ...]
    recommendation: Recommendation
    validation_status: Mapping[str, object]
    warnings: tuple[Mapping[str, object], ...]
    assumptions: tuple[Mapping[str, object], ...]
    traceability: Mapping[str, object]
    reconciliation_report: ReconciliationReport
    output_artifacts: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        return {
            "command": "compare-all-scenarios",
            "run_id": self.run_id,
            "reconciled": self.reconciliation_report.passed,
            "scenario_ids": list(CANONICAL_SCENARIO_IDS),
            "weather_checksum": self.weather_checksum,
            "event_tape_checksum": self.event_tape_checksum,
            "ranking_count": 1 if self.ranking else 0,
            "winner": self.recommendation.winner,
            "calculation_valid": self.recommendation.calculation_valid,
            "recommendation_tier": self.recommendation.recommendation_tier,
            "decision_grade": self.recommendation.decision_grade,
            "tied_winners": list(self.recommendation.tied_winners),
            "validation_status": _json_safe_mapping(self.validation_status),
            "output_artifacts": list(self.output_artifacts),
        }

    def to_record(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "config_checksum": self.config_checksum,
            "config_metadata": _json_safe_mapping(self.config_metadata),
            "weather_checksum": self.weather_checksum,
            "event_tape_checksum": self.event_tape_checksum,
            "scenario_results": {
                scenario_id: _json_safe_mapping(summary)
                for scenario_id, summary in self.annual_summaries.items()
            },
            "daily_summaries": {
                scenario_id: [_json_safe_mapping(record) for record in records]
                for scenario_id, records in self.daily_summaries.items()
            },
            "annual_summaries": {
                scenario_id: _json_safe_mapping(summary)
                for scenario_id, summary in self.annual_summaries.items()
            },
            "event_summaries": {
                scenario_id: _json_safe_mapping(summary)
                for scenario_id, summary in self.event_summaries.items()
            },
            "economic_summaries": {
                scenario_id: _json_safe_mapping(summary)
                for scenario_id, summary in self.economic_summaries.items()
            },
            "energy_gain_vs_baseline": {
                scenario_id: _json_safe_mapping(summary)
                for scenario_id, summary in self.energy_gain_vs_baseline.items()
            },
            "ranking": [entry.to_record() for entry in self.ranking],
            "recommendation": self.recommendation.to_record(),
            "validation_status": _json_safe_mapping(self.validation_status),
            "warnings": [_json_safe_mapping(warning) for warning in self.warnings],
            "assumptions": [_json_safe_mapping(assumption) for assumption in self.assumptions],
            "traceability": _json_safe_mapping(self.traceability),
            "reconciliation_report": self.reconciliation_report.to_record(),
            "output_artifacts": list(self.output_artifacts),
        }


@dataclass(frozen=True)
class CompareAllScenariosResult:
    output_directory: Path
    summary: dict[str, object]
    comparison: ComparisonResult


class CompareAllScenarios:
    """Run baseline, reactive, and coating against one shared weather/event context."""

    def __init__(
        self,
        config: SolarCleanConfig,
        *,
        weather: WeatherDataset | None = None,
        clean_energy: CleanEnergyProfile | None = None,
        event_tape: ExogenousEventTape | None = None,
        scenario_order: Sequence[str] | None = None,
        parameter_registry_path: Path | None = None,
        parameter_registry: ParameterRegistry | None = None,
        write_artifacts: bool = True,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.config = config
        self.weather = weather
        if clean_energy is not None and weather is None:
            raise ValueError("clean_energy injection requires the matching weather dataset")
        self.clean_energy = clean_energy
        self.event_tape = event_tape
        # Reports scenario-level completion to callers (e.g. the dashboard job
        # table). Purely observational: it never alters simulation behaviour,
        # though a callback may raise to abort between scenarios.
        self.progress_callback = progress_callback
        self.scenario_order = _resolve_scenario_order(scenario_order)
        self.parameter_registry_path = (
            parameter_registry_path or config.calibration.parameter_registry_path
        )
        # Allows T7 experiment runners to inject an already-mutated registry (e.g. with one
        # economics parameter overridden for a sensitivity sweep) without writing a temp YAML
        # file to disk for every trial.
        self.parameter_registry = parameter_registry
        # T7 Monte Carlo / sensitivity experiments call CompareAllScenarios hundreds of times.
        # Writing the full CSV/PNG/JSON artifact package on every trial would be slow and would
        # flood disk with throwaway run directories, so callers that only need the in-memory
        # ComparisonResult can opt out. A run directory is still created (cheap) so run_id and
        # traceability stay consistent with normal runs.
        self.write_artifacts = write_artifacts

    def run(self) -> CompareAllScenariosResult:
        registry = self.parameter_registry or ParameterRegistry.from_yaml(
            self.parameter_registry_path
        )
        _validate_comparison_config(self.config, registry)
        weather = self.weather if self.weather is not None else _load_weather(self.config)
        profile = self.clean_energy
        if profile is None:
            profile = PVWattsPowerModel().calculate_hourly(weather, self.config.pv_system)
        else:
            _validate_injected_clean_energy(
                weather=weather,
                profile=profile,
                config=self.config,
            )
        event_tape = self.event_tape or _generate_event_tape(self.config, profile)
        weather_checksum = _weather_checksum(weather)
        event_tape_checksum = event_tape.checksum()
        context = ScenarioContext.from_inputs(
            weather=weather,
            clean_energy=profile,
            event_tape=event_tape,
            farm_config=self.config.farm,
            metadata={
                "weather_checksum": weather_checksum,
                "event_tape_checksum": event_tape_checksum,
            },
        )
        scenario_results = _run_scenarios(
            config=self.config,
            context=context,
            scenario_order=self.scenario_order,
            progress_callback=self.progress_callback,
        )

        economics = build_economics_from_parameter_registry(registry)
        operational_by_scenario = {
            scenario_id: _annual_operational_quantities(result)
            for scenario_id, result in scenario_results.items()
        }
        annual_outputs = _build_annual_economic_outputs(
            config=self.config,
            scenario_results=scenario_results,
            operational_by_scenario=operational_by_scenario,
            economics=economics,
        )
        economic_results = {
            result.scenario_name: result
            for result in evaluate_annual_scenario_outputs(
                outputs=tuple(
                    annual_outputs[scenario_id] for scenario_id in CANONICAL_SCENARIO_IDS
                ),
                config=economics.config,
            )
        }
        energy_gain = _energy_gain_vs_baseline(scenario_results)
        warnings = _comparison_warnings(
            config=self.config,
            weather=weather,
            economics=economics,
        )
        assumptions = _comparison_assumptions(
            config=self.config,
            economics=economics,
            registry_path=self.parameter_registry_path,
            registry=registry,
        )
        validation_status = build_validation_status(registry)

        writer = OutputWriter(self.config)
        if self.write_artifacts:
            output_dir = writer.create_run_directory("compare-all-scenarios")
        else:
            run_id = writer.build_run_id("compare-all-scenarios")
            output_dir = self.config.output.base_directory / run_id
        run_id = output_dir.name
        traceability = _traceability(
            run_id=run_id,
            config=self.config,
            config_checksum=_config_checksum(self.config),
            weather=weather,
            weather_checksum=weather_checksum,
            event_tape=event_tape,
            event_tape_checksum=event_tape_checksum,
            scenario_order=self.scenario_order,
            parameter_registry_path=self.parameter_registry_path,
            parameter_registry=registry,
            economics=economics,
        )
        cost_reconciliation_checks = _cost_reconciliation_checks(
            annual_outputs=annual_outputs,
            economic_results=economic_results,
            economics=economics,
        )
        preliminary_report = build_reconciliation_report(
            scenario_results=scenario_results,
            annual_outputs=annual_outputs,
            economic_results=economic_results,
            energy_gain_vs_baseline=energy_gain,
            scenario_input_checksums=_scenario_input_checksums(
                weather_checksum=weather_checksum,
                event_tape_checksum=event_tape_checksum,
            ),
            warnings=warnings,
            cost_reconciliation_checks=cost_reconciliation_checks,
            ranking=(),
            preliminary_reconciliation_passed=None,
        )
        if preliminary_report.passed:
            ranking = _rank_scenarios(
                scenario_results=scenario_results,
                economic_results=economic_results,
                energy_gain_vs_baseline=energy_gain,
            )
            reconciliation_report = build_reconciliation_report(
                scenario_results=scenario_results,
                annual_outputs=annual_outputs,
                economic_results=economic_results,
                energy_gain_vs_baseline=energy_gain,
                scenario_input_checksums=_scenario_input_checksums(
                    weather_checksum=weather_checksum,
                    event_tape_checksum=event_tape_checksum,
                ),
                warnings=warnings,
                cost_reconciliation_checks=cost_reconciliation_checks,
                ranking=ranking,
                preliminary_reconciliation_passed=True,
            )
        else:
            ranking = ()
            reconciliation_report = build_reconciliation_report(
                scenario_results=scenario_results,
                annual_outputs=annual_outputs,
                economic_results=economic_results,
                energy_gain_vs_baseline=energy_gain,
                scenario_input_checksums=_scenario_input_checksums(
                    weather_checksum=weather_checksum,
                    event_tape_checksum=event_tape_checksum,
                ),
                warnings=warnings,
                cost_reconciliation_checks=cost_reconciliation_checks,
                ranking=(),
                preliminary_reconciliation_passed=False,
            )
        recommendation = _build_recommendation(
            ranking=ranking,
            scenario_results=scenario_results,
            economic_results=economic_results,
            energy_gain_vs_baseline=energy_gain,
            assumptions=assumptions,
            warnings=warnings,
            traceability=traceability,
            reconciliation_report=reconciliation_report,
            config=self.config,
            registry=registry,
            weather=weather,
        )
        daily_summaries = _daily_summaries(scenario_results)
        annual_summaries = _annual_summaries(
            scenario_results=scenario_results,
            economic_results=economic_results,
            energy_gain_vs_baseline=energy_gain,
            operational_by_scenario=operational_by_scenario,
            weather_checksum=weather_checksum,
            event_tape_checksum=event_tape_checksum,
        )
        event_summaries = _event_summaries(scenario_results)
        economic_summaries = {
            scenario_id: _economic_summary(economic_results[scenario_id])
            for scenario_id in CANONICAL_SCENARIO_IDS
        }
        output_artifacts: tuple[str, ...] = ()
        if self.write_artifacts:
            output_artifacts = _write_comparison_package(
                output_dir=output_dir,
                writer=writer,
                config=self.config,
                weather=weather,
                profile=profile,
                event_tape=event_tape,
                run_id=run_id,
                scenario_results=scenario_results,
                daily_summaries=daily_summaries,
                annual_summaries=annual_summaries,
                economic_results=economic_results,
                cost_reconciliation_checks=cost_reconciliation_checks,
                ranking=ranking,
                recommendation=recommendation,
                validation_status=validation_status,
                reconciliation_report=reconciliation_report,
                traceability=traceability,
            )
        comparison = ComparisonResult(
            run_id=run_id,
            output_directory=output_dir,
            config_checksum=str(traceability["config_checksum"]),
            config_metadata=_config_metadata(self.config),
            weather_checksum=weather_checksum,
            event_tape_checksum=event_tape_checksum,
            scenario_results=MappingProxyType(dict(scenario_results)),
            economic_results=MappingProxyType(dict(economic_results)),
            daily_summaries=MappingProxyType(dict(daily_summaries)),
            annual_summaries=MappingProxyType(dict(annual_summaries)),
            event_summaries=MappingProxyType(dict(event_summaries)),
            economic_summaries=MappingProxyType(dict(economic_summaries)),
            energy_gain_vs_baseline=MappingProxyType(dict(energy_gain)),
            ranking=ranking,
            recommendation=recommendation,
            validation_status=MappingProxyType(validation_status),
            warnings=warnings,
            assumptions=assumptions,
            traceability=traceability,
            reconciliation_report=reconciliation_report,
            output_artifacts=output_artifacts,
        )
        summary = comparison.to_summary()
        if self.write_artifacts:
            writer.write_summary(output_dir, summary)
            writer.write_text_summary(output_dir, summary)
        return CompareAllScenariosResult(
            output_directory=output_dir,
            summary=summary,
            comparison=comparison,
        )


def build_reconciliation_report(
    *,
    scenario_results: Mapping[str, AnnualScenarioResult],
    annual_outputs: Mapping[str, AnnualScenarioOutput],
    economic_results: Mapping[str, EconomicResult],
    energy_gain_vs_baseline: Mapping[str, Mapping[str, object]],
    scenario_input_checksums: Mapping[str, Mapping[str, str]],
    warnings: tuple[Mapping[str, object], ...],
    cost_reconciliation_checks: Mapping[str, tuple[CostReconciliationCheck, ...]],
    ranking: tuple[ScenarioRankingEntry, ...],
    preliminary_reconciliation_passed: bool | None,
) -> ReconciliationReport:
    checks: list[ReconciliationCheckResult] = []
    checks.extend(_input_checksum_checks(scenario_input_checksums))
    checks.extend(_annual_daily_energy_checks(scenario_results))
    checks.extend(_operational_checks(scenario_results, annual_outputs))
    checks.extend(_economic_checks(annual_outputs, economic_results, cost_reconciliation_checks))
    checks.extend(_energy_gain_checks(scenario_results, energy_gain_vs_baseline))
    checks.append(_warnings_check(warnings))
    if preliminary_reconciliation_passed is not None:
        checks.extend(
            _ranking_checks(
                ranking=ranking,
                economic_results=economic_results,
                preliminary_reconciliation_passed=preliminary_reconciliation_passed,
            )
        )
    return ReconciliationReport(
        passed=all(check.passed for check in checks),
        checks=tuple(checks),
    )


def _load_weather(config: SolarCleanConfig) -> WeatherDataset:
    return _weather_provider(config).load(_weather_request(config))


def _validate_injected_clean_energy(
    *,
    weather: WeatherDataset,
    profile: CleanEnergyProfile,
    config: SolarCleanConfig,
) -> None:
    """Reject a cached PV profile that does not belong to these static inputs."""
    if not profile.hourly.index.equals(weather.hourly.index):
        raise ValueError("injected clean_energy timestamps must match weather timestamps")
    expected_metadata: dict[str, object] = {
        "panel_count": config.pv_system.panel_count,
        "panel_capacity_w": config.pv_system.panel_capacity_w,
        "total_dc_capacity_w": config.pv_system.total_dc_capacity_w,
        "tilt_degrees": config.pv_system.tilt_degrees,
        "azimuth_degrees": config.pv_system.azimuth_degrees,
        "inverter_efficiency": config.pv_system.inverter_efficiency,
        "dc_ac_ratio": config.pv_system.dc_ac_ratio,
        "gamma_pdc_per_c": config.pv_system.gamma_pdc_per_c,
        "module_temperature_model": config.pv_system.module_temperature_model,
    }
    mismatches = [
        key for key, expected in expected_metadata.items() if profile.metadata.get(key) != expected
    ]
    if mismatches:
        raise ValueError(
            "injected clean_energy does not match pv_system fields: " + ", ".join(mismatches)
        )


def _validate_comparison_config(
    config: SolarCleanConfig,
    registry: ParameterRegistry,
) -> None:
    if config.reactive_cv.perfect_information_benchmark:
        raise ValueError(
            "perfect_information_benchmark cannot replace the ranked reactive scenario; "
            "run the oracle only through the separate reactive benchmark use case"
        )
    mitigation_enabled = config.reactive_cv.enabled or config.coating.enabled
    if mitigation_enabled and config.farm.representation != "cohort":
        raise ValueError(
            "three-scenario mitigation comparison requires farm.representation='cohort'"
        )
    if (
        config.calibration.assumption_set == "riyadh_central_v2"
        and config.coating.preset == "central"
    ):
        registry_value = registry.get("coating.dust_accumulation_multiplier").central_value
        configured = config.coating.physics.dust_accumulation_multiplier
        if abs(configured - registry_value) > 1e-12:
            raise ValueError(
                "riyadh_central_v2 coating dust_accumulation_multiplier must match the "
                f"active parameter registry central value ({configured} != {registry_value})"
            )
    if config.calibration.assumption_set == "riyadh_central_v2" and config.reactive_cv.enabled:
        panels_per_worker_hour = registry.get("cleaning.panels_per_worker_hour").central_value
        expected_cleaning_minutes = 60.0 * config.farm.panels_per_cohort / panels_per_worker_hour
        configured_cleaning_minutes = config.reactive_cv.crew.cleaning_minutes_per_cohort
        if abs(configured_cleaning_minutes - expected_cleaning_minutes) > 1e-12:
            raise ValueError(
                "riyadh_central_v2 cleaning_minutes_per_cohort must match the active "
                "parameter registry central panels-per-worker-hour calibration "
                f"({configured_cleaning_minutes} != {expected_cleaning_minutes})"
            )


def _generate_event_tape(
    config: SolarCleanConfig,
    profile: CleanEnergyProfile,
) -> ExogenousEventTape:
    dates = tuple(pd.Timestamp(str(day)).date() for day in profile.daily.index)
    return generate_event_tape(
        dates=dates,
        seed=config.soiling.random_seed,
        soiling=config.soiling,
        rainfall=config.rainfall_cleaning,
        farm=config.farm,
        birds=config.bird_droppings,
    )


def _run_scenarios(
    *,
    config: SolarCleanConfig,
    context: ScenarioContext,
    scenario_order: tuple[str, ...],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, AnnualScenarioResult]:
    executed: dict[str, AnnualScenarioResult] = {}
    total = len(scenario_order)
    for completed, scenario_id in enumerate(scenario_order):
        if progress_callback is not None:
            progress_callback(completed, total, f"Simulating {scenario_id} scenario")
        strategy = _build_strategy(scenario_id, config)
        executed[scenario_id] = ScenarioSimulationEngine(strategy).run(
            context,
            random_seed=config.soiling.random_seed,
        )
    if progress_callback is not None:
        progress_callback(total, total, "Scenarios simulated; evaluating economics and artifacts")
    return {scenario_id: executed[scenario_id] for scenario_id in CANONICAL_SCENARIO_IDS}


def _build_strategy(scenario_id: str, config: SolarCleanConfig) -> MitigationStrategy:
    baseline_farm = (
        CohortFarm(config.farm, config.bird_droppings)
        if config.farm.representation == "cohort"
        else None
    )
    if scenario_id == "baseline":
        return BaselineStrategy(
            KimberStyleSoilingModel(config.soiling, config.rainfall_cleaning),
            farm=baseline_farm,
            farm_config=config.farm,
        )
    if scenario_id == "reactive":
        if not config.reactive_cv.enabled:
            return BaselineStrategy(
                KimberStyleSoilingModel(config.soiling, config.rainfall_cleaning),
                farm=baseline_farm,
                farm_config=config.farm,
                name="reactive",
            )
        return ReactiveCVStrategy(
            reactive=config.reactive_cv,
            soiling=config.soiling,
            rainfall=config.rainfall_cleaning,
            birds=config.bird_droppings,
            farm=config.farm,
            perfect_information=config.reactive_cv.perfect_information_benchmark,
            name="reactive",
        )
    if scenario_id == "coating":
        if not config.coating.enabled:
            return BaselineStrategy(
                KimberStyleSoilingModel(config.soiling, config.rainfall_cleaning),
                farm=baseline_farm,
                farm_config=config.farm,
                name="coating",
            )
        return CoatingStrategy(
            coating=config.coating,
            soiling=config.soiling,
            rainfall=config.rainfall_cleaning,
            birds=config.bird_droppings,
            farm=config.farm,
            pv_system=config.pv_system,
        )
    raise ValueError(f"unknown scenario id: {scenario_id}")


def _load_economics(parameter_registry_path: Path) -> EconomicsCalibration:
    registry = ParameterRegistry.from_yaml(parameter_registry_path)
    return build_economics_from_parameter_registry(registry)


def _build_annual_economic_outputs(
    *,
    config: SolarCleanConfig,
    scenario_results: Mapping[str, AnnualScenarioResult],
    operational_by_scenario: Mapping[str, OperationalQuantities],
    economics: EconomicsCalibration,
) -> dict[str, AnnualScenarioOutput]:
    outputs: dict[str, AnnualScenarioOutput] = {}
    for scenario_id in CANONICAL_SCENARIO_IDS:
        result = scenario_results[scenario_id]
        operational = operational_by_scenario[scenario_id]
        cost_components: tuple[CostComponent, ...] = ()
        metadata: dict[str, object] = {}
        useful_life_years: float | None = None
        if scenario_id == "reactive" and config.reactive_cv.enabled:
            cost_components = build_reactive_cost_components(
                operational_quantities=operational,
                rates=economics.reactive_cost_rates,
                additional_components=economics.equipment_cost_components,
            )
            # Drone/camera equipment wears out on its own schedule, not the
            # PV plant's: recover the reactive CAPEX over the registry's
            # drone-equipment life, mirroring how coating CAPEX uses the
            # coating's useful life.
            useful_life_years = economics.drone_equipment_useful_life_years
        elif scenario_id == "coating":
            coating_basis = _coating_cost_basis(result)
            if coating_basis:
                metadata["coating_cost_basis"] = coating_basis
                useful_life_years = _coating_useful_life_years(coating_basis)
                cost_components = build_coating_cost_components_from_basis(
                    coating_cost_basis=coating_basis,
                    application_labour_rate=economics.reactive_cost_rates.crew_hour,
                    process_energy_rate=economics.reactive_cost_rates.energy_kwh,
                    inspection_labour_rate=economics.reactive_cost_rates.crew_hour,
                )
        outputs[scenario_id] = AnnualScenarioOutput(
            scenario_name=scenario_id,
            actual_energy_kwh=result.annual_actual_energy_kwh,
            clean_energy_kwh=result.annual_clean_energy_kwh,
            operational_quantities=operational,
            cost_components=cost_components,
            metadata=metadata,
            useful_life_years=useful_life_years,
        )
    return outputs


def _annual_operational_quantities(result: AnnualScenarioResult) -> OperationalQuantities:
    daily = result.daily_results
    coated_panel_count = max(
        (day.operational.coated_panel_count for day in daily),
        default=0,
    )
    return OperationalQuantities(
        inspections_count=sum(day.operational.inspections_count for day in daily),
        cleaning_actions_count=sum(day.operational.cleaning_actions_count for day in daily),
        coated_panel_count=coated_panel_count,
        crew_hours=sum(day.operational.crew_hours for day in daily),
        drone_flight_hours=sum(day.operational.drone_flight_hours for day in daily),
        water_liters=sum(day.operational.water_liters for day in daily),
        energy_used_kwh=sum(day.operational.energy_used_kwh for day in daily),
        opex_cost=sum(day.operational.opex_cost for day in daily),
        capex_cost=sum(day.operational.capex_cost for day in daily),
    )


def _coating_cost_basis(result: AnnualScenarioResult) -> Mapping[str, object]:
    for daily in result.daily_results:
        raw = daily.extensions.get("coating_cost_basis")
        if isinstance(raw, Mapping):
            return {str(key): value for key, value in raw.items()}
    return {}


def _coating_useful_life_years(cost_basis: Mapping[str, object]) -> float | None:
    raw_life = cost_basis.get("useful_life_years")
    if raw_life is None:
        return None
    life = _numeric_value(raw_life, label="coating useful_life_years")
    if life <= 0:
        raise ValueError("coating useful_life_years must be positive.")
    return life


def _energy_gain_vs_baseline(
    scenario_results: Mapping[str, AnnualScenarioResult],
) -> dict[str, Mapping[str, object]]:
    baseline = scenario_results["baseline"].annual_actual_energy_kwh
    gains: dict[str, Mapping[str, object]] = {}
    for scenario_id in CANONICAL_SCENARIO_IDS:
        actual = scenario_results[scenario_id].annual_actual_energy_kwh
        gain = actual - baseline
        gains[scenario_id] = {
            "basis": "annual_actual_energy_kwh",
            "baseline_annual_actual_energy_kwh": baseline,
            "scenario_annual_actual_energy_kwh": actual,
            "energy_gain_vs_baseline_kwh": gain,
            "energy_gain_vs_baseline_percent": _safe_divide(gain, baseline) * 100.0
            if baseline > 0
            else None,
        }
    return gains


def _comparison_warnings(
    *,
    config: SolarCleanConfig,
    weather: WeatherDataset,
    economics: EconomicsCalibration,
) -> tuple[Mapping[str, object], ...]:
    warnings: list[Mapping[str, object]] = []
    if config.weather.provider != "nasa_power":
        warnings.append(
            {
                "code": "non_live_weather_provider",
                "message": (
                    f"Comparison used weather.provider={config.weather.provider}; "
                    "decision use requires measured or refreshed weather."
                ),
                "source": "config.weather.provider",
            }
        )
    if bool(weather.metadata.get("test_only", False)):
        warnings.append(
            {
                "code": "fixture_weather_test_only",
                "message": "Fixture weather is deterministic test data, not a Riyadh measurement.",
                "source": "weather.metadata.test_only",
            }
        )
    if not _simulation_period_is_full_year(config):
        warnings.append(
            {
                "code": "simulation_period_not_full_year",
                "message": (
                    "Comparison period is not a full Jan 1-Dec 31 site-year; "
                    "annual fields represent the configured period total and no economic "
                    "recommendation may be produced."
                ),
                "source": "simulation.start/simulation.end",
                "blocking": True,
            }
        )
    if config.coating.costs.source_status != "prompt_quoted":
        warnings.append(
            {
                "code": "coating_costs_not_validated",
                "message": (
                    "Coating cost assumptions are "
                    f"{config.coating.costs.source_status}, not validated field costs."
                ),
                "source": "coating.costs.source_status",
            }
        )
    if not config.coating.deployment.field_application_demonstrated:
        warnings.append(
            {
                "code": "coating_field_application_not_demonstrated",
                "message": "Coating deployment remains provisional for field application.",
                "source": "coating.deployment.field_application_demonstrated",
            }
        )
    for warning in economics.warnings:
        warnings.append(
            {
                "code": "non_validated_economic_parameter",
                "message": warning.message,
                "source": warning.registry_key,
                "status": warning.status,
            }
        )
    return tuple(MappingProxyType(dict(warning)) for warning in warnings)


def _simulation_period_is_full_year(config: SolarCleanConfig) -> bool:
    start = config.simulation.start
    end = config.simulation.end
    return (
        start.year == end.year
        and start.month == 1
        and start.day == 1
        and end.month == 12
        and end.day == 31
    )


def _comparison_assumptions(
    *,
    config: SolarCleanConfig,
    economics: EconomicsCalibration,
    registry_path: Path,
    registry: ParameterRegistry,
) -> tuple[Mapping[str, object], ...]:
    assumptions: list[Mapping[str, object]] = [
        {
            "code": "shared_weather_event_tape",
            "message": (
                "Baseline, reactive, and coating scenarios are run against one resolved "
                "weather dataset and one immutable exogenous event tape."
            ),
        },
        {
            "code": "ranking_metric",
            "message": "Scenario ranking uses T4 net_annual_benefit_sar after reconciliation.",
        },
        {
            "code": "roi_payback_basis",
            "message": (
                "Comparison CSV and recommendation outputs include ROI/payback fields "
                "computed as incremental mitigation economics versus baseline."
            ),
        },
        {
            "code": "central_assumption_set",
            "assumption_set": config.calibration.assumption_set,
            "registry_path": str(registry_path),
            "source_note": config.calibration.source_note,
        },
    ]
    assumptions.extend(_registry_assumption_records(registry, registry_path))
    assumptions.extend(_configured_assumption_records(config, registry_path))
    for metadata in economics.parameter_metadata:
        record = asdict(metadata)
        record["code"] = "t5_economics_parameter"
        record["registry_path"] = str(registry_path)
        assumptions.append(record)
    return tuple(MappingProxyType(dict(assumption)) for assumption in assumptions)


def _configured_assumption_records(
    config: SolarCleanConfig,
    registry_path: Path,
) -> list[Mapping[str, object]]:
    records = [
        (
            "soiling.base_daily_loss_fraction",
            "soiling.base_daily_soiling_loss_fraction",
            config.soiling.base_daily_soiling_loss_fraction,
            "fraction/day",
        ),
        (
            "reactive.whole_farm_surveys_per_year",
            "reactive_cv.inspection.interval_days",
            365.0 / config.reactive_cv.inspection.interval_days,
            "surveys/year",
        ),
        (
            "reactive.drone_cohorts_per_flight",
            "reactive_cv.drone.cohorts_per_flight",
            config.reactive_cv.drone.cohorts_per_flight,
            "cohorts/flight",
        ),
        (
            "reactive.cv_recall_fraction",
            "reactive_cv.observer.recall_fraction",
            config.reactive_cv.observer.recall_fraction,
            "fraction",
        ),
        (
            "reactive.cleaning_trigger_fraction",
            "reactive_cv.dispatch.estimated_loss_threshold_fraction",
            config.reactive_cv.dispatch.estimated_loss_threshold_fraction,
            "fraction",
        ),
        (
            "reactive.water_liters_per_panel",
            "reactive_cv.crew.water_liters_per_cohort",
            config.reactive_cv.crew.water_liters_per_cohort / config.farm.panels_per_cohort,
            "liters/panel",
        ),
        (
            "coating.dust_accumulation_multiplier",
            "coating.physics.dust_accumulation_multiplier",
            config.coating.physics.dust_accumulation_multiplier,
            "multiplier",
        ),
        (
            "coating.optical_transmittance_multiplier",
            "coating.physics.optical_transmittance_multiplier",
            config.coating.physics.optical_transmittance_multiplier,
            "multiplier",
        ),
        (
            "coating.useful_life_years",
            "coating.costs.useful_life_years",
            config.coating.costs.useful_life_years,
            "years",
        ),
    ]
    return [
        {
            "code": "configured_central_v2_parameter",
            "registry_key": key,
            "configuration_path": path,
            "value": value,
            "unit": unit,
            "assumption_set": config.calibration.assumption_set,
            "registry_path": str(registry_path),
        }
        for key, path, value, unit in records
    ]


def _registry_assumption_records(
    registry: ParameterRegistry,
    registry_path: Path,
) -> list[Mapping[str, object]]:
    records: list[Mapping[str, object]] = []
    for key in KEY_ASSUMPTION_REGISTRY_KEYS:
        parameter = registry.get(key)
        records.append(
            {
                "code": "t5_key_assumption_parameter",
                "registry_key": parameter.name,
                "configuration_path": parameter.configuration_path,
                "central_value": parameter.central_value,
                "low_value": parameter.low_value,
                "high_value": parameter.high_value,
                "unit": parameter.unit,
                "source": parameter.source,
                "status": parameter.status,
                "confidence": parameter.confidence,
                "evidence_type": parameter.evidence_type,
                "rationale": parameter.rationale,
                "registry_path": str(registry_path),
            }
        )
    return records


def _traceability(
    *,
    run_id: str,
    config: SolarCleanConfig,
    config_checksum: str,
    weather: WeatherDataset,
    weather_checksum: str,
    event_tape: ExogenousEventTape,
    event_tape_checksum: str,
    scenario_order: tuple[str, ...],
    parameter_registry_path: Path,
    parameter_registry: ParameterRegistry,
    economics: EconomicsCalibration,
) -> Mapping[str, object]:
    code_version = code_version_metadata()
    return MappingProxyType(
        {
            "run_id": run_id,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "project": "SolarClean-DT",
            **code_version,
            "config_checksum": config_checksum,
            "config_metadata": _config_metadata(config),
            "weather_checksum": weather_checksum,
            "weather_provider": weather.metadata.get("provider"),
            "weather_metadata": _json_safe_mapping(weather.metadata),
            "event_tape_checksum": event_tape_checksum,
            "event_tape_metadata": _json_safe_mapping(event_tape.metadata),
            "scenario_execution_order": list(scenario_order),
            "scenario_output_order": list(CANONICAL_SCENARIO_IDS),
            "parameter_registry_path": str(parameter_registry_path),
            "parameter_registry_checksum": parameter_registry.checksum(),
            "parameter_registry_metadata": dict(parameter_registry.metadata),
            "parameter_registry_parameters": parameter_registry.to_records(),
            "calibration_assumption_set": config.calibration.assumption_set,
            "economics_parameter_count": len(economics.parameter_metadata),
            "economics_config": asdict(economics.config),
        }
    )


def _config_metadata(config: SolarCleanConfig) -> Mapping[str, object]:
    return MappingProxyType(
        {
            "site": config.site.model_dump(mode="json"),
            "simulation": config.simulation.model_dump(mode="json"),
            "weather": config.weather.model_dump(mode="json"),
            "farm": config.farm.model_dump(mode="json"),
            "calibration": config.calibration.model_dump(mode="json"),
            "reactive_cv_enabled": config.reactive_cv.enabled,
            "coating_enabled": config.coating.enabled,
            "coating_preset": config.coating.preset,
        }
    )


def _cost_reconciliation_checks(
    *,
    annual_outputs: Mapping[str, AnnualScenarioOutput],
    economic_results: Mapping[str, EconomicResult],
    economics: EconomicsCalibration,
) -> dict[str, tuple[CostReconciliationCheck, ...]]:
    del economic_results
    rules = _reactive_cost_rules(economics.reactive_cost_rates)
    return {
        "baseline": (),
        "reactive": reconcile_operational_costs(
            operational_quantities=annual_outputs["reactive"].operational_quantities,
            cost_components=annual_outputs["reactive"].cost_components,
            rules=rules,
        )
        if rules
        else (),
        "coating": (),
    }


def _reactive_cost_rules(rates: ReactiveCostRates) -> tuple[CostReconciliationRule, ...]:
    pairs = (
        ("reactive inspection operations", "inspections_count", rates.inspection),
        ("reactive cleaning equipment use", "cleaning_actions_count", rates.cleaning_action),
        ("reactive crew labour", "crew_hours", rates.crew_hour),
        ("reactive drone flight operations", "drone_flight_hours", rates.drone_flight_hour),
        ("reactive water use", "water_liters", rates.water_liter),
        ("reactive energy use", "energy_used_kwh", rates.energy_kwh),
    )
    rules: list[CostReconciliationRule] = []
    for name, quantity, rate in pairs:
        if rate is None:
            continue
        rules.append(
            CostReconciliationRule(
                cost_component_name=name,
                quantity_name=quantity,
                rate_sar_per_unit=rate.amount_sar_per_unit,
                tolerance_sar=COST_TOLERANCE_SAR,
            )
        )
    return tuple(rules)


def _input_checksum_checks(
    scenario_input_checksums: Mapping[str, Mapping[str, str]],
) -> tuple[ReconciliationCheckResult, ...]:
    weather = {
        scenario_id: checks["weather_checksum"]
        for scenario_id, checks in scenario_input_checksums.items()
    }
    event_tapes = {
        scenario_id: checks["event_tape_checksum"]
        for scenario_id, checks in scenario_input_checksums.items()
    }
    return (
        _same_value_check(
            name="same_weather_checksum",
            values=weather,
            label="weather checksum",
        ),
        _same_value_check(
            name="same_event_tape_checksum",
            values=event_tapes,
            label="event tape checksum",
        ),
    )


def _annual_daily_energy_checks(
    scenario_results: Mapping[str, AnnualScenarioResult],
) -> tuple[ReconciliationCheckResult, ...]:
    checks: list[ReconciliationCheckResult] = []
    for scenario_id, result in scenario_results.items():
        daily_clean = sum(day.clean_energy_kwh for day in result.daily_results)
        daily_actual = sum(day.actual_energy_kwh for day in result.daily_results)
        clean_diff = result.annual_clean_energy_kwh - daily_clean
        actual_diff = result.annual_actual_energy_kwh - daily_actual
        passed = (
            abs(clean_diff) <= ENERGY_TOLERANCE_KWH and abs(actual_diff) <= ENERGY_TOLERANCE_KWH
        )
        checks.append(
            ReconciliationCheckResult(
                name=f"{scenario_id}_annual_energy_reconciles_with_daily",
                passed=passed,
                message="OK"
                if passed
                else (
                    f"{scenario_id} annual energy does not equal summed daily outputs: "
                    f"clean_diff={clean_diff:.6g} kWh, actual_diff={actual_diff:.6g} kWh."
                ),
                details={
                    "annual_clean_energy_kwh": result.annual_clean_energy_kwh,
                    "summed_daily_clean_energy_kwh": daily_clean,
                    "annual_actual_energy_kwh": result.annual_actual_energy_kwh,
                    "summed_daily_actual_energy_kwh": daily_actual,
                    "tolerance_kwh": ENERGY_TOLERANCE_KWH,
                },
            )
        )
    return tuple(checks)


def _operational_checks(
    scenario_results: Mapping[str, AnnualScenarioResult],
    annual_outputs: Mapping[str, AnnualScenarioOutput],
) -> tuple[ReconciliationCheckResult, ...]:
    checks: list[ReconciliationCheckResult] = []
    for scenario_id, result in scenario_results.items():
        expected = _annual_operational_quantities(result)
        recorded = annual_outputs[scenario_id].operational_quantities
        expected_record = expected.to_record()
        recorded_record = recorded.to_record()
        passed = expected_record == recorded_record
        checks.append(
            ReconciliationCheckResult(
                name=f"{scenario_id}_annual_operational_quantities_reconcile_with_daily",
                passed=passed,
                message="OK"
                if passed
                else f"{scenario_id} annual operational quantities do not match daily sums.",
                details={
                    "expected_from_daily": expected_record,
                    "recorded_for_economics": recorded_record,
                },
            )
        )
    checks.extend(_reactive_event_log_checks(scenario_results.get("reactive")))
    checks.extend(_coating_operational_basis_checks(scenario_results.get("coating")))
    return tuple(checks)


def _reactive_event_log_checks(
    result: AnnualScenarioResult | None,
) -> tuple[ReconciliationCheckResult, ...]:
    if result is None:
        return ()
    operational = _annual_operational_quantities(result)
    inspection_events = _event_count(result.events, "reactive_inspection")
    cleaning_events = _event_count(result.events, "reactive_cleaning_action")
    return (
        _quantity_event_check(
            name="reactive_inspections_reconcile_with_event_log",
            quantity_name="inspections_count",
            quantity_value=float(operational.inspections_count),
            event_count=inspection_events,
        ),
        _quantity_event_check(
            name="reactive_cleaning_actions_reconcile_with_event_log",
            quantity_name="cleaning_actions_count",
            quantity_value=float(operational.cleaning_actions_count),
            event_count=cleaning_events,
        ),
    )


def _coating_operational_basis_checks(
    result: AnnualScenarioResult | None,
) -> tuple[ReconciliationCheckResult, ...]:
    if result is None or not result.daily_results:
        return ()
    basis = _coating_cost_basis(result)
    coated_panels = _annual_operational_quantities(result).coated_panel_count
    if not basis and coated_panels == 0:
        return (
            ReconciliationCheckResult(
                name="coating_disabled_has_no_operational_or_cost_basis",
                passed=True,
                message="OK",
            ),
        )
    basis_panels = basis.get("coated_panel_count")
    panel_passed = isinstance(basis_panels, int | float) and int(basis_panels) == coated_panels
    operational_energy = _annual_operational_quantities(result).energy_used_kwh
    basis_energy = basis.get("process_energy_kwh")
    energy_passed = (
        isinstance(basis_energy, int | float)
        and abs(float(basis_energy) - operational_energy) <= ENERGY_TOLERANCE_KWH
    )
    return (
        ReconciliationCheckResult(
            name="coating_coated_panel_count_reconciles_with_cost_basis",
            passed=panel_passed,
            message="OK"
            if panel_passed
            else (
                "Coating coated_panel_count does not match the coating cost basis "
                f"(operational={coated_panels}, basis={basis_panels})."
            ),
            details={
                "operational_coated_panel_count": coated_panels,
                "cost_basis_coated_panel_count": basis_panels,
            },
        ),
        ReconciliationCheckResult(
            name="coating_process_energy_reconciles_with_cost_basis",
            passed=energy_passed,
            message="OK"
            if energy_passed
            else (
                "Coating operational process energy does not match its one-time cost basis "
                f"(operational={operational_energy}, basis={basis_energy})."
            ),
            details={
                "operational_process_energy_kwh": operational_energy,
                "cost_basis_process_energy_kwh": basis_energy,
            },
        ),
    )


def _economic_checks(
    annual_outputs: Mapping[str, AnnualScenarioOutput],
    economic_results: Mapping[str, EconomicResult],
    cost_reconciliation_checks: Mapping[str, tuple[CostReconciliationCheck, ...]],
) -> tuple[ReconciliationCheckResult, ...]:
    checks: list[ReconciliationCheckResult] = []
    for scenario_id in CANONICAL_SCENARIO_IDS:
        output = annual_outputs[scenario_id]
        economic = economic_results[scenario_id]
        checks.append(_economic_physical_check(output, economic))
        checks.append(_economic_component_total_check(scenario_id, economic))
        for cost_check in cost_reconciliation_checks.get(scenario_id, ()):
            checks.append(
                ReconciliationCheckResult(
                    name=f"{scenario_id}_cost_{cost_check.quantity_name}_reconciles",
                    passed=cost_check.passed,
                    message=cost_check.message,
                    details=asdict(cost_check),
                )
            )
    checks.append(
        _coating_cost_completeness_check(
            annual_outputs["coating"],
            economic_results["coating"],
        )
    )
    return tuple(checks)


def _coating_cost_completeness_check(
    output: AnnualScenarioOutput,
    economic: EconomicResult,
) -> ReconciliationCheckResult:
    basis = output.metadata.get("coating_cost_basis")
    if not isinstance(basis, Mapping):
        passed = not output.cost_components
        return ReconciliationCheckResult(
            name="coating_cost_basis_is_fully_priced",
            passed=passed,
            message="OK" if passed else "Disabled coating unexpectedly has cost components.",
        )
    required = {
        "coating material capex",
        "coating surface preparation capex",
        "coating fixed equipment capex",
        "coating maintenance opex",
        "coating application labour capex",
        "coating process energy capex",
        "coating inspection labour opex",
    }
    present = {component.name for component in economic.cost_breakdown}
    missing = sorted(required - present)
    return ReconciliationCheckResult(
        name="coating_cost_basis_is_fully_priced",
        passed=not missing,
        message="OK" if not missing else f"Missing coating cost components: {missing}.",
        details={"required_components": sorted(required), "missing_components": missing},
    )


def _economic_physical_check(
    output: AnnualScenarioOutput,
    economic: EconomicResult,
) -> ReconciliationCheckResult:
    scenario_name_matches = output.scenario_name == economic.scenario_name
    revenue_non_negative = economic.annual_revenue_sar >= 0.0 and output.actual_energy_kwh >= 0.0
    passed = scenario_name_matches and revenue_non_negative
    return ReconciliationCheckResult(
        name=f"{output.scenario_name}_economic_result_reconciles_with_physical_output",
        passed=passed,
        message="OK"
        if passed
        else (
            f"{output.scenario_name} economic result does not align with physical annual output."
        ),
        details={
            "scenario_name": output.scenario_name,
            "economic_scenario_name": economic.scenario_name,
            "actual_energy_kwh": output.actual_energy_kwh,
            "annual_revenue_sar": economic.annual_revenue_sar,
        },
    )


def _economic_component_total_check(
    scenario_id: str,
    economic: EconomicResult,
) -> ReconciliationCheckResult:
    capex = sum(
        component.amount_sar
        for component in economic.cost_breakdown
        if component.category == "capex"
    )
    opex = sum(
        component.amount_sar
        for component in economic.cost_breakdown
        if component.category == "opex"
    )
    capex_diff = economic.total_capex_sar - capex
    opex_diff = economic.annual_opex_sar - opex
    total_diff = economic.total_annual_cost_sar - (
        economic.annualized_capex_sar + economic.annual_opex_sar
    )
    net_diff = economic.net_annual_benefit_sar - (
        economic.annual_revenue_sar - economic.total_annual_cost_sar
    )
    passed = (
        abs(capex_diff) <= COST_TOLERANCE_SAR
        and abs(opex_diff) <= COST_TOLERANCE_SAR
        and abs(total_diff) <= COST_TOLERANCE_SAR
        and abs(net_diff) <= COST_TOLERANCE_SAR
    )
    return ReconciliationCheckResult(
        name=f"{scenario_id}_economic_totals_reconcile",
        passed=passed,
        message="OK"
        if passed
        else (
            f"{scenario_id} economic totals do not reconcile: capex_diff={capex_diff:.6g}, "
            f"opex_diff={opex_diff:.6g}, total_diff={total_diff:.6g}, "
            f"net_diff={net_diff:.6g}."
        ),
        details={
            "cost_tolerance_sar": COST_TOLERANCE_SAR,
            "capex_component_sum_sar": capex,
            "opex_component_sum_sar": opex,
            "total_capex_sar": economic.total_capex_sar,
            "annual_opex_sar": economic.annual_opex_sar,
            "total_annual_cost_sar": economic.total_annual_cost_sar,
            "net_annual_benefit_sar": economic.net_annual_benefit_sar,
        },
    )


def _energy_gain_checks(
    scenario_results: Mapping[str, AnnualScenarioResult],
    energy_gain_vs_baseline: Mapping[str, Mapping[str, object]],
) -> tuple[ReconciliationCheckResult, ...]:
    baseline_actual = scenario_results["baseline"].annual_actual_energy_kwh
    checks: list[ReconciliationCheckResult] = []
    for scenario_id in CANONICAL_SCENARIO_IDS:
        gain_record = energy_gain_vs_baseline[scenario_id]
        expected_gain = scenario_results[scenario_id].annual_actual_energy_kwh - baseline_actual
        recorded = gain_record.get("energy_gain_vs_baseline_kwh")
        basis = gain_record.get("basis")
        passed = (
            isinstance(recorded, int | float)
            and abs(float(recorded) - expected_gain) <= ENERGY_TOLERANCE_KWH
            and basis == "annual_actual_energy_kwh"
        )
        checks.append(
            ReconciliationCheckResult(
                name=f"{scenario_id}_baseline_relative_energy_gain_uses_annual_ac_energy",
                passed=passed,
                message="OK"
                if passed
                else (
                    f"{scenario_id} baseline-relative energy gain must be "
                    "scenario annual_actual_energy_kwh minus baseline annual_actual_energy_kwh."
                ),
                details={
                    "basis": basis,
                    "recorded_energy_gain_vs_baseline_kwh": recorded,
                    "expected_energy_gain_vs_baseline_kwh": expected_gain,
                    "baseline_annual_actual_energy_kwh": baseline_actual,
                },
            )
        )
    return tuple(checks)


def _warnings_check(
    warnings: tuple[Mapping[str, object], ...],
) -> ReconciliationCheckResult:
    blocking = [warning for warning in warnings if warning.get("blocking") is True]
    passed = not blocking
    return ReconciliationCheckResult(
        name="no_blocking_assumption_warnings",
        passed=passed,
        message="OK"
        if passed
        else "Comparison has blocking assumption warnings and cannot be ranked.",
        details={
            "warning_count": len(warnings),
            "warning_codes": [w.get("code") for w in warnings],
            "blocking_warning_codes": [w.get("code") for w in blocking],
        },
    )


def _ranking_checks(
    *,
    ranking: tuple[ScenarioRankingEntry, ...],
    economic_results: Mapping[str, EconomicResult],
    preliminary_reconciliation_passed: bool,
) -> tuple[ReconciliationCheckResult, ...]:
    if not preliminary_reconciliation_passed:
        return (
            ReconciliationCheckResult(
                name="ranking_blocked_until_reconciliation_passes",
                passed=False,
                message="Ranking was not produced because reconciliation failed.",
            ),
        )
    ranking_count_passed = len(ranking) == len(CANONICAL_SCENARIO_IDS)
    ordered = sorted(
        CANONICAL_SCENARIO_IDS,
        key=lambda scenario_id: (
            -economic_results[scenario_id].net_annual_benefit_sar,
            scenario_id,
        ),
    )
    actual_order = [entry.scenario_id for entry in ranking]
    order_passed = actual_order == ordered
    return (
        ReconciliationCheckResult(
            name="exactly_one_ranking_produced_for_valid_run",
            passed=ranking_count_passed,
            message="OK"
            if ranking_count_passed
            else (
                "A valid comparison must produce one ranked list containing baseline, "
                "reactive, and coating exactly once."
            ),
            details={
                "ranking_row_count": len(ranking),
                "expected_scenario_ids": list(CANONICAL_SCENARIO_IDS),
                "actual_scenario_ids": actual_order,
            },
        ),
        ReconciliationCheckResult(
            name="ranking_sorted_by_net_annual_benefit",
            passed=order_passed,
            message="OK" if order_passed else "Ranking is not sorted by T4 net_annual_benefit_sar.",
            details={
                "expected_order": ordered,
                "actual_order": actual_order,
            },
        ),
    )


def _rank_scenarios(
    *,
    scenario_results: Mapping[str, AnnualScenarioResult],
    economic_results: Mapping[str, EconomicResult],
    energy_gain_vs_baseline: Mapping[str, Mapping[str, object]],
) -> tuple[ScenarioRankingEntry, ...]:
    ordered = sorted(
        CANONICAL_SCENARIO_IDS,
        key=lambda scenario_id: (
            -economic_results[scenario_id].net_annual_benefit_sar,
            scenario_id,
        ),
    )
    entries: list[ScenarioRankingEntry] = []
    previous_value: float | None = None
    current_rank = 0
    for position, scenario_id in enumerate(ordered, start=1):
        value = economic_results[scenario_id].net_annual_benefit_sar
        tied_with_previous = (
            previous_value is not None and abs(value - previous_value) <= RANKING_TOLERANCE_SAR
        )
        if not tied_with_previous:
            current_rank = position
        gain = energy_gain_vs_baseline[scenario_id]["energy_gain_vs_baseline_kwh"]
        entries.append(
            ScenarioRankingEntry(
                rank=current_rank,
                scenario_id=scenario_id,
                net_annual_benefit_sar=value,
                annual_actual_energy_kwh=scenario_results[scenario_id].annual_actual_energy_kwh,
                energy_gain_vs_baseline_kwh=float(cast(float, gain)),
                tied_with_previous=tied_with_previous,
            )
        )
        previous_value = value
    return tuple(entries)


def _build_recommendation(
    *,
    ranking: tuple[ScenarioRankingEntry, ...],
    scenario_results: Mapping[str, AnnualScenarioResult],
    economic_results: Mapping[str, EconomicResult],
    energy_gain_vs_baseline: Mapping[str, Mapping[str, object]],
    assumptions: tuple[Mapping[str, object], ...],
    warnings: tuple[Mapping[str, object], ...],
    traceability: Mapping[str, object],
    reconciliation_report: ReconciliationReport,
    config: SolarCleanConfig,
    registry: ParameterRegistry,
    weather: WeatherDataset,
) -> Recommendation:
    tier, status_counts = _recommendation_evidence_tier(
        config=config,
        registry=registry,
        weather=weather,
    )
    caveat = (
        " This recommendation rests on provisional calibration parameters; see validation_status."
        if any(parameter.status != "validated" for parameter in registry.parameters)
        else ""
    )
    if not reconciliation_report.passed or not ranking:
        return Recommendation(
            valid=False,
            calculation_valid=False,
            recommendation_tier=tier,
            decision_grade=False,
            parameter_status_counts=MappingProxyType(status_counts),
            winner=None,
            ordered_scenario_ids=(),
            tied_winners=(),
            decisive_margin_sar=None,
            kpi_snapshot={},
            assumptions=assumptions,
            warnings=warnings,
            traceability=traceability,
            message=(
                "No recommendation produced because calculation reconciliation failed." + caveat
            ),
        )
    top_value = ranking[0].net_annual_benefit_sar
    tied_winners = tuple(
        entry.scenario_id
        for entry in ranking
        if abs(entry.net_annual_benefit_sar - top_value) <= RANKING_TOLERANCE_SAR
    )
    winner = tied_winners[0] if len(tied_winners) == 1 else None
    decisive_margin = None
    if len(ranking) > 1:
        decisive_margin = top_value - ranking[1].net_annual_benefit_sar
    snapshot = {
        scenario_id: {
            "annual_actual_energy_kwh": scenario_results[scenario_id].annual_actual_energy_kwh,
            "energy_gain_vs_baseline_kwh": energy_gain_vs_baseline[scenario_id][
                "energy_gain_vs_baseline_kwh"
            ],
            "net_annual_benefit_sar": economic_results[scenario_id].net_annual_benefit_sar,
            "total_annual_cost_sar": economic_results[scenario_id].total_annual_cost_sar,
            "roi": economic_results[scenario_id].roi,
            "payback_years": economic_results[scenario_id].payback_years,
            **_incremental_mitigation_summary(
                scenario_id=scenario_id,
                economic_results=economic_results,
            ),
        }
        for scenario_id in CANONICAL_SCENARIO_IDS
    }
    if winner is None:
        message = "Top scenarios are tied within the configured ranking tolerance."
    else:
        message = f"{tier.replace('_', ' ').title()} winner under current assumptions: {winner}."
    message += caveat
    return Recommendation(
        valid=tier != "exploratory",
        calculation_valid=True,
        recommendation_tier=tier,
        decision_grade=tier == "decision_grade",
        parameter_status_counts=MappingProxyType(status_counts),
        winner=winner,
        ordered_scenario_ids=tuple(entry.scenario_id for entry in ranking),
        tied_winners=tied_winners,
        decisive_margin_sar=decisive_margin,
        kpi_snapshot=MappingProxyType(snapshot),
        assumptions=assumptions,
        warnings=warnings,
        traceability=traceability,
        message=message,
    )


def _recommendation_evidence_tier(
    *,
    config: SolarCleanConfig,
    registry: ParameterRegistry,
    weather: WeatherDataset,
) -> tuple[str, dict[str, int]]:
    """Grade evidence independently from arithmetic/reconciliation validity."""

    counts = {status: 0 for status in ("validated", "provisional", "blocked", "unsourced")}
    for parameter in registry.parameters:
        counts[parameter.status] = counts.get(parameter.status, 0) + 1
    full_year = _simulation_period_is_full_year(config)
    credible_weather = config.weather.provider == "nasa_power" and not bool(
        weather.metadata.get("test_only", False)
    )
    if counts["blocked"] or counts["unsourced"] or not full_year or not credible_weather:
        return "exploratory", counts
    if counts["provisional"]:
        return "calibrated", counts
    return "decision_grade", counts


def _daily_summaries(
    scenario_results: Mapping[str, AnnualScenarioResult],
) -> dict[str, tuple[Mapping[str, object], ...]]:
    # Running total of (scenario daily AC energy - baseline daily AC energy).
    # All scenarios share one weather/event context, so dates align 1:1; the
    # final value per scenario equals its annual energy_gain_vs_baseline_kwh.
    baseline_daily_actual = {
        day.date.isoformat(): day.actual_energy_kwh
        for day in scenario_results["baseline"].daily_results
    }
    summaries: dict[str, tuple[Mapping[str, object], ...]] = {}
    for scenario_id in CANONICAL_SCENARIO_IDS:
        records = []
        cumulative_gain = 0.0
        for record in scenario_results[scenario_id].to_daily_frame().to_dict(orient="records"):
            typed = {str(key): value for key, value in record.items()}
            typed["scenario_id"] = scenario_id
            day_date = typed.get("date")
            actual = typed.get("actual_energy_kwh")
            if day_date in baseline_daily_actual and isinstance(actual, int | float):
                cumulative_gain += float(actual) - baseline_daily_actual[day_date]
                typed["cumulative_energy_gain_vs_baseline_kwh"] = cumulative_gain
            records.append(MappingProxyType(typed))
        summaries[scenario_id] = tuple(records)
    return summaries


def _annual_summaries(
    *,
    scenario_results: Mapping[str, AnnualScenarioResult],
    economic_results: Mapping[str, EconomicResult],
    energy_gain_vs_baseline: Mapping[str, Mapping[str, object]],
    operational_by_scenario: Mapping[str, OperationalQuantities],
    weather_checksum: str,
    event_tape_checksum: str,
) -> dict[str, Mapping[str, object]]:
    summaries: dict[str, Mapping[str, object]] = {}
    for scenario_id in CANONICAL_SCENARIO_IDS:
        result = scenario_results[scenario_id]
        economic = economic_results[scenario_id]
        record = result.summary()
        record["scenario_id"] = scenario_id
        record["weather_checksum"] = weather_checksum
        record["event_tape_checksum"] = event_tape_checksum
        record.update(energy_gain_vs_baseline[scenario_id])
        for key, value in operational_by_scenario[scenario_id].to_record().items():
            record[f"annual_operational_{key}"] = value
        record.update(
            _annual_operational_extension_summary(
                scenario_id=scenario_id,
                result=result,
                operational=operational_by_scenario[scenario_id],
            )
        )
        record.update(_annual_water_balance_summary(result))
        record.update(_economic_summary(economic))
        record.update(
            _incremental_mitigation_summary(
                scenario_id=scenario_id,
                economic_results=economic_results,
            )
        )
        summaries[scenario_id] = MappingProxyType(record)
    return summaries


def _annual_water_balance_summary(result: AnnualScenarioResult) -> dict[str, object]:
    """Annual totals of the coating's stored daily water diagnostics.

    Zero for scenarios without the extensions (baseline/reactive harvest no
    water), so the CSV columns stay uniform across scenarios. Condensed water
    is dew that formed on the coated surface (it drives passive cleaning);
    collected water is the smaller share routed to storage, which stays zero
    unless the config enables collection efficiencies.
    """
    return {
        "annual_condensed_water_liters": _sum_daily_extension(result, "condensed_water_liters"),
        "annual_collected_water_liters": _sum_daily_extension(
            result, "actually_collected_water_liters"
        ),
    }


def _annual_operational_extension_summary(
    *,
    scenario_id: str,
    result: AnnualScenarioResult,
    operational: OperationalQuantities,
) -> dict[str, object]:
    if scenario_id != "reactive":
        return {}
    return {
        "annual_operational_whole_farm_survey_count": _sum_daily_extension(
            result,
            "whole_farm_survey_count",
        ),
        "annual_operational_block_or_cohort_inspection_count": _sum_daily_extension(
            result,
            "block_or_cohort_inspection_count",
            default=float(operational.inspections_count),
        ),
        "annual_operational_cleaning_dispatch_count": _sum_daily_extension(
            result,
            "cleaning_dispatch_count",
            default=float(operational.cleaning_actions_count),
        ),
        "annual_operational_panels_cleaned": _sum_daily_extension(result, "panels_cleaned"),
    }


def _sum_daily_extension(
    result: AnnualScenarioResult,
    key: str,
    *,
    default: float = 0.0,
) -> float:
    values = [
        _numeric_value(day.extensions[key], label=f"daily extension {key}")
        for day in result.daily_results
        if key in day.extensions
    ]
    if not values:
        return default
    return sum(values)


def _numeric_value(value: object, *, label: str) -> float:
    if not isinstance(value, int | float | str):
        raise ValueError(f"{label} must be numeric.")
    return float(value)


def _event_summaries(
    scenario_results: Mapping[str, AnnualScenarioResult],
) -> dict[str, Mapping[str, object]]:
    summaries: dict[str, Mapping[str, object]] = {}
    for scenario_id in CANONICAL_SCENARIO_IDS:
        events = scenario_results[scenario_id].events
        count_by_type: dict[str, int] = {}
        for event in events:
            count_by_type[event.event_type] = count_by_type.get(event.event_type, 0) + 1
        summaries[scenario_id] = MappingProxyType(
            {
                "scenario_id": scenario_id,
                "event_count": len(events),
                "event_count_by_type": count_by_type,
                "event_log_reference": "scenario_events.csv",
            }
        )
    return summaries


def _economic_summary(result: EconomicResult) -> Mapping[str, object]:
    return MappingProxyType(
        {
            "scenario_id": result.scenario_name,
            "annual_revenue_sar": result.annual_revenue_sar,
            "annualized_capex_sar": result.annualized_capex_sar,
            "annual_opex_sar": result.annual_opex_sar,
            "total_annual_cost_sar": result.total_annual_cost_sar,
            "net_annual_benefit_sar": result.net_annual_benefit_sar,
            "roi": result.roi,
            "payback_years": result.payback_years,
            "effective_lcoe_sar_per_kwh": result.effective_lcoe_sar_per_kwh,
            "total_capex_sar": result.total_capex_sar,
            "capital_recovery_life_years": result.capital_recovery_life_years,
            "cost_component_count": len(result.cost_breakdown),
        }
    )


def _incremental_mitigation_summary(
    *,
    scenario_id: str,
    economic_results: Mapping[str, EconomicResult],
) -> dict[str, object]:
    baseline = economic_results["baseline"]
    scenario = economic_results[scenario_id]
    incremental_revenue = scenario.annual_revenue_sar - baseline.annual_revenue_sar
    incremental_annual_cost = scenario.total_annual_cost_sar - baseline.total_annual_cost_sar
    incremental_opex = scenario.annual_opex_sar - baseline.annual_opex_sar
    incremental_capex = scenario.total_capex_sar - baseline.total_capex_sar
    incremental_net = incremental_revenue - incremental_annual_cost
    incremental_roi = None
    incremental_payback = None
    if scenario_id != "baseline":
        incremental_roi = _safe_optional_divide(
            incremental_net,
            incremental_annual_cost,
        )
        annual_cash_after_opex = incremental_revenue - incremental_opex
        incremental_payback = _incremental_payback_years(
            incremental_capex_sar=incremental_capex,
            annual_cash_after_opex_sar=annual_cash_after_opex,
        )
    return {
        "incremental_revenue_vs_baseline_sar": incremental_revenue,
        "incremental_annual_cost_vs_baseline_sar": incremental_annual_cost,
        "incremental_net_annual_benefit_vs_baseline_sar": incremental_net,
        "incremental_roi_vs_baseline": incremental_roi,
        "incremental_payback_years_vs_baseline": incremental_payback,
        "roi_payback_basis": "incremental_vs_baseline",
    }


def _safe_optional_divide(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _incremental_payback_years(
    *,
    incremental_capex_sar: float,
    annual_cash_after_opex_sar: float,
) -> float | None:
    if annual_cash_after_opex_sar <= 0:
        return None
    if incremental_capex_sar <= 0:
        return 0.0
    return incremental_capex_sar / annual_cash_after_opex_sar


def _write_comparison_package(
    *,
    output_dir: Path,
    writer: OutputWriter,
    config: SolarCleanConfig,
    weather: WeatherDataset,
    profile: CleanEnergyProfile,
    event_tape: ExogenousEventTape,
    run_id: str,
    scenario_results: Mapping[str, AnnualScenarioResult],
    daily_summaries: Mapping[str, tuple[Mapping[str, object], ...]],
    annual_summaries: Mapping[str, Mapping[str, object]],
    economic_results: Mapping[str, EconomicResult],
    cost_reconciliation_checks: Mapping[str, tuple[CostReconciliationCheck, ...]],
    ranking: tuple[ScenarioRankingEntry, ...],
    recommendation: Recommendation,
    validation_status: Mapping[str, object],
    reconciliation_report: ReconciliationReport,
    traceability: Mapping[str, object],
) -> tuple[str, ...]:
    del config
    artifacts: list[str] = []
    writer.write_config(output_dir)
    artifacts.append("config_resolved.yaml")
    writer.write_weather(output_dir, weather)
    artifacts.append("weather_hourly.csv")
    writer.write_clean_energy(output_dir, profile)
    artifacts.extend(["clean_energy_hourly.csv", "daily_clean_energy.csv"])
    writer.write_daily_weather_diagnostics(output_dir, weather, profile)
    artifacts.append("daily_weather_diagnostics.csv")

    (output_dir / "event_tape.json").write_text(event_tape.to_json(), encoding="utf-8")
    artifacts.append("event_tape.json")
    write_json_report(output_dir / "comparison_metadata.json", dict(traceability))
    artifacts.append("comparison_metadata.json")
    writer.write_metadata(output_dir, dict(traceability))
    artifacts.append("metadata.json")

    daily_frame = _records_frame(
        record for scenario_id in CANONICAL_SCENARIO_IDS for record in daily_summaries[scenario_id]
    )
    daily_frame.to_csv(
        output_dir / "scenario_daily_summary.csv",
        index=False,
        float_format=writer.config.output.csv_float_format,
    )
    artifacts.append("scenario_daily_summary.csv")

    annual_frame = _records_frame(
        annual_summaries[scenario_id] for scenario_id in CANONICAL_SCENARIO_IDS
    )
    annual_frame.to_csv(
        output_dir / "scenario_annual_summary.csv",
        index=False,
        float_format=writer.config.output.csv_float_format,
    )
    artifacts.append("scenario_annual_summary.csv")

    cost_frame = _records_frame(
        _cost_summary_records(
            economic_results=economic_results,
            cost_reconciliation_checks=cost_reconciliation_checks,
        )
    )
    cost_frame.to_csv(
        output_dir / "scenario_cost_summary.csv",
        index=False,
        float_format=writer.config.output.csv_float_format,
    )
    artifacts.append("scenario_cost_summary.csv")

    events_frame = _records_frame(_event_records(scenario_results))
    events_frame.to_csv(output_dir / "scenario_events.csv", index=False)
    artifacts.append("scenario_events.csv")

    write_json_report(
        output_dir / "scenario_ranking.json",
        {
            "run_id": run_id,
            "ranking_tolerance_sar": RANKING_TOLERANCE_SAR,
            "ranking": [entry.to_record() for entry in ranking],
        },
    )
    artifacts.append("scenario_ranking.json")
    recommendation_record = recommendation.to_record()
    recommendation_record["validation_status"] = _json_safe_mapping(validation_status)
    write_json_report(output_dir / "recommendation.json", recommendation_record)
    artifacts.append("recommendation.json")
    write_json_report(output_dir / "reconciliation_report.json", reconciliation_report.to_record())
    artifacts.append("reconciliation_report.json")

    plot_paths = write_comparison_diagnostic_plots(
        output_dir=output_dir,
        daily_summary=daily_frame,
        annual_summary=annual_frame,
        cost_summary=cost_frame,
    )
    artifacts.extend(path.name for path in plot_paths)
    return tuple(artifacts)


def _cost_summary_records(
    *,
    economic_results: Mapping[str, EconomicResult],
    cost_reconciliation_checks: Mapping[str, tuple[CostReconciliationCheck, ...]],
) -> tuple[Mapping[str, object], ...]:
    records: list[Mapping[str, object]] = []
    for scenario_id in CANONICAL_SCENARIO_IDS:
        economic = economic_results[scenario_id]
        base = dict(_economic_summary(economic))
        if not economic.cost_breakdown:
            record = dict(base)
            record.update(
                {
                    "component_name": "none",
                    "category": "",
                    "amount_sar": 0.0,
                    "unit": "",
                    "source": "",
                    "source_status": "",
                    "notes": "",
                }
            )
            records.append(MappingProxyType(record))
            continue
        for component in economic.cost_breakdown:
            record = dict(base)
            record.update(
                {
                    "component_name": component.name,
                    "category": component.category,
                    "amount_sar": component.amount_sar,
                    "unit": component.unit,
                    "source": component.source,
                    "source_status": component.source_status,
                    "notes": component.notes or "",
                    "cost_reconciliation_messages": "; ".join(
                        check.message
                        for check in cost_reconciliation_checks.get(scenario_id, ())
                        if check.cost_component_name.lower() == component.name.lower()
                    ),
                }
            )
            records.append(MappingProxyType(record))
    return tuple(records)


def _event_records(
    scenario_results: Mapping[str, AnnualScenarioResult],
) -> tuple[Mapping[str, object], ...]:
    events: list[DomainEvent] = []
    for scenario_id in CANONICAL_SCENARIO_IDS:
        events.extend(scenario_results[scenario_id].events)
    return tuple(MappingProxyType(event.to_record()) for event in ordered_domain_events(events))


def _same_value_check(
    *,
    name: str,
    values: Mapping[str, str],
    label: str,
) -> ReconciliationCheckResult:
    unique = set(values.values())
    passed = len(unique) == 1
    return ReconciliationCheckResult(
        name=name,
        passed=passed,
        message="OK" if passed else f"Scenarios did not share exactly one {label}.",
        details=values,
    )


def _quantity_event_check(
    *,
    name: str,
    quantity_name: str,
    quantity_value: float,
    event_count: int,
) -> ReconciliationCheckResult:
    passed = abs(quantity_value - event_count) <= 1e-9
    return ReconciliationCheckResult(
        name=name,
        passed=passed,
        message="OK"
        if passed
        else (
            f"{quantity_name}={quantity_value:g} does not match event log count {event_count:g}."
        ),
        details={
            "quantity_name": quantity_name,
            "quantity_value": quantity_value,
            "event_count": event_count,
        },
    )


def _event_count(events: tuple[DomainEvent, ...], event_type: str) -> int:
    return sum(1 for event in events if event.event_type == event_type)


def _scenario_input_checksums(
    *,
    weather_checksum: str,
    event_tape_checksum: str,
) -> Mapping[str, Mapping[str, str]]:
    return MappingProxyType(
        {
            scenario_id: MappingProxyType(
                {
                    "weather_checksum": weather_checksum,
                    "event_tape_checksum": event_tape_checksum,
                }
            )
            for scenario_id in CANONICAL_SCENARIO_IDS
        }
    )


def _resolve_scenario_order(order: Sequence[str] | None) -> tuple[str, ...]:
    if order is None:
        return CANONICAL_SCENARIO_IDS
    resolved = tuple(str(item) for item in order)
    if len(resolved) != len(CANONICAL_SCENARIO_IDS) or set(resolved) != set(CANONICAL_SCENARIO_IDS):
        raise ValueError("scenario_order must contain baseline, reactive, and coating exactly once")
    return resolved


def _weather_checksum(weather: WeatherDataset) -> str:
    return _dataframe_checksum(weather.hourly)


def _dataframe_checksum(frame: pd.DataFrame) -> str:
    payload = frame.to_csv(index=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _config_checksum(config: SolarCleanConfig) -> str:
    return _payload_checksum(config.model_dump(mode="json"))


def _payload_checksum(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _records_frame(records: Sequence[Mapping[str, object]] | Any) -> pd.DataFrame:
    normalized = [_flatten_record_for_csv(record) for record in records]
    return pd.DataFrame.from_records(normalized)


def _flatten_record_for_csv(record: Mapping[str, object]) -> dict[str, object]:
    flattened: dict[str, object] = {}
    for key, value in record.items():
        safe = _json_safe(value)
        flattened[str(key)] = (
            json.dumps(safe, sort_keys=True) if isinstance(safe, dict | list) else safe
        )
    return flattened


def _json_safe_mapping(mapping: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _json_safe(value) for key, value in mapping.items()}


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator > 0.0 else 0.0
