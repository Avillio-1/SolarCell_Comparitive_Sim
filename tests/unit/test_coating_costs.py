from __future__ import annotations

from pathlib import Path

import pytest

from solarclean.config.loader import load_config
from solarclean.config.models import CoatingCostConfig, CoatingDeploymentConfig, FarmConfig
from solarclean.domain.coating.costs import build_coating_cost_basis


def test_coating_config_loads_default_offline_fixture() -> None:
    config = load_config(Path("configs/offline_fixture.yaml"))

    assert config.coating.preset == "central"
    assert config.coating.physics.optical_transmittance_multiplier == pytest.approx(0.913)
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
        reapplication_interval_years=5.0,
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
