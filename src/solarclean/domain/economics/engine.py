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
        capital_recovery_life_years = (
            inputs.useful_life_years
            if inputs.useful_life_years is not None
            else float(self.config.useful_life_years)
        )
        annualized_capex_sar = self.annualize_capex(
            total_capex_sar,
            useful_life_years=capital_recovery_life_years,
        )

        total_annual_cost_sar = annualized_capex_sar + annual_opex_sar
        net_annual_benefit_sar = annual_revenue_sar - total_annual_cost_sar

        roi = self._safe_divide(net_annual_benefit_sar, total_annual_cost_sar)

        annual_cash_after_opex = annual_revenue_sar - annual_opex_sar
        payback_years = self._payback_years(
            total_capex_sar=total_capex_sar,
            annual_cash_after_opex=annual_cash_after_opex,
            net_annual_benefit_sar=net_annual_benefit_sar,
        )

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
            capital_recovery_life_years=capital_recovery_life_years,
        )

    def annualize_capex(
        self,
        total_capex_sar: float,
        *,
        useful_life_years: float | None = None,
    ) -> float:
        if total_capex_sar < 0:
            raise ValueError("total_capex_sar must be non-negative.")

        if total_capex_sar == 0:
            return 0.0

        r = self.config.discount_rate
        n = useful_life_years if useful_life_years is not None else self.config.useful_life_years
        if n <= 0:
            raise ValueError("useful_life_years must be positive.")

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
            component.amount_sar for component in cost_components if component.category == category
        )

    @staticmethod
    def _safe_divide(numerator: float, denominator: float) -> float | None:
        if denominator <= 0:
            return None
        return numerator / denominator

    @staticmethod
    def _payback_years(
        *,
        total_capex_sar: float,
        annual_cash_after_opex: float,
        net_annual_benefit_sar: float,
    ) -> float | None:
        if net_annual_benefit_sar <= 0:
            return None
        if total_capex_sar == 0:
            return 0.0
        return EconomicEngine._safe_divide(total_capex_sar, annual_cash_after_opex)
