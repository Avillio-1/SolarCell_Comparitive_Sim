from __future__ import annotations

from typing import get_type_hints

import pytest
from tests.config_factory import fixture_config

from solarclean.config.models import (
    AssumptionLevel,
    CoatingConfig,
    CoatingCostConfig,
    CoatingDeploymentConfig,
    CoatingDeploymentMode,
    FarmConfig,
    SourceStatus,
)
from solarclean.domain.coating.costs import CoatingCostBasis, build_coating_cost_basis


def test_coating_config_loads_default_offline_fixture() -> None:
    config = fixture_config()

    assert config.coating.preset == "central"
    assert config.coating.physics.optical_transmittance_multiplier == pytest.approx(1.0)
    assert config.coating.physics.source_optical_transmittance_absolute_fraction is None
    assert config.coating.water.collectable_water_efficiency_fraction < 1.0
    assert config.coating.costs.material_cost_per_m2 > 0.0


def test_coating_cost_basis_scales_to_10000_panels() -> None:
    farm = FarmConfig(total_panels=10000, panel_capacity_w=400, cohort_count=100)
    deployment = CoatingDeploymentConfig(area_per_panel_m2=2.0, mode="factory_preinstall")
    costs = CoatingCostConfig(
        material_loading_g_per_m2=12.5,
        material_cost_per_m2=4.0,
        surface_preparation_cost_per_m2=1.5,
        application_labor_hours_per_m2=0.03,
        process_energy_kwh_per_m2=0.2,
        fixed_equipment_setup_cost=5000.0,
        inspection_hours_per_year=40.0,
        maintenance_cost_per_year=1200.0,
        useful_life_years=5.0,
        reapplication_interval_years=None,
        water_collection_infrastructure_cost=0.0,
        assumption_level="central",
        source_status="provisional",
    )

    basis = build_coating_cost_basis(farm=farm, deployment=deployment, costs=costs)

    assert basis.coated_panel_count == 10000
    assert basis.total_coated_area_m2 == pytest.approx(20000.0)
    assert basis.total_material_loading_kg == pytest.approx(250.0)
    assert basis.material_cost_total == pytest.approx(80000.0)
    assert basis.process_energy_kwh == pytest.approx(4000.0)
    assert basis.fixed_equipment_setup_cost == pytest.approx(5000.0)
    assert basis.deployment_mode == "factory_preinstall"
    assert basis.source_status == "provisional"


def test_coating_cost_rejects_free_or_negative_material_cost() -> None:
    with pytest.raises(ValueError):
        CoatingCostConfig(material_cost_per_m2=0.0)
    with pytest.raises(ValueError):
        CoatingCostConfig(material_cost_per_m2=-1.0)


def test_coating_deployment_rejects_reapplication_after_useful_life() -> None:
    with pytest.raises(ValueError, match="reapplication interval"):
        CoatingDeploymentConfig(
            useful_life_years=3.0,
            reapplication_supported=True,
            field_application_demonstrated=True,
            reapplication_interval_years=4.0,
        )


def test_coating_deployment_rejects_unsupported_reapplication_interval() -> None:
    with pytest.raises(ValueError, match="reapplication interval requires"):
        CoatingDeploymentConfig(reapplication_supported=False, reapplication_interval_years=5.0)


def test_coating_deployment_rejects_undemonstrated_retrofit() -> None:
    with pytest.raises(ValueError, match="retrofit deployment"):
        CoatingDeploymentConfig(mode="retrofit", field_application_demonstrated=False)


def test_coating_cost_rejects_reapplication_after_useful_life() -> None:
    with pytest.raises(ValueError, match="reapplication interval"):
        CoatingCostConfig(useful_life_years=3.0, reapplication_interval_years=4.0)


def test_coating_config_rejects_mismatched_lifecycle_basis() -> None:
    with pytest.raises(ValueError, match="coating lifecycle"):
        CoatingConfig(
            deployment=CoatingDeploymentConfig(
                useful_life_years=3.0,
                reapplication_supported=True,
                field_application_demonstrated=True,
                reapplication_interval_years=3.0,
            ),
            costs=CoatingCostConfig(
                useful_life_years=5.0,
                reapplication_interval_years=5.0,
            ),
        )


def test_coating_cost_basis_uses_config_literal_aliases() -> None:
    hints = get_type_hints(CoatingCostBasis)

    assert hints["deployment_mode"] == CoatingDeploymentMode
    assert hints["assumption_level"] == AssumptionLevel
    assert hints["source_status"] == SourceStatus
