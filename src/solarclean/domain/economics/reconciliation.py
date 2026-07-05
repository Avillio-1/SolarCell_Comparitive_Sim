from __future__ import annotations

from dataclasses import dataclass

from solarclean.domain.economics.contracts import CostComponent
from solarclean.domain.scenario.contracts import OperationalQuantities


@dataclass(frozen=True)
class CostReconciliationRule:
    """Expected cost = recorded operational quantity × unit rate."""

    cost_component_name: str
    quantity_name: str
    rate_sar_per_unit: float
    tolerance_sar: float = 1e-6

    def __post_init__(self) -> None:
        if not self.cost_component_name:
            raise ValueError("cost_component_name must not be empty.")
        if not self.quantity_name:
            raise ValueError("quantity_name must not be empty.")
        if self.rate_sar_per_unit < 0:
            raise ValueError("rate_sar_per_unit must be non-negative.")
        if self.tolerance_sar < 0:
            raise ValueError("tolerance_sar must be non-negative.")


@dataclass(frozen=True)
class CostReconciliationCheck:
    cost_component_name: str
    quantity_name: str
    quantity_value: float
    rate_sar_per_unit: float
    expected_amount_sar: float
    recorded_amount_sar: float | None
    difference_sar: float | None
    passed: bool
    message: str


def reconcile_operational_costs(
    *,
    operational_quantities: OperationalQuantities,
    cost_components: tuple[CostComponent, ...],
    rules: tuple[CostReconciliationRule, ...],
) -> tuple[CostReconciliationCheck, ...]:
    """Check whether recorded operational quantities reconcile with costs."""

    component_by_name = {
        component.name.lower(): component for component in cost_components
    }

    checks: list[CostReconciliationCheck] = []

    for rule in rules:
        quantity_value = _get_quantity_value(
            operational_quantities=operational_quantities,
            quantity_name=rule.quantity_name,
        )
        expected = quantity_value * rule.rate_sar_per_unit

        component = component_by_name.get(rule.cost_component_name.lower())

        if component is None:
            checks.append(
                CostReconciliationCheck(
                    cost_component_name=rule.cost_component_name,
                    quantity_name=rule.quantity_name,
                    quantity_value=quantity_value,
                    rate_sar_per_unit=rule.rate_sar_per_unit,
                    expected_amount_sar=expected,
                    recorded_amount_sar=None,
                    difference_sar=None,
                    passed=False,
                    message="Missing cost component.",
                )
            )
            continue

        difference = component.amount_sar - expected
        passed = abs(difference) <= rule.tolerance_sar

        checks.append(
            CostReconciliationCheck(
                cost_component_name=rule.cost_component_name,
                quantity_name=rule.quantity_name,
                quantity_value=quantity_value,
                rate_sar_per_unit=rule.rate_sar_per_unit,
                expected_amount_sar=expected,
                recorded_amount_sar=component.amount_sar,
                difference_sar=difference,
                passed=passed,
                message="OK" if passed else "Recorded cost does not match operational quantity.",
            )
        )

    return tuple(checks)


def all_reconciled(checks: tuple[CostReconciliationCheck, ...]) -> bool:
    return all(check.passed for check in checks)


def _get_quantity_value(
    *,
    operational_quantities: OperationalQuantities,
    quantity_name: str,
) -> float:
    if not hasattr(operational_quantities, quantity_name):
        raise ValueError(f"Unknown operational quantity: {quantity_name}")

    value = getattr(operational_quantities, quantity_name)

    if not isinstance(value, int | float):
        raise TypeError(f"Operational quantity {quantity_name} is not numeric.")

    return float(value)