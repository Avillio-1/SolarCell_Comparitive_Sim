from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from solarclean.domain.economics.adapters import (
    build_baseline_economic_inputs,
    build_coating_cost_components_from_basis,
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
    useful_life_years: float | None = None

    def __post_init__(self) -> None:
        if not self.scenario_name:
            raise ValueError("scenario_name must not be empty.")
        if self.actual_energy_kwh < 0:
            raise ValueError("actual_energy_kwh must be non-negative.")
        if self.clean_energy_kwh < 0:
            raise ValueError("clean_energy_kwh must be non-negative.")
        if self.useful_life_years is not None and self.useful_life_years <= 0:
            raise ValueError("useful_life_years must be positive when provided.")


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
            useful_life_years=output.useful_life_years,
        )

    if scenario == "reactive" or scenario.startswith("reactive"):
        return build_reactive_economic_inputs(
            actual_energy_kwh=output.actual_energy_kwh,
            clean_energy_kwh=output.clean_energy_kwh,
            operational_quantities=output.operational_quantities,
            cost_components=output.cost_components,
            useful_life_years=output.useful_life_years,
        )

    if scenario == "coating" or scenario.startswith("coating"):
        cost_components = output.cost_components or _coating_cost_components_from_metadata(
            output.metadata
        )
        return build_coating_economic_inputs(
            actual_energy_kwh=output.actual_energy_kwh,
            clean_energy_kwh=output.clean_energy_kwh,
            operational_quantities=output.operational_quantities,
            cost_components=cost_components,
            useful_life_years=output.useful_life_years
            or _coating_useful_life_years_from_metadata(output.metadata),
        )

    return ScenarioEconomicInputs(
        scenario_name=output.scenario_name,
        actual_energy_kwh=output.actual_energy_kwh,
        clean_energy_kwh=output.clean_energy_kwh,
        operational_quantities=output.operational_quantities,
        cost_components=output.cost_components,
        useful_life_years=output.useful_life_years,
    )


def evaluate_annual_scenario_outputs(
    *,
    outputs: tuple[AnnualScenarioOutput, ...],
    config: EconomicConfig,
) -> tuple[EconomicResult, ...]:
    """Apply the common economic engine to all annual scenario outputs."""

    engine = EconomicEngine(config)

    return tuple(
        engine.evaluate(build_economic_inputs_from_annual_output(output)) for output in outputs
    )


def build_annual_financial_summary_from_outputs(
    *,
    outputs: tuple[AnnualScenarioOutput, ...],
    config: EconomicConfig,
) -> tuple[AnnualFinancialSummaryRow, ...]:
    results = evaluate_annual_scenario_outputs(outputs=outputs, config=config)
    return build_annual_financial_summary(results)


def _coating_cost_components_from_metadata(
    metadata: Mapping[str, object],
) -> tuple[CostComponent, ...]:
    value = metadata.get("coating_cost_basis")
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise ValueError("metadata['coating_cost_basis'] must be a mapping.")
    return build_coating_cost_components_from_basis(
        coating_cost_basis={str(key): item for key, item in value.items()},
    )


def _coating_useful_life_years_from_metadata(
    metadata: Mapping[str, object],
) -> float | None:
    value = metadata.get("coating_cost_basis")
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("metadata['coating_cost_basis'] must be a mapping.")
    raw_life = value.get("useful_life_years")
    if raw_life is None:
        return None
    life = float(raw_life)
    if life <= 0:
        raise ValueError("metadata['coating_cost_basis']['useful_life_years'] must be positive.")
    return life
