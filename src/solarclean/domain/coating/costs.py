from __future__ import annotations

from dataclasses import asdict, dataclass

from solarclean.config.models import (
    AssumptionLevel,
    CoatingCostConfig,
    CoatingDeploymentConfig,
    CoatingDeploymentMode,
    FarmConfig,
    SourceStatus,
)


@dataclass(frozen=True)
class CoatingCostBasis:
    coated_panel_count: int
    area_per_panel_m2: float
    total_coated_area_m2: float
    material_loading_g_per_m2: float
    total_material_loading_kg: float
    material_cost_per_m2: float
    material_cost_total: float
    surface_preparation_cost_total: float
    application_labor_hours: float
    process_energy_kwh: float
    fixed_equipment_setup_cost: float
    inspection_hours_per_year: float
    maintenance_cost_per_year: float
    useful_life_years: float
    reapplication_interval_years: float
    deployment_mode: CoatingDeploymentMode
    water_collection_infrastructure_cost: float
    assumption_level: AssumptionLevel
    source_status: SourceStatus
    thermal_treatment_temperature_c: float
    thermal_treatment_duration_minutes: float
    field_application_demonstrated: bool

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def build_coating_cost_basis(
    *,
    farm: FarmConfig,
    deployment: CoatingDeploymentConfig,
    costs: CoatingCostConfig,
) -> CoatingCostBasis:
    area = float(farm.total_panels) * deployment.area_per_panel_m2
    return CoatingCostBasis(
        coated_panel_count=farm.total_panels,
        area_per_panel_m2=deployment.area_per_panel_m2,
        total_coated_area_m2=area,
        material_loading_g_per_m2=costs.material_loading_g_per_m2,
        total_material_loading_kg=area * costs.material_loading_g_per_m2 / 1000.0,
        material_cost_per_m2=costs.material_cost_per_m2,
        material_cost_total=area * costs.material_cost_per_m2,
        surface_preparation_cost_total=area * costs.surface_preparation_cost_per_m2,
        application_labor_hours=area * costs.application_labor_hours_per_m2,
        process_energy_kwh=area * costs.process_energy_kwh_per_m2,
        fixed_equipment_setup_cost=costs.fixed_equipment_setup_cost,
        inspection_hours_per_year=costs.inspection_hours_per_year,
        maintenance_cost_per_year=costs.maintenance_cost_per_year,
        useful_life_years=costs.useful_life_years,
        reapplication_interval_years=costs.reapplication_interval_years,
        deployment_mode=deployment.mode,
        water_collection_infrastructure_cost=costs.water_collection_infrastructure_cost,
        assumption_level=costs.assumption_level,
        source_status=costs.source_status,
        thermal_treatment_temperature_c=deployment.thermal_treatment_temperature_c,
        thermal_treatment_duration_minutes=deployment.thermal_treatment_duration_minutes,
        field_application_demonstrated=deployment.field_application_demonstrated,
    )
