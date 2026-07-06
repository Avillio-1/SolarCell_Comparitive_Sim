from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from solarclean.domain.economics.contracts import (
    CostCategory,
    CostComponent,
    ScenarioEconomicInputs,
)
from solarclean.domain.scenario.contracts import OperationalQuantities


@dataclass(frozen=True)
class UnitCostRate:
    """Traceable cost rate supplied by calibration/configuration."""

    amount_sar_per_unit: float
    quantity_unit: str
    source: str
    source_status: str = "unspecified"
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.amount_sar_per_unit < 0:
            raise ValueError("amount_sar_per_unit must be non-negative.")
        if not self.quantity_unit:
            raise ValueError("quantity_unit must not be empty.")
        if not self.source:
            raise ValueError("source must not be empty.")
        if not self.source_status:
            raise ValueError("source_status must not be empty.")


@dataclass(frozen=True)
class ReactiveCostRates:
    """Optional rate card for turning recorded reactive operations into costs."""

    inspection: UnitCostRate | None = None
    cleaning_action: UnitCostRate | None = None
    crew_hour: UnitCostRate | None = None
    drone_flight_hour: UnitCostRate | None = None
    water_liter: UnitCostRate | None = None
    energy_kwh: UnitCostRate | None = None


def build_baseline_economic_inputs(
    *,
    actual_energy_kwh: float,
    clean_energy_kwh: float,
    operational_quantities: OperationalQuantities | None = None,
    cost_components: tuple[CostComponent, ...] = (),
    useful_life_years: float | None = None,
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
        useful_life_years=useful_life_years,
    )


def build_reactive_cost_components(
    *,
    operational_quantities: OperationalQuantities,
    rates: ReactiveCostRates,
    additional_components: tuple[CostComponent, ...] = (),
) -> tuple[CostComponent, ...]:
    """Map annual reactive operations to OPEX components using supplied rates only."""

    components: list[CostComponent] = []

    _append_rated_component(
        components,
        name="reactive inspection operations",
        category="opex",
        quantity_name="inspections_count",
        quantity_value=float(operational_quantities.inspections_count),
        rate=rates.inspection,
    )
    _append_rated_component(
        components,
        name="reactive cleaning equipment use",
        category="opex",
        quantity_name="cleaning_actions_count",
        quantity_value=float(operational_quantities.cleaning_actions_count),
        rate=rates.cleaning_action,
    )
    _append_rated_component(
        components,
        name="reactive crew labour",
        category="opex",
        quantity_name="crew_hours",
        quantity_value=operational_quantities.crew_hours,
        rate=rates.crew_hour,
    )
    _append_rated_component(
        components,
        name="reactive drone flight operations",
        category="opex",
        quantity_name="drone_flight_hours",
        quantity_value=operational_quantities.drone_flight_hours,
        rate=rates.drone_flight_hour,
    )
    _append_rated_component(
        components,
        name="reactive water use",
        category="opex",
        quantity_name="water_liters",
        quantity_value=operational_quantities.water_liters,
        rate=rates.water_liter,
    )
    _append_rated_component(
        components,
        name="reactive energy use",
        category="opex",
        quantity_name="energy_used_kwh",
        quantity_value=operational_quantities.energy_used_kwh,
        rate=rates.energy_kwh,
    )

    components.extend(additional_components)
    return tuple(components)


def build_reactive_economic_inputs(
    *,
    actual_energy_kwh: float,
    clean_energy_kwh: float,
    operational_quantities: OperationalQuantities,
    cost_components: tuple[CostComponent, ...],
    useful_life_years: float | None = None,
) -> ScenarioEconomicInputs:
    return ScenarioEconomicInputs(
        scenario_name="reactive",
        actual_energy_kwh=actual_energy_kwh,
        clean_energy_kwh=clean_energy_kwh,
        operational_quantities=operational_quantities,
        cost_components=cost_components,
        useful_life_years=useful_life_years,
    )


def build_coating_cost_components_from_basis(
    *,
    coating_cost_basis: Mapping[str, object],
    application_labour_rate: UnitCostRate | None = None,
    process_energy_rate: UnitCostRate | None = None,
) -> tuple[CostComponent, ...]:
    """Map T3 coating cost-basis quantities to T4 cost components.

    The coating scenario reports the basis, but T4 owns the componentized
    valuation and any optional rates such as application labour or process
    energy.
    """

    source_status = _basis_str(coating_cost_basis, "source_status", "unspecified")
    basis_notes = _coating_basis_notes(coating_cost_basis)

    components = [
        _basis_component(
            coating_cost_basis=coating_cost_basis,
            key="material_cost_total",
            name="coating material capex",
            category="capex",
            source_status=source_status,
            notes=basis_notes,
        ),
        _basis_component(
            coating_cost_basis=coating_cost_basis,
            key="surface_preparation_cost_total",
            name="coating surface preparation capex",
            category="capex",
            source_status=source_status,
            notes=basis_notes,
        ),
        _basis_component(
            coating_cost_basis=coating_cost_basis,
            key="fixed_equipment_setup_cost",
            name="coating fixed equipment capex",
            category="capex",
            source_status=source_status,
            notes=basis_notes,
        ),
        _basis_component(
            coating_cost_basis=coating_cost_basis,
            key="water_collection_infrastructure_cost",
            name="coating water collection infrastructure capex",
            category="capex",
            source_status=source_status,
            notes=basis_notes,
        ),
        _basis_component(
            coating_cost_basis=coating_cost_basis,
            key="maintenance_cost_per_year",
            name="coating maintenance opex",
            category="opex",
            source_status=source_status,
            notes=basis_notes,
        ),
    ]

    _append_rated_component(
        components,
        name="coating application labour capex",
        category="capex",
        quantity_name="application_labor_hours",
        quantity_value=_basis_float(coating_cost_basis, "application_labor_hours"),
        rate=application_labour_rate,
    )
    _append_rated_component(
        components,
        name="coating process energy capex",
        category="capex",
        quantity_name="process_energy_kwh",
        quantity_value=_basis_float(coating_cost_basis, "process_energy_kwh"),
        rate=process_energy_rate,
    )

    return tuple(components)


