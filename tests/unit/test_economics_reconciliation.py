from __future__ import annotations

from solarclean.domain.economics import (
    CostComponent,
    CostReconciliationRule,
    all_reconciled,
    reconcile_operational_costs,
)
from solarclean.domain.scenario.contracts import OperationalQuantities


def test_reconciliation_passes_when_costs_match_operational_quantities() -> None:
    operational = OperationalQuantities(
        crew_hours=10,
        water_liters=100,
    )
    cost_components = (
        CostComponent(
            name="labour opex",
            category="opex",
            amount_sar=300,
            unit="SAR/year",
            source="test",
        ),
        CostComponent(
            name="water opex",
            category="opex",
            amount_sar=50,
            unit="SAR/year",
            source="test",
        ),
    )
    rules = (
        CostReconciliationRule(
            cost_component_name="labour opex",
            quantity_name="crew_hours",
            rate_sar_per_unit=30,
        ),
        CostReconciliationRule(
            cost_component_name="water opex",
            quantity_name="water_liters",
            rate_sar_per_unit=0.5,
        ),
    )

    checks = reconcile_operational_costs(
        operational_quantities=operational,
        cost_components=cost_components,
        rules=rules,
    )

    assert all_reconciled(checks)
    assert all(check.message == "OK" for check in checks)


def test_reconciliation_fails_when_cost_does_not_match_quantity() -> None:
    operational = OperationalQuantities(crew_hours=10)
    cost_components = (
        CostComponent(
            name="labour opex",
            category="opex",
            amount_sar=250,
            unit="SAR/year",
            source="test",
        ),
    )
    rules = (
        CostReconciliationRule(
            cost_component_name="labour opex",
            quantity_name="crew_hours",
            rate_sar_per_unit=30,
        ),
    )

    checks = reconcile_operational_costs(
        operational_quantities=operational,
        cost_components=cost_components,
        rules=rules,
    )

    assert not all_reconciled(checks)
    assert checks[0].expected_amount_sar == 300
    assert checks[0].recorded_amount_sar == 250