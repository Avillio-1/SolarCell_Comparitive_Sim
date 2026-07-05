from __future__ import annotations

from solarclean.domain.economics.contracts import (
    CostComponent,
    EconomicConfig,
    EconomicResult,
    ScenarioEconomicInputs,
)


class EconomicEngine:
    """Common T4 techno-economic engine used by all scenarios."""

    def __init__(self, config: EconomicConfig) -> None:
        self.config = config

    def evaluate(self, inputs: ScenarioEconomicInputs) -> EconomicResult:
        total_capex_sar = self._sum_costs(inputs.cost_components, "capex")
        annual_opex_sar = self._sum_costs(inputs.cost_components, "opex")

        annual_revenue_sar = inputs.actual_energy_kwh * self.config.tariff_sar_per_kwh
        annualized_capex_sar = self.annualize_capex(total_capex_sar)

        total_annual_cost_sar = annualized_capex_sar + annual_opex_sar
        net_annual_benefit_sar = annual_revenue_sar - total_annual_cost_sar

        roi = self._safe_divide(net_annual_benefit_sar, total_annual_cost_sar)

        annual_cash_after_opex = annual_revenue_sar - annual_opex_sar
        payback_years = self._safe_divide(total_capex_sar, annual_cash_after_opex)

        effective_lcoe_sar_per_kwh = self._safe_divide(
            total_annual_cost_sar,
            inputs.actual_energy_kwh,
        )

        return EconomicResult(
            scenario_name=inputs.scenario_name,
            annual_revenue_sar=annual_revenue_sar,
            annualized_capex_sar=annualized_capex_sar,
            annual_opex_sar=annual_opex_sar,
            total_annual_cost_sar=total_annual_cost_sar,
            net_annual_benefit_sar=net_annual_benefit_sar,
            roi=roi,
            payback_years=payback_years,
            effective_lcoe_sar_per_kwh=effective_lcoe_sar_per_kwh,
            total_capex_sar=total_capex_sar,
            cost_breakdown=inputs.cost_components,
        )

    def annualize_capex(self, total_capex_sar: float) -> float:
        if total_capex_sar < 0:
            raise ValueError("total_capex_sar must be non-negative.")

        if total_capex_sar == 0:
            return 0.0

        r = self.config.discount_rate
        n = self.config.useful_life_years

        if r == 0:
            return total_capex_sar / n

        growth_factor = (1 + r) ** n
        capital_recovery_factor = (r * growth_factor) / (growth_factor - 1)
        return total_capex_sar * capital_recovery_factor

    @staticmethod
    def _sum_costs(
        cost_components: tuple[CostComponent, ...],
        category: str,
    ) -> float:
        return sum(
            component.amount_sar
            for component in cost_components
            if component.category == category
        )

    @staticmethod
    def _safe_divide(numerator: float, denominator: float) -> float | None:
        if denominator <= 0:
            return None
        return numerator / denominator