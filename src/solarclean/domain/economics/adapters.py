from __future__ import annotations

from solarclean.domain.economics.contracts import (
    CostComponent,
    ScenarioEconomicInputs,
)
from solarclean.domain.scenario.contracts import OperationalQuantities


def build_baseline_economic_inputs(
    *,
    actual_energy_kwh: float,
    clean_energy_kwh: float,
    operational_quantities: OperationalQuantities | None = None,
    cost_components: tuple[CostComponent, ...] = (),
) -> ScenarioEconomicInputs:
    """Build baseline economic inputs.

    Important:
    Baseline soiling loss is already represented through reduced actual_energy_kwh.
    Do not add a separate soiling-loss cost component here.
    """

    _reject_soiling_loss_costs(cost_components)

    return ScenarioEconomicInputs(
        scenario_name="baseline",
        actual_energy_kwh=actual_energy_kwh,
        clean_energy_kwh=clean_energy_kwh,
        operational_quantities=operational_quantities or OperationalQuantities(),
        cost_components=cost_components,
    )


def build_reactive_economic_inputs(
    *,
    actual_energy_kwh: float,
    clean_energy_kwh: float,
    operational_quantities: OperationalQuantities,
    cost_components: tuple[CostComponent, ...],
) -> ScenarioEconomicInputs:
    return ScenarioEconomicInputs(
        scenario_name="reactive",
        actual_energy_kwh=actual_energy_kwh,
        clean_energy_kwh=clean_energy_kwh,
        operational_quantities=operational_quantities,
        cost_components=cost_components,
    )


def build_coating_economic_inputs(
    *,
    actual_energy_kwh: float,
    clean_energy_kwh: float,
    operational_quantities: OperationalQuantities,
    cost_components: tuple[CostComponent, ...],
) -> ScenarioEconomicInputs:
    return ScenarioEconomicInputs(
        scenario_name="coating",
        actual_energy_kwh=actual_energy_kwh,
        clean_energy_kwh=clean_energy_kwh,
        operational_quantities=operational_quantities,
        cost_components=cost_components,
    )


def _reject_soiling_loss_costs(cost_components: tuple[CostComponent, ...]) -> None:
    for component in cost_components:
        normalized_name = component.name.lower().replace("-", " ")
        if "soiling" in normalized_name and "loss" in normalized_name:
            raise ValueError(
                "Baseline soiling loss must not be added as a separate cost. "
                "It is already represented through reduced actual_energy_kwh."
            )