from __future__ import annotations

import pytest

from solarclean.domain.economics import (
    CostComponent,
    EconomicConfig,
    EconomicEngine,
    ScenarioEconomicInputs,
    build_baseline_economic_inputs,
)
from solarclean.domain.scenario.contracts import OperationalQuantities


def test_economics_engine_matches_hand_calculated_reference_case() -> None:
    config = EconomicConfig(
        currency="SAR",
        tariff_sar_per_kwh=0.50,
        discount_rate=0.10,
        useful_life_years=5,
    )
    engine = EconomicEngine(config)

    inputs = ScenarioEconomicInputs(
        scenario_name="reference",
        actual_energy_kwh=10_000,
        clean_energy_kwh=11_000,
        operational_quantities=OperationalQuantities(),
        cost_components=(
            CostComponent(
                name="reference capex",
                category="capex",
                amount_sar=10_000,
                unit="SAR",
                source="hand calculated test",
            ),
            CostComponent(
                name="reference opex",
                category="opex",
                amount_sar=500,
                unit="SAR/year",
                source="hand calculated test",
            ),
        ),
    )

    result = engine.evaluate(inputs)

    expected_crf = (0.10 * (1.10**5)) / ((1.10**5) - 1)
    expected_annualized_capex = 10_000 * expected_crf
    expected_revenue = 10_000 * 0.50
    expected_opex = 500
    expected_total_cost = expected_annualized_capex + expected_opex
    expected_net_benefit = expected_revenue - expected_total_cost

    assert result.annual_revenue_sar == pytest.approx(expected_revenue)
    assert result.annualized_capex_sar == pytest.approx(expected_annualized_capex)
    assert result.annual_opex_sar == pytest.approx(expected_opex)
    assert result.total_annual_cost_sar == pytest.approx(expected_total_cost)
    assert result.net_annual_benefit_sar == pytest.approx(expected_net_benefit)
    assert result.effective_lcoe_sar_per_kwh == pytest.approx(expected_total_cost / 10_000)
    assert result.roi == pytest.approx(expected_net_benefit / expected_total_cost)
    assert result.payback_years == pytest.approx(10_000 / (expected_revenue - expected_opex))


def test_zero_discount_rate_annualizes_capex_by_useful_life() -> None:
    config = EconomicConfig(
        currency="SAR",
        tariff_sar_per_kwh=0.20,
        discount_rate=0.0,
        useful_life_years=5,
    )
    engine = EconomicEngine(config)

    assert engine.annualize_capex(10_000) == pytest.approx(2_000)


def test_baseline_adapter_rejects_soiling_loss_cost_component() -> None:
    with pytest.raises(ValueError, match="Baseline soiling loss"):
        build_baseline_economic_inputs(
            actual_energy_kwh=10_000,
            clean_energy_kwh=11_000,
            cost_components=(
                CostComponent(
                    name="soiling loss charge",
                    category="opex",
                    amount_sar=100,
                    unit="SAR/year",
                    source="invalid test component",
                ),
            ),
        )


def test_baseline_adapter_accepts_normal_cost_components() -> None:
    inputs = build_baseline_economic_inputs(
        actual_energy_kwh=10_000,
        clean_energy_kwh=11_000,
        cost_components=(
            CostComponent(
                name="monitoring opex",
                category="opex",
                amount_sar=100,
                unit="SAR/year",
                source="test component",
            ),
        ),
    )

    assert inputs.scenario_name == "baseline"
    assert len(inputs.cost_components) == 1
    assert inputs.cost_components[0].name == "monitoring opex"


def test_baseline_adapter_rejects_multiple_double_counting_names() -> None:
    blocked_names = (
        "soiling loss charge",
        "dust loss charge",
        "lost revenue charge",
        "revenue loss adjustment",
    )

    for name in blocked_names:
        with pytest.raises(ValueError, match="Baseline soiling loss"):
            build_baseline_economic_inputs(
                actual_energy_kwh=10_000,
                clean_energy_kwh=11_000,
                cost_components=(
                    CostComponent(
                        name=name,
                        category="opex",
                        amount_sar=100,
                        unit="SAR/year",
                        source="invalid test component",
                    ),
                ),
            )


def test_payback_is_none_when_annual_economics_do_not_recover_costs() -> None:
    config = EconomicConfig(
        currency="SAR",
        tariff_sar_per_kwh=0.20,
        discount_rate=0.10,
        useful_life_years=5,
    )
    engine = EconomicEngine(config)

    result = engine.evaluate(
        ScenarioEconomicInputs(
            scenario_name="negative",
            actual_energy_kwh=10_000,
            clean_energy_kwh=11_000,
            cost_components=(
                CostComponent(
                    name="capex",
                    category="capex",
                    amount_sar=10_000,
                    unit="SAR",
                    source="test",
                ),
                CostComponent(
                    name="opex",
                    category="opex",
                    amount_sar=500,
                    unit="SAR/year",
                    source="test",
                ),
            ),
        )
    )

    assert result.net_annual_benefit_sar < 0
    assert result.roi is not None
    assert result.roi < 0
    assert result.payback_years is None


def test_zero_energy_and_zero_cost_edges_do_not_divide() -> None:
    result = EconomicEngine(EconomicConfig()).evaluate(
        ScenarioEconomicInputs(
            scenario_name="zero",
            actual_energy_kwh=0,
            clean_energy_kwh=0,
        )
    )

    assert result.annual_revenue_sar == 0
    assert result.total_annual_cost_sar == 0
    assert result.net_annual_benefit_sar == 0
    assert result.roi is None
    assert result.payback_years is None
    assert result.effective_lcoe_sar_per_kwh is None


def test_zero_capex_positive_net_benefit_has_zero_payback() -> None:
    result = EconomicEngine(EconomicConfig(tariff_sar_per_kwh=0.20)).evaluate(
        ScenarioEconomicInputs(
            scenario_name="opex-only",
            actual_energy_kwh=1_000,
            clean_energy_kwh=1_000,
            cost_components=(
                CostComponent(
                    name="opex",
                    category="opex",
                    amount_sar=50,
                    unit="SAR/year",
                    source="test",
                ),
            ),
        )
    )

    assert result.total_capex_sar == 0
    assert result.net_annual_benefit_sar > 0
    assert result.payback_years == 0
