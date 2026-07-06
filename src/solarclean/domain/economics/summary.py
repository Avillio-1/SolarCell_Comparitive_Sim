from __future__ import annotations

from dataclasses import asdict, dataclass

from solarclean.domain.economics.contracts import EconomicResult


@dataclass(frozen=True)
class AnnualFinancialSummaryRow:
    scenario_name: str
    annual_revenue_sar: float
    annualized_capex_sar: float
    annual_opex_sar: float
    total_annual_cost_sar: float
    net_annual_benefit_sar: float
    roi: float | None
    payback_years: float | None
    effective_lcoe_sar_per_kwh: float | None
    total_capex_sar: float
    capital_recovery_life_years: float

    @classmethod
    def from_result(cls, result: EconomicResult) -> AnnualFinancialSummaryRow:
        return cls(
            scenario_name=result.scenario_name,
            annual_revenue_sar=result.annual_revenue_sar,
            annualized_capex_sar=result.annualized_capex_sar,
            annual_opex_sar=result.annual_opex_sar,
            total_annual_cost_sar=result.total_annual_cost_sar,
            net_annual_benefit_sar=result.net_annual_benefit_sar,
            roi=result.roi,
            payback_years=result.payback_years,
            effective_lcoe_sar_per_kwh=result.effective_lcoe_sar_per_kwh,
            total_capex_sar=result.total_capex_sar,
            capital_recovery_life_years=result.capital_recovery_life_years,
        )

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def build_annual_financial_summary(
    results: tuple[EconomicResult, ...],
) -> tuple[AnnualFinancialSummaryRow, ...]:
    """Build comparison-ready annual financial rows for all scenarios."""
    return tuple(AnnualFinancialSummaryRow.from_result(result) for result in results)


def financial_summary_to_records(
    rows: tuple[AnnualFinancialSummaryRow, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(row.to_record() for row in rows)
