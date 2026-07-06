from __future__ import annotations

import pytest

from solarclean.domain.economics import (
    AnnualScenarioOutput,
    CostComponent,
    EconomicConfig,
    ReactiveCostRates,
    UnitCostRate,
    build_annual_financial_summary_from_outputs,
    build_coating_cost_components_from_basis,
    build_reactive_cost_components,
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


def test_reactive_adapter_maps_recorded_operations_with_explicit_rates() -> None:
    operational = OperationalQuantities(
        inspections_count=2,
        cleaning_actions_count=3,
        crew_hours=4,
        drone_flight_hours=1.5,
        water_liters=20,
        energy_used_kwh=7,
    )

    components = build_reactive_cost_components(
        operational_quantities=operational,
        rates=ReactiveCostRates(
            inspection=UnitCostRate(5, "inspection", "test rate", "provisional"),
            cleaning_action=UnitCostRate(8, "cleaning_action", "test rate", "provisional"),
            crew_hour=UnitCostRate(30, "hour", "test rate", "provisional"),
            drone_flight_hour=UnitCostRate(40, "flight_hour", "test rate", "provisional"),
            water_liter=UnitCostRate(0.5, "liter", "test rate", "provisional"),
            energy_kwh=UnitCostRate(0.2, "kWh", "test rate", "provisional"),
        ),
    )

    by_name = {component.name: component for component in components}

    assert by_name["reactive inspection operations"].amount_sar == 10
    assert by_name["reactive cleaning equipment use"].amount_sar == 24
    assert by_name["reactive crew labour"].amount_sar == 120
    assert by_name["reactive drone flight operations"].amount_sar == 60
    assert by_name["reactive water use"].amount_sar == 10
    assert by_name["reactive energy use"].amount_sar == pytest.approx(1.4)
    assert all(component.category == "opex" for component in components)
    assert all(component.unit == "SAR/year" for component in components)
    assert all(component.source_status == "provisional" for component in components)


def test_coating_adapter_maps_cost_basis_with_traceable_lifecycle_notes() -> None:
    basis = _coating_cost_basis()

    components = build_coating_cost_components_from_basis(
        coating_cost_basis=basis,
        application_labour_rate=UnitCostRate(25, "hour", "test labour", "provisional"),
        process_energy_rate=UnitCostRate(0.2, "kWh", "test energy", "provisional"),
    )
    by_name = {component.name: component for component in components}

    assert by_name["coating material capex"].amount_sar == 400
    assert by_name["coating surface preparation capex"].amount_sar == 150
    assert by_name["coating fixed equipment capex"].amount_sar == 1_000
    assert by_name["coating water collection infrastructure capex"].amount_sar == 700
    assert by_name["coating maintenance opex"].amount_sar == 120
    assert by_name["coating application labour capex"].amount_sar == 250
    assert by_name["coating process energy capex"].amount_sar == 6
    assert by_name["coating material capex"].source_status == "provisional"
    assert "total_coated_area_m2=100" in str(by_name["coating material capex"].notes)
    assert "reapplication_interval_years=2.0" in str(by_name["coating material capex"].notes)


def test_coating_output_metadata_can_feed_financial_summary_without_engine_branching() -> None:
    config = EconomicConfig(
        currency="SAR",
        tariff_sar_per_kwh=0.20,
        discount_rate=0.0,
        useful_life_years=5,
    )
    outputs = (
        AnnualScenarioOutput(
            scenario_name="coating",
            actual_energy_kwh=10_800,
            clean_energy_kwh=11_000,
            metadata={"coating_cost_basis": _coating_cost_basis()},
        ),
    )

    rows = build_annual_financial_summary_from_outputs(outputs=outputs, config=config)

    assert rows[0].annualized_capex_sar == 450
    assert rows[0].annual_opex_sar == 120
    assert rows[0].total_annual_cost_sar == 570
    assert rows[0].capital_recovery_life_years == 5


def test_coating_useful_life_overrides_generic_capital_recovery_life() -> None:
    config = EconomicConfig(
        currency="SAR",
        tariff_sar_per_kwh=0.20,
        discount_rate=0.0,
        useful_life_years=15,
    )
    basis = _coating_cost_basis()
    basis["useful_life_years"] = 3.0
    outputs = (
        AnnualScenarioOutput(
            scenario_name="coating",
            actual_energy_kwh=10_800,
            clean_energy_kwh=11_000,
            metadata={"coating_cost_basis": basis},
        ),
    )

    rows = build_annual_financial_summary_from_outputs(outputs=outputs, config=config)

    assert rows[0].annualized_capex_sar == 750
    assert rows[0].capital_recovery_life_years == 3


def _coating_cost_basis() -> dict[str, object]:
    return {
        "total_coated_area_m2": 100.0,
        "material_cost_total": 400.0,
        "surface_preparation_cost_total": 150.0,
        "application_labor_hours": 10.0,
        "process_energy_kwh": 30.0,
        "fixed_equipment_setup_cost": 1_000.0,
        "maintenance_cost_per_year": 120.0,
        "useful_life_years": 5.0,
        "reapplication_interval_years": 2.0,
        "water_collection_infrastructure_cost": 700.0,
        "assumption_level": "central",
        "source_status": "provisional",
    }
