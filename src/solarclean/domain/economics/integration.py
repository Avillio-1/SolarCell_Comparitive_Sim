from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from solarclean.domain.economics.adapters import (
    build_baseline_economic_inputs,
    build_coating_economic_inputs,
    build_reactive_economic_inputs,
)
from solarclean.domain.economics.contracts import (
    CostComponent,
    EconomicConfig,
    EconomicResult,
    ScenarioEconomicInputs,
)
from solarclean.domain.economics.engine import EconomicEngine
from solarclean.domain.economics.summary import (
    AnnualFinancialSummaryRow,
    build_annual_financial_summary,
)
from solarclean.domain.scenario.contracts import OperationalQuantities


@dataclass(frozen=True)
class AnnualScenarioOutput:
    """Thin T4 input contract for annual outputs from baseline/reactive/coating."""

    scenario_name: str
    actual_energy_kwh: float
    clean_energy_kwh: float
    operational_quantities: OperationalQuantities = field(default_factory=OperationalQuantities)
    cost_components: tuple[CostComponent, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.scenario_name:
            raise ValueError("scenario_name must not be empty.")
        if self.actual_energy_kwh < 0:
            raise ValueError("actual_energy_kwh must be non-negative.")
        if self.clean_energy_kwh < 0:
            raise ValueError("clean_energy_kwh must be non-negative.")


def build_economic_inputs_from_annual_output(
    output: AnnualScenarioOutput,
) -> ScenarioEconomicInputs:
    """Convert annual scenario outputs into T4 economic inputs."""

    scenario = output.scenario_name.lower()

    if scenario == "baseline" or scenario.startswith("baseline"):
        return build_baseline_economic_inputs(
            actual_energy_kwh=output.actual_energy_kwh,
            clean_energy_kwh=output.clean_energy_kwh,
            operational_quantities=output.operational_quantities,
            cost_components=output.cost_components,
        )

    if scenario == "reactive" or scenario.startswith("reactive"):
        return build_reactive_economic_inputs(
            actual_energy_kwh=output.actual_energy_kwh,
            clean_energy_kwh=output.clean_energy_kwh,
            operational_quantities=output.operational_quantities,
            cost_components=output.cost_components,
        )

    if scenario == "coating" or scenario.startswith("coating"):
        return build_coating_economic_inputs(
            actual_energy_kwh=output.actual_energy_kwh,
            clean_energy_kwh=output.clean_energy_kwh,
            operational_quantities=output.operational_quantities,
            cost_components=output.cost_components,
        )

    return ScenarioEconomicInputs(
        scenario_name=output.scenario_name,
        actual_energy_kwh=output.actual_energy_kwh,
        clean_energy_kwh=output.clean_energy_kwh,
        operational_quantities=output.operational_quantities,
        cost_components=output.cost_components,
    )


def evaluate_annual_scenario_outputs(
    *,
    outputs: tuple[AnnualScenarioOutput, ...],
    config: EconomicConfig,
) -> tuple[EconomicResult, ...]:
    """Apply the common economic engine to all annual scenario outputs."""

    engine = EconomicEngine(config)

    return tuple(
        engine.evaluate(build_economic_inputs_from_annual_output(output))
        for output in outputs
    )


def build_annual_financial_summary_from_outputs(
    *,
    outputs: tuple[AnnualScenarioOutput, ...],
    config: EconomicConfig,
) -> tuple[AnnualFinancialSummaryRow, ...]:
    results = evaluate_annual_scenario_outputs(outputs=outputs, config=config)
    return build_annual_financial_summary(results)