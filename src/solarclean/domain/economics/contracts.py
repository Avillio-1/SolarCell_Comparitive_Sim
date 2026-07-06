from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from solarclean.domain.scenario.contracts import OperationalQuantities

CostCategory = Literal["capex", "opex"]


@dataclass(frozen=True)
class EconomicConfig:
    """Common Saudi/Riyadh economic assumptions for all scenarios."""

    currency: str = "SAR"
    tariff_sar_per_kwh: float = 0.0
    discount_rate: float = 0.0
    useful_life_years: int = 1
    annualization_method: str = "capital_recovery_factor"

    def __post_init__(self) -> None:
        if self.currency != "SAR":
            raise ValueError("SolarClean-DT T4 currently expects SAR as the currency.")
        if self.tariff_sar_per_kwh < 0:
            raise ValueError("tariff_sar_per_kwh must be non-negative.")
        if self.discount_rate < 0:
            raise ValueError("discount_rate must be non-negative.")
        if self.useful_life_years <= 0:
            raise ValueError("useful_life_years must be positive.")
        if self.annualization_method != "capital_recovery_factor":
            raise ValueError("Only capital_recovery_factor annualization is currently supported.")


@dataclass(frozen=True)
class CostComponent:
    """One traceable cost item with unit and source information."""

    name: str
    category: CostCategory
    amount_sar: float
    unit: str
    source: str = "unspecified"
    notes: str | None = None
    source_status: str = "unspecified"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("CostComponent.name must not be empty.")
        if self.amount_sar < 0:
            raise ValueError("CostComponent.amount_sar must be non-negative.")
        if not self.unit:
            raise ValueError("CostComponent.unit must not be empty.")
        if not self.source:
            raise ValueError("CostComponent.source must not be empty.")
        if not self.source_status:
            raise ValueError("CostComponent.source_status must not be empty.")


@dataclass(frozen=True)
class ScenarioEconomicInputs:
    """Physical annual outputs plus cost components for one scenario."""

    scenario_name: str
    actual_energy_kwh: float
    clean_energy_kwh: float
    operational_quantities: OperationalQuantities = field(default_factory=OperationalQuantities)
    cost_components: tuple[CostComponent, ...] = ()

    def __post_init__(self) -> None:
        if not self.scenario_name:
            raise ValueError("scenario_name must not be empty.")
        if self.actual_energy_kwh < 0:
            raise ValueError("actual_energy_kwh must be non-negative.")
        if self.clean_energy_kwh < 0:
            raise ValueError("clean_energy_kwh must be non-negative.")


@dataclass(frozen=True)
class EconomicResult:
    """Annual financial KPIs for one scenario."""

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
    cost_breakdown: tuple[CostComponent, ...]