def build_coating_economic_inputs(
    *,
    actual_energy_kwh: float,
    clean_energy_kwh: float,
    operational_quantities: OperationalQuantities,
    cost_components: tuple[CostComponent, ...],
    useful_life_years: float | None = None,
) -> ScenarioEconomicInputs:
    return ScenarioEconomicInputs(
        scenario_name="coating",
        actual_energy_kwh=actual_energy_kwh,
        clean_energy_kwh=clean_energy_kwh,
        operational_quantities=operational_quantities,
        cost_components=cost_components,
        useful_life_years=useful_life_years,
    )


def _reject_soiling_loss_costs(cost_components: tuple[CostComponent, ...]) -> None:
    blocked_patterns = (
        ("soiling", "loss"),
        ("dust", "loss"),
        ("lost", "revenue"),
        ("revenue", "loss"),
    )

    for component in cost_components:
        normalized_name = component.name.lower().replace("-", " ")

        for first, second in blocked_patterns:
            if first in normalized_name and second in normalized_name:
                raise ValueError(
                    "Baseline soiling loss must not be added as a separate cost. "
                    "It is already represented through reduced actual_energy_kwh."
                )


def _append_rated_component(
    components: list[CostComponent],
    *,
    name: str,
    category: CostCategory,
    quantity_name: str,
    quantity_value: float,
    rate: UnitCostRate | None,
) -> None:
    if rate is None:
        return
    if quantity_value < 0:
        raise ValueError(f"{quantity_name} must be non-negative.")

    components.append(
        CostComponent(
            name=name,
            category=category,
            amount_sar=quantity_value * rate.amount_sar_per_unit,
            unit=_money_unit(category),
            source=rate.source,
            notes=_combine_notes(
                f"{quantity_name}={quantity_value:g} {rate.quantity_unit}; "
                f"unit_rate={rate.amount_sar_per_unit:g} SAR/{rate.quantity_unit}",
                rate.notes,
            ),
            source_status=rate.source_status,
        )
    )


def _basis_component(
    *,
    coating_cost_basis: Mapping[str, object],
    key: str,
    name: str,
    category: CostCategory,
    source_status: str,
    notes: str,
) -> CostComponent:
    return CostComponent(
        name=name,
        category=category,
        amount_sar=_basis_float(coating_cost_basis, key),
        unit=_money_unit(category),
        source="coating_cost_basis",
        notes=notes,
        source_status=source_status,
    )


def _basis_float(
    coating_cost_basis: Mapping[str, object],
    key: str,
) -> float:
    value = coating_cost_basis.get(key)
    if not isinstance(value, int | float):
        raise ValueError(f"coating_cost_basis[{key!r}] must be numeric.")
    if value < 0:
        raise ValueError(f"coating_cost_basis[{key!r}] must be non-negative.")
    return float(value)


def _basis_str(
    coating_cost_basis: Mapping[str, object],
    key: str,
    default: str,
) -> str:
    value = coating_cost_basis.get(key, default)
    return str(value) if value else default


def _basis_optional_float(
    coating_cost_basis: Mapping[str, object],
    key: str,
) -> float | None:
    value = coating_cost_basis.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise ValueError(f"coating_cost_basis[{key!r}] must be numeric or None.")
    if value < 0:
        raise ValueError(f"coating_cost_basis[{key!r}] must be non-negative.")
    return float(value)


def _coating_basis_notes(coating_cost_basis: Mapping[str, object]) -> str:
    useful_life = _basis_float(coating_cost_basis, "useful_life_years")
    reapplication = _basis_optional_float(coating_cost_basis, "reapplication_interval_years")
    coated_area = _basis_float(coating_cost_basis, "total_coated_area_m2")
    assumption_level = _basis_str(coating_cost_basis, "assumption_level", "unspecified")
    return (
        f"total_coated_area_m2={coated_area:g}; useful_life_years={useful_life:g}; "
        f"reapplication_interval_years={reapplication}; assumption_level={assumption_level}"
    )


def _money_unit(category: CostCategory) -> str:
    if category == "capex":
        return "SAR"
    return "SAR/year"


def _combine_notes(first: str, second: str | None) -> str:
    if second:
        return f"{first}; {second}"
    return first
