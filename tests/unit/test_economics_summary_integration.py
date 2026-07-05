from __future__ import annotations

from solarclean.domain.economics import (
    AnnualScenarioOutput,
    CostComponent,
    EconomicConfig,
    build_annual_financial_summary_from_outputs,
    financial_summary_to_records,
)
from solarclean.domain.scenario.contracts import OperationalQuantities


def test_builds_annual_financial_summary_for_three_strategies() -> None:
    config = EconomicConfig(
        currency="SAR",
        tariff_sar_per_kwh=0.20,
        discount_rate=0.0,
        useful_life_years=5,
    )

    outputs = (
        AnnualScenarioOutput(
            scenario_name="baseline",
            actual_energy_kwh=10_000,
            clean_energy_kwh=11_000,
        ),
        AnnualScenarioOutput(
            scenario_name="reactive",
            actual_energy_kwh=10_500,
            clean_energy_kwh=11_000,
            operational_quantities=OperationalQuantities(
                crew_hours=10,
                water_liters=100,
            ),
            cost_components=(
                CostComponent(
                    name="labour opex",
                    category="opex",
                    amount_sar=300,
                    unit="SAR/year",
                    source="test",
                ),
            ),
        ),
        AnnualScenarioOutput(
            scenario_name="coating",
            actual_energy_kwh=10_800,
            clean_energy_kwh=11_000,
            operational_quantities=OperationalQuantities(
                coated_panel_count=100,
            ),
            cost_components=(
                CostComponent(
                    name="coating material capex",
                    category="capex",
                    amount_sar=1_000,
                    unit="SAR",
                    source="test",
                ),
            ),
        ),
    )

    rows = build_annual_financial_summary_from_outputs(
        outputs=outputs,
        config=config,
    )
    records = financial_summary_to_records(rows)

    assert len(rows) == 3
    assert [row.scenario_name for row in rows] == ["baseline", "reactive", "coating"]

    baseline = records[0]
    reactive = records[1]
    coating = records[2]

    assert baseline["annual_revenue_sar"] == 2_000
    assert baseline["total_annual_cost_sar"] == 0
    assert reactive["annual_revenue_sar"] == 2_100
    assert reactive["annual_opex_sar"] == 300
    assert coating["annual_revenue_sar"] == 2_160
    assert coating["annualized_capex_sar"] == 200