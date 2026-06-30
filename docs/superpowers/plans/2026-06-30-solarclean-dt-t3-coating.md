# SolarClean-DT T3 Coating Scenario Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Scenario 3, a KAUST-inspired proactive coating scenario with coating physics, water accounting, and T4-ready cost basis, using the T1 shared scenario engine.

**Architecture:** Add a focused `solarclean.domain.coating` package for pure coating state, physics, costs, and `CoatingStrategy`. Add validated `coating` configuration, a `RunCoatingSimulation` application use case, a `run-coating` CLI command, paper-calibration configs, and docs. Keep the annual loop inside `ScenarioSimulationEngine`; coating data travels through T1 `extensions`.

**Tech Stack:** Python 3.11+, dataclasses, Pydantic config models, pandas, numpy, Typer, pytest, Ruff, mypy.

---

## File Structure

- Create `src/solarclean/domain/coating/__init__.py`: public coating exports.
- Create `src/solarclean/domain/coating/costs.py`: `CoatingCostBasis` and area/material/process quantity calculations.
- Create `src/solarclean/domain/coating/state.py`: per-cohort and aggregate coating state dataclasses.
- Create `src/solarclean/domain/coating/physics.py`: dew point, surface temperature, condensation, passive cleaning, bird removal, and mechanism energy calculations.
- Create `src/solarclean/domain/coating/strategy.py`: T1 `MitigationStrategy` implementation.
- Modify `src/solarclean/config/models.py`: add nested `CoatingConfig` models and include `coating` in `SolarCleanConfig`.
- Modify `src/solarclean/application/use_cases.py`: add `RunCoatingSimulation` and shared event-tape/context helpers.
- Modify `src/solarclean/cli/main.py`: add `solarclean run-coating`.
- Add `configs/coating_weak.yaml`, `configs/coating_central.yaml`, `configs/coating_strong.yaml`, and `configs/coating_paper_calibration.yaml`.
- Add `tests/unit/test_coating_physics.py`, `tests/unit/test_coating_costs.py`, `tests/unit/test_coating_strategy.py`.
- Add `tests/regression/test_t3_coating_scenario.py`.
- Add `docs/data_contracts/coating_scenario.md`, `docs/assumptions/coating_scenario.md`, and `docs/adr/ADR-010-t3-coating-scenario.md`.
- Modify `PROGRESS.md`.

## Task 1: Configuration And Cost Basis

**Files:**
- Modify: `src/solarclean/config/models.py`
- Create: `src/solarclean/domain/coating/__init__.py`
- Create: `src/solarclean/domain/coating/costs.py`
- Test: `tests/unit/test_coating_costs.py`

- [ ] **Step 1: Write failing config and cost tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail for missing coating config**

Run:

```powershell
python -m pytest tests/unit/test_coating_costs.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'solarclean.domain.coating'` or `ImportError` for missing coating config models.

- [ ] **Step 3: Implement config models**

Add these declarations to `src/solarclean/config/models.py` near the existing config model declarations:

```python
CoatingPresetName = Literal["weak", "central", "strong", "paper_calibration"]
CoatingDeploymentMode = Literal["factory_preinstall", "retrofit"]
AssumptionLevel = Literal["weak", "central", "strong"]
SourceStatus = Literal["prompt_quoted", "provisional", "unsourced"]


class CoatingPhysicsConfig(StrictModel):
    optical_transmittance_multiplier: float = Field(default=0.913, gt=0, le=1)
    emissivity_atmospheric_window: float = Field(default=0.90, ge=0, le=1)
    contact_angle_degrees: float = Field(default=167.0, ge=0, le=180)
    sliding_angle_degrees: float = Field(default=3.0, ge=0, le=90)
    dust_accumulation_multiplier: float = Field(default=0.35, ge=0, le=1)
    initial_effectiveness_fraction: float = Field(default=1.0, ge=0, le=1)
    annual_degradation_fraction: float = Field(default=0.08, ge=0, le=1)
    max_surface_cooling_c: float = Field(default=7.0, ge=0)
    humidity_cooling_reference_pct: float = Field(default=80.0, ge=1, le=100)
    wind_cooling_decay_per_m_s: float = Field(default=0.08, ge=0)
    daytime_cooling_fraction: float = Field(default=0.35, ge=0, le=1)
    passive_cleaning_base_efficiency: float = Field(default=0.55, ge=0, le=1)
    passive_cleaning_tilt_reference_degrees: float = Field(default=25.0, ge=1, le=90)
    bird_removal_efficiency: float = Field(default=0.08, ge=0, le=1)
    max_bird_removal_fraction_per_day: float = Field(default=0.02, ge=0, le=1)


class CoatingWaterConfig(StrictModel):
    condensation_liters_per_m2_per_c_hour: float = Field(default=0.0142, ge=0)
    minimum_relative_humidity_pct: float = Field(default=60.0, ge=0, le=100)
    collectable_water_efficiency_fraction: float = Field(default=0.65, ge=0, le=1)
    actual_collection_efficiency_fraction: float = Field(default=0.50, ge=0, le=1)


class CoatingDeploymentConfig(StrictModel):
    mode: CoatingDeploymentMode = "factory_preinstall"
    area_per_panel_m2: float = Field(default=2.0, gt=0)
    useful_life_years: float = Field(default=5.0, gt=0)
    reapplication_interval_years: float = Field(default=5.0, gt=0)
    thermal_treatment_temperature_c: float = Field(default=400.0, gt=0)
    thermal_treatment_duration_minutes: float = Field(default=30.0, gt=0)
    field_application_demonstrated: bool = False

    @model_validator(mode="after")
    def validate_reapplication_interval(self) -> CoatingDeploymentConfig:
        if self.reapplication_interval_years > self.useful_life_years:
            raise ValueError("reapplication interval cannot exceed useful life")
        return self


class CoatingCostConfig(StrictModel):
    material_loading_g_per_m2: float = Field(default=12.5, gt=0)
    material_cost_per_m2: float = Field(default=4.0, gt=0)
    surface_preparation_cost_per_m2: float = Field(default=1.5, ge=0)
    application_labor_hours_per_m2: float = Field(default=0.03, ge=0)
    process_energy_kwh_per_m2: float = Field(default=0.2, ge=0)
    fixed_equipment_setup_cost: float = Field(default=5000.0, ge=0)
    inspection_hours_per_year: float = Field(default=40.0, ge=0)
    maintenance_cost_per_year: float = Field(default=1200.0, ge=0)
    useful_life_years: float = Field(default=5.0, gt=0)
    reapplication_interval_years: float = Field(default=5.0, gt=0)
    water_collection_infrastructure_cost: float = Field(default=0.0, ge=0)
    assumption_level: AssumptionLevel = "central"
    source_status: SourceStatus = "provisional"

    @model_validator(mode="after")
    def validate_cost_life(self) -> CoatingCostConfig:
        if self.reapplication_interval_years > self.useful_life_years:
            raise ValueError("reapplication interval cannot exceed useful life")
        return self


class CoatingConfig(StrictModel):
    enabled: bool = True
    preset: CoatingPresetName = "central"
    physics: CoatingPhysicsConfig = Field(default_factory=CoatingPhysicsConfig)
    water: CoatingWaterConfig = Field(default_factory=CoatingWaterConfig)
    deployment: CoatingDeploymentConfig = Field(default_factory=CoatingDeploymentConfig)
    costs: CoatingCostConfig = Field(default_factory=CoatingCostConfig)
```

Add this field to `SolarCleanConfig`:

```python
    coating: CoatingConfig = Field(default_factory=CoatingConfig)
```

- [ ] **Step 4: Implement cost basis**

Create `src/solarclean/domain/coating/costs.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass

from solarclean.config.models import CoatingCostConfig, CoatingDeploymentConfig, FarmConfig


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
    deployment_mode: str
    water_collection_infrastructure_cost: float
    assumption_level: str
    source_status: str
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
```

Create `src/solarclean/domain/coating/__init__.py`:

```python
from solarclean.domain.coating.costs import CoatingCostBasis, build_coating_cost_basis

__all__ = ["CoatingCostBasis", "build_coating_cost_basis"]
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```powershell
python -m pytest tests/unit/test_coating_costs.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```powershell
git add src/solarclean/config/models.py src/solarclean/domain/coating/__init__.py src/solarclean/domain/coating/costs.py tests/unit/test_coating_costs.py
git commit -m "Add coating config and cost basis"
```

## Task 2: Coating Physics

**Files:**
- Create: `src/solarclean/domain/coating/physics.py`
- Test: `tests/unit/test_coating_physics.py`

- [ ] **Step 1: Write failing physics tests**

```python
from __future__ import annotations

import pytest

from solarclean.config.models import CoatingPhysicsConfig, CoatingWaterConfig
from solarclean.domain.coating.physics import (
    apply_bird_removal,
    calculate_condensation,
    calculate_dew_point_c,
    calculate_energy_mechanisms,
    calculate_passive_dust_cleaning,
    calculate_surface_temperature_c,
)


def test_dew_point_and_condensation_require_surface_below_dew_point() -> None:
    dew_point = calculate_dew_point_c(air_temperature_c=20.0, relative_humidity_pct=80.0)
    surface = calculate_surface_temperature_c(
        air_temperature_c=20.0,
        relative_humidity_pct=80.0,
        wind_speed_m_s=0.5,
        irradiance_w_m2=0.0,
        physics=CoatingPhysicsConfig(max_surface_cooling_c=7.0),
    )
    condensation = calculate_condensation(
        air_temperature_c=20.0,
        relative_humidity_pct=80.0,
        surface_temperature_c=surface,
        exposure_hours=1.0,
        area_m2=10.0,
        water=CoatingWaterConfig(condensation_liters_per_m2_per_c_hour=0.01),
    )

    assert dew_point == pytest.approx(16.44, abs=0.15)
    assert surface < dew_point
    assert condensation.condensed_liters > 0.0
    assert condensation.potentially_collectable_liters <= condensation.condensed_liters
    assert condensation.actually_collected_liters <= condensation.potentially_collectable_liters


def test_no_condensation_when_humidity_or_temperature_conditions_fail() -> None:
    low_humidity = calculate_condensation(
        air_temperature_c=28.0,
        relative_humidity_pct=35.0,
        surface_temperature_c=10.0,
        exposure_hours=1.0,
        area_m2=20.0,
        water=CoatingWaterConfig(minimum_relative_humidity_pct=60.0),
    )
    warm_surface = calculate_condensation(
        air_temperature_c=20.0,
        relative_humidity_pct=80.0,
        surface_temperature_c=19.0,
        exposure_hours=1.0,
        area_m2=20.0,
        water=CoatingWaterConfig(),
    )

    assert low_humidity.condensed_liters == 0.0
    assert warm_surface.condensed_liters == 0.0


def test_passive_cleaning_and_bird_removal_are_bounded() -> None:
    physics = CoatingPhysicsConfig(
        passive_cleaning_base_efficiency=0.5,
        max_bird_removal_fraction_per_day=0.02,
        bird_removal_efficiency=0.5,
    )

    dust_restored = calculate_passive_dust_cleaning(
        current_dust_soiling_ratio=0.80,
        condensed_liters_per_m2=0.20,
        tilt_degrees=25.0,
        coating_effectiveness=0.9,
        physics=physics,
    )
    bird = apply_bird_removal(
        current_coverage_fraction=0.10,
        condensed_liters_per_m2=0.20,
        coating_effectiveness=0.9,
        physics=physics,
    )

    assert 0.0 < dust_restored <= 0.20
    assert bird.removed_coverage_fraction == pytest.approx(0.02)
    assert bird.remaining_coverage_fraction == pytest.approx(0.08)


def test_energy_mechanisms_do_not_double_count_total_gain() -> None:
    result = calculate_energy_mechanisms(
        clean_energy_kwh=100.0,
        cleanliness_ratio=0.80,
        optical_transmittance_multiplier=0.913,
        cooling_delta_c=5.0,
        gamma_pdc_per_c=-0.0035,
    )

    assert result.optical_effect_kwh < 0.0
    assert result.temperature_effect_kwh > 0.0
    assert result.cleanliness_effect_kwh == pytest.approx(-20.0)
    assert result.final_energy_kwh <= 100.0
    assert result.final_energy_kwh == pytest.approx(
        result.clean_reference_energy_kwh
        + result.optical_effect_kwh
        + result.temperature_effect_kwh
        + result.cleanliness_effect_kwh
    )
```

- [ ] **Step 2: Run tests to verify they fail for missing physics module**

Run:

```powershell
python -m pytest tests/unit/test_coating_physics.py -q
```

Expected: collection fails with `ModuleNotFoundError` or import errors for missing physics functions.

- [ ] **Step 3: Implement physics dataclasses and functions**

Create `src/solarclean/domain/coating/physics.py`:

```python
from __future__ import annotations

import math
from dataclasses import dataclass

from solarclean.config.models import CoatingPhysicsConfig, CoatingWaterConfig


@dataclass(frozen=True)
class CondensationResult:
    dew_point_c: float
    surface_temperature_c: float
    condensed_liters: float
    potentially_collectable_liters: float
    actually_collected_liters: float


@dataclass(frozen=True)
class BirdRemovalResult:
    removed_coverage_fraction: float
    remaining_coverage_fraction: float


@dataclass(frozen=True)
class EnergyMechanismResult:
    clean_reference_energy_kwh: float
    optical_effect_kwh: float
    temperature_effect_kwh: float
    cleanliness_effect_kwh: float
    final_energy_kwh: float
    optical_multiplier: float
    temperature_multiplier: float
    cleanliness_ratio: float


def calculate_dew_point_c(air_temperature_c: float, relative_humidity_pct: float) -> float:
    humidity = min(100.0, max(1e-6, relative_humidity_pct))
    a = 17.625
    b = 243.04
    alpha = math.log(humidity / 100.0) + (a * air_temperature_c) / (b + air_temperature_c)
    return (b * alpha) / (a - alpha)


def calculate_surface_temperature_c(
    *,
    air_temperature_c: float,
    relative_humidity_pct: float,
    wind_speed_m_s: float,
    irradiance_w_m2: float,
    physics: CoatingPhysicsConfig,
) -> float:
    humidity_factor = min(1.2, max(0.0, relative_humidity_pct / physics.humidity_cooling_reference_pct))
    wind_factor = math.exp(-physics.wind_cooling_decay_per_m_s * max(0.0, wind_speed_m_s))
    night_factor = 1.0 if irradiance_w_m2 <= 5.0 else physics.daytime_cooling_fraction
    cooling = (
        physics.max_surface_cooling_c
        * physics.emissivity_atmospheric_window
        * humidity_factor
        * wind_factor
        * night_factor
    )
    return air_temperature_c - cooling


def calculate_condensation(
    *,
    air_temperature_c: float,
    relative_humidity_pct: float,
    surface_temperature_c: float,
    exposure_hours: float,
    area_m2: float,
    water: CoatingWaterConfig,
) -> CondensationResult:
    dew_point = calculate_dew_point_c(air_temperature_c, relative_humidity_pct)
    if (
        relative_humidity_pct < water.minimum_relative_humidity_pct
        or surface_temperature_c >= dew_point
        or exposure_hours <= 0.0
        or area_m2 <= 0.0
    ):
        condensed = 0.0
    else:
        depression = dew_point - surface_temperature_c
        condensed = (
            depression
            * exposure_hours
            * area_m2
            * water.condensation_liters_per_m2_per_c_hour
        )
    potential = condensed * water.collectable_water_efficiency_fraction
    actual = potential * water.actual_collection_efficiency_fraction
    return CondensationResult(
        dew_point_c=dew_point,
        surface_temperature_c=surface_temperature_c,
        condensed_liters=condensed,
        potentially_collectable_liters=potential,
        actually_collected_liters=actual,
    )


def calculate_passive_dust_cleaning(
    *,
    current_dust_soiling_ratio: float,
    condensed_liters_per_m2: float,
    tilt_degrees: float,
    coating_effectiveness: float,
    physics: CoatingPhysicsConfig,
) -> float:
    recoverable = max(0.0, 1.0 - current_dust_soiling_ratio)
    if recoverable == 0.0 or condensed_liters_per_m2 <= 0.0 or coating_effectiveness <= 0.0:
        return 0.0
    tilt_factor = min(1.0, max(0.0, tilt_degrees / physics.passive_cleaning_tilt_reference_degrees))
    water_factor = min(1.0, condensed_liters_per_m2 / 0.128)
    restored = recoverable * physics.passive_cleaning_base_efficiency * tilt_factor * water_factor
    return min(recoverable, restored * coating_effectiveness)


def apply_bird_removal(
    *,
    current_coverage_fraction: float,
    condensed_liters_per_m2: float,
    coating_effectiveness: float,
    physics: CoatingPhysicsConfig,
) -> BirdRemovalResult:
    if current_coverage_fraction <= 0.0 or condensed_liters_per_m2 <= 0.0 or coating_effectiveness <= 0.0:
        removed = 0.0
    else:
        water_factor = min(1.0, condensed_liters_per_m2 / 0.128)
        candidate = current_coverage_fraction * physics.bird_removal_efficiency * water_factor
        removed = min(current_coverage_fraction, physics.max_bird_removal_fraction_per_day, candidate * coating_effectiveness)
    return BirdRemovalResult(
        removed_coverage_fraction=removed,
        remaining_coverage_fraction=max(0.0, current_coverage_fraction - removed),
    )


def calculate_energy_mechanisms(
    *,
    clean_energy_kwh: float,
    cleanliness_ratio: float,
    optical_transmittance_multiplier: float,
    cooling_delta_c: float,
    gamma_pdc_per_c: float,
) -> EnergyMechanismResult:
    clean = max(0.0, clean_energy_kwh)
    optical_multiplier = min(1.0, max(0.0, optical_transmittance_multiplier))
    clean_ratio = min(1.0, max(0.0, cleanliness_ratio))
    temperature_multiplier = max(0.0, 1.0 + abs(gamma_pdc_per_c) * max(0.0, cooling_delta_c))
    optical_effect = clean * (optical_multiplier - 1.0)
    temperature_effect = clean * optical_multiplier * clean_ratio * (temperature_multiplier - 1.0)
    cleanliness_effect = clean * (clean_ratio - 1.0)
    final = clean + optical_effect + temperature_effect + cleanliness_effect
    final = min(clean, max(0.0, final))
    return EnergyMechanismResult(
        clean_reference_energy_kwh=clean,
        optical_effect_kwh=optical_effect,
        temperature_effect_kwh=temperature_effect,
        cleanliness_effect_kwh=cleanliness_effect,
        final_energy_kwh=final,
        optical_multiplier=optical_multiplier,
        temperature_multiplier=temperature_multiplier,
        cleanliness_ratio=clean_ratio,
    )
```

- [ ] **Step 4: Run physics tests**

Run:

```powershell
python -m pytest tests/unit/test_coating_physics.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```powershell
git add src/solarclean/domain/coating/physics.py tests/unit/test_coating_physics.py
git commit -m "Add coating physical models"
```

## Task 3: Coating State And Strategy

**Files:**
- Create: `src/solarclean/domain/coating/state.py`
- Create: `src/solarclean/domain/coating/strategy.py`
- Modify: `src/solarclean/domain/coating/__init__.py`
- Test: `tests/unit/test_coating_strategy.py`

- [ ] **Step 1: Write failing strategy tests**

```python
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from tests.unit.test_weather import _request

from solarclean.config.loader import load_config
from solarclean.domain.events.tape import generate_event_tape
from solarclean.domain.scenario.contracts import ScenarioContext
from solarclean.domain.simulation.scenario_engine import ScenarioSimulationEngine
from solarclean.domain.coating.strategy import CoatingStrategy
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider


def _context() -> ScenarioContext:
    config = load_config(Path("configs/offline_fixture.yaml"))
    weather = FixtureWeatherProvider().load(_request())
    clean = PVWattsPowerModel().calculate_hourly(weather, config.pv_system)
    dates = [date.fromisoformat(str(day)) for day in clean.daily.index.astype(str)]
    tape = generate_event_tape(
        dates=dates,
        seed=config.soiling.random_seed,
        soiling=config.soiling,
        rainfall=config.rainfall_cleaning,
        farm=config.farm,
        birds=config.bird_droppings,
    )
    return ScenarioContext.from_inputs(
        weather=weather,
        clean_energy=clean,
        event_tape=tape,
        farm_config=config.farm,
        metadata={"event_tape_checksum": tape.checksum()},
    )


def test_coating_strategy_runs_through_shared_engine_and_preserves_tape_checksum() -> None:
    config = load_config(Path("configs/offline_fixture.yaml"))
    context = _context()

    result = ScenarioSimulationEngine(
        CoatingStrategy(
            coating=config.coating,
            soiling=config.soiling,
            rainfall=config.rainfall_cleaning,
            birds=config.bird_droppings,
            farm=config.farm,
            pv_system=config.pv_system,
        )
    ).run(context, random_seed=config.soiling.random_seed)

    frame = result.to_daily_frame()
    assert result.scenario_name == "coating"
    assert len(result.daily_results) == len(context.clean_energy.daily)
    assert (frame["actual_energy_kwh"] <= frame["clean_energy_kwh"] + 1e-9).all()
    assert "extension_event_tape_checksum" in frame.columns
    assert frame["extension_event_tape_checksum"].iloc[0] == context.event_tape.checksum()
    assert "optical_effect_kwh" in result.extension_keys()
    assert "temperature_effect_kwh" in result.extension_keys()
    assert "cleanliness_effect_kwh" in result.extension_keys()


def test_coating_strategy_is_reproducible() -> None:
    config = load_config(Path("configs/offline_fixture.yaml"))
    context = _context()
    strategy = CoatingStrategy(
        coating=config.coating,
        soiling=config.soiling,
        rainfall=config.rainfall_cleaning,
        birds=config.bird_droppings,
        farm=config.farm,
        pv_system=config.pv_system,
    )

    first = ScenarioSimulationEngine(strategy).run(context, random_seed=42)
    second = ScenarioSimulationEngine(strategy).run(context, random_seed=42)

    pd.testing.assert_frame_equal(first.to_daily_frame(), second.to_daily_frame())
    assert [event.to_record() for event in first.events] == [
        event.to_record() for event in second.events
    ]


def test_coating_outputs_water_and_cost_quantities_separately() -> None:
    config = load_config(Path("configs/offline_fixture.yaml"))
    result = ScenarioSimulationEngine(
        CoatingStrategy(
            coating=config.coating,
            soiling=config.soiling,
            rainfall=config.rainfall_cleaning,
            birds=config.bird_droppings,
            farm=config.farm,
            pv_system=config.pv_system,
        )
    ).run(_context(), random_seed=42)

    first = result.daily_results[0]
    assert first.extensions["condensed_water_liters"] >= first.extensions["potentially_collectable_water_liters"]
    assert first.extensions["potentially_collectable_water_liters"] >= first.extensions["actually_collected_water_liters"]
    assert first.operational.coated_panel_count == 10000
    assert first.extensions["coating_cost_basis"]["total_coated_area_m2"] == pytest.approx(20000.0)
    assert first.extensions["coating_cost_basis"]["material_cost_total"] > 0.0
```

- [ ] **Step 2: Run tests to verify they fail for missing strategy module**

Run:

```powershell
python -m pytest tests/unit/test_coating_strategy.py -q
```

Expected: collection fails with `ModuleNotFoundError` or import errors for `CoatingStrategy`.

- [ ] **Step 3: Implement state dataclasses**

Create `src/solarclean/domain/coating/state.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CoatingCohortState:
    cohort_id: int
    panel_count: int
    applied: bool
    age_days: int
    effectiveness_fraction: float
    degradation_fraction: float
    dust_soiling_ratio: float
    bird_drop_coverage_fraction: float
    bird_drop_loss_fraction: float
    cumulative_condensed_water_liters: float = 0.0
    cumulative_potentially_collectable_water_liters: float = 0.0
    cumulative_actually_collected_water_liters: float = 0.0


@dataclass(frozen=True)
class CoatingScenarioState:
    date: date
    cohorts: tuple[CoatingCohortState, ...]
```

- [ ] **Step 4: Implement strategy**

Create `src/solarclean/domain/coating/strategy.py` with these public pieces:

```python
from __future__ import annotations

from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

from solarclean.config.models import (
    BirdDroppingConfig,
    CoatingConfig,
    FarmConfig,
    PVSystemConfig,
    RainfallCleaningConfig,
    SoilingConfig,
)
from solarclean.domain.coating.costs import build_coating_cost_basis
from solarclean.domain.coating.physics import (
    apply_bird_removal,
    calculate_condensation,
    calculate_energy_mechanisms,
    calculate_passive_dust_cleaning,
    calculate_surface_temperature_c,
)
from solarclean.domain.coating.state import CoatingCohortState, CoatingScenarioState
from solarclean.domain.contamination.soiling import ContaminationState, KimberStyleSoilingModel
from solarclean.domain.scenario.contracts import (
    DailyScenarioInput,
    DailyScenarioResult,
    DomainEvent,
    OperationalQuantities,
    ScenarioContext,
    StrategyStep,
)


class CoatingStrategy:
    name = "coating"

    def __init__(
        self,
        *,
        coating: CoatingConfig,
        soiling: SoilingConfig,
        rainfall: RainfallCleaningConfig,
        birds: BirdDroppingConfig,
        farm: FarmConfig,
        pv_system: PVSystemConfig,
    ) -> None:
        self.coating = coating
        self.soiling_model = KimberStyleSoilingModel(soiling, rainfall)
        self.rainfall = rainfall
        self.birds = birds
        self.farm = farm
        self.pv_system = pv_system
        self.cost_basis = build_coating_cost_basis(
            farm=farm,
            deployment=coating.deployment,
            costs=coating.costs,
        )

    def initial_state(self, context: ScenarioContext, rng: np.random.Generator) -> CoatingScenarioState:
        del rng
        first_day = pd.Timestamp(str(next(iter(context.clean_energy.daily.index)))).date()
        cohorts = tuple(
            CoatingCohortState(
                cohort_id=cohort_id,
                panel_count=self.farm.panels_per_cohort,
                applied=self.coating.enabled,
                age_days=0,
                effectiveness_fraction=self.coating.physics.initial_effectiveness_fraction,
                degradation_fraction=0.0,
                dust_soiling_ratio=1.0,
                bird_drop_coverage_fraction=0.0,
                bird_drop_loss_fraction=0.0,
            )
            for cohort_id in range(self.farm.cohort_count)
        )
        return CoatingScenarioState(date=first_day, cohorts=cohorts)
```

Then add the `simulate_day()` method in the same file:

```python
    def simulate_day(
        self,
        day_input: DailyScenarioInput,
        state: object,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> StrategyStep:
        if not isinstance(state, CoatingScenarioState):
            raise TypeError("coating strategy state has the wrong type")
        del rng
        hourly = _hourly_for_day(context.weather.hourly, day_input.date)
        day_water = _daily_water(hourly, self.coating, self.cost_basis.total_coated_area_m2)
        condensed_per_m2 = (
            day_water.condensed_liters / self.cost_basis.total_coated_area_m2
            if self.cost_basis.total_coated_area_m2 > 0.0
            else 0.0
        )
        base_update = self.soiling_model.update(
            ContaminationState(dust_soiling_ratio=_average_dust(state.cohorts)),
            day_input.environment,
            np.random.default_rng(0),
            event_inputs=day_input.event_inputs,
        )
        next_cohorts: list[CoatingCohortState] = []
        events: list[DomainEvent] = []
        for cohort in state.cohorts:
            effectiveness = _effectiveness_after_degradation(cohort, self.coating)
            dust_ratio = base_update.state.dust_soiling_ratio
            dust_ratio = 1.0 - ((1.0 - dust_ratio) * self.coating.physics.dust_accumulation_multiplier)
            restored = calculate_passive_dust_cleaning(
                current_dust_soiling_ratio=dust_ratio,
                condensed_liters_per_m2=condensed_per_m2,
                tilt_degrees=self.pv_system.tilt_degrees,
                coating_effectiveness=effectiveness,
                physics=self.coating.physics,
            )
            dust_ratio = min(1.0, dust_ratio + restored)
            coverage_addition = (
                day_input.event_inputs.bird_coverage_additions.get(cohort.cohort_id, 0.0)
                if day_input.event_inputs is not None
                else 0.0
            )
            coverage = min(1.0, cohort.bird_drop_coverage_fraction + coverage_addition)
            if day_input.environment.precipitation_mm > 0.0:
                coverage *= 1.0 - self.birds.rain_removal_efficiency
            bird = apply_bird_removal(
                current_coverage_fraction=coverage,
                condensed_liters_per_m2=condensed_per_m2,
                coating_effectiveness=effectiveness,
                physics=self.coating.physics,
            )
            bird_loss = min(1.0, bird.remaining_coverage_fraction * self.birds.loss_per_coverage_fraction)
            next_cohorts.append(
                replace(
                    cohort,
                    age_days=cohort.age_days + 1,
                    effectiveness_fraction=effectiveness,
                    degradation_fraction=1.0 - effectiveness,
                    dust_soiling_ratio=dust_ratio,
                    bird_drop_coverage_fraction=bird.remaining_coverage_fraction,
                    bird_drop_loss_fraction=bird_loss,
                    cumulative_condensed_water_liters=cohort.cumulative_condensed_water_liters
                    + day_water.condensed_liters * cohort.panel_count / self.farm.total_panels,
                    cumulative_potentially_collectable_water_liters=cohort.cumulative_potentially_collectable_water_liters
                    + day_water.potentially_collectable_liters * cohort.panel_count / self.farm.total_panels,
                    cumulative_actually_collected_water_liters=cohort.cumulative_actually_collected_water_liters
                    + day_water.actually_collected_liters * cohort.panel_count / self.farm.total_panels,
                )
            )
            if restored > 0.0:
                events.append(
                    DomainEvent(
                        date=day_input.date,
                        event_type="coating_passive_dust_cleaning",
                        magnitude=restored,
                        description="Condensation-assisted coating dust removal.",
                        scenario_name=self.name,
                        cohort_id=cohort.cohort_id,
                        metadata={"condensed_liters_per_m2": condensed_per_m2},
                    )
                )
            if bird.removed_coverage_fraction > 0.0:
                events.append(
                    DomainEvent(
                        date=day_input.date,
                        event_type="coating_bird_dropping_removal",
                        magnitude=bird.removed_coverage_fraction,
                        description="Limited coating-assisted bird-dropping removal.",
                        scenario_name=self.name,
                        cohort_id=cohort.cohort_id,
                        metadata={"condensed_liters_per_m2": condensed_per_m2},
                    )
                )
        if day_water.condensed_liters > 0.0:
            events.append(
                DomainEvent(
                    date=day_input.date,
                    event_type="coating_condensation",
                    magnitude=day_water.condensed_liters,
                    description="Radiative-cooling coating condensed water.",
                    scenario_name=self.name,
                    metadata={"potentially_collectable_liters": day_water.potentially_collectable_liters},
                )
            )
        cleanliness_ratio = _average_cleanliness(tuple(next_cohorts))
        cooling_delta = _mean_cooling_delta(hourly, self.coating)
        energy = calculate_energy_mechanisms(
            clean_energy_kwh=day_input.clean_energy_kwh,
            cleanliness_ratio=cleanliness_ratio,
            optical_transmittance_multiplier=self.coating.physics.optical_transmittance_multiplier,
            cooling_delta_c=cooling_delta,
            gamma_pdc_per_c=self.pv_system.gamma_pdc_per_c,
        )
        checksum = context.event_tape.checksum() if context.event_tape is not None else ""
        extensions = {
            "clean_reference_energy_kwh": energy.clean_reference_energy_kwh,
            "optical_effect_kwh": energy.optical_effect_kwh,
            "temperature_effect_kwh": energy.temperature_effect_kwh,
            "cleanliness_effect_kwh": energy.cleanliness_effect_kwh,
            "final_coated_energy_kwh": energy.final_energy_kwh,
            "optical_multiplier": energy.optical_multiplier,
            "temperature_multiplier": energy.temperature_multiplier,
            "cleanliness_ratio": energy.cleanliness_ratio,
            "condensed_water_liters": day_water.condensed_liters,
            "potentially_collectable_water_liters": day_water.potentially_collectable_liters,
            "actually_collected_water_liters": day_water.actually_collected_liters,
            "coating_age_days": max(cohort.age_days for cohort in next_cohorts),
            "coating_effectiveness_fraction": _average_effectiveness(tuple(next_cohorts)),
            "average_dust_soiling_ratio": _average_dust(tuple(next_cohorts)),
            "average_bird_loss_fraction": _average_bird_loss(tuple(next_cohorts)),
            "coated_area_m2": self.cost_basis.total_coated_area_m2,
            "coating_cost_basis": self.cost_basis.to_record(),
            "event_tape_checksum": checksum,
        }
        result = DailyScenarioResult(
            date=day_input.date,
            scenario_name=self.name,
            clean_energy_kwh=day_input.clean_energy_kwh,
            actual_energy_kwh=energy.final_energy_kwh,
            operational=OperationalQuantities(
                coated_panel_count=self.farm.total_panels,
                water_liters=day_water.actually_collected_liters,
                energy_used_kwh=self.cost_basis.process_energy_kwh / 365.0,
                capex_cost=self.cost_basis.material_cost_total
                + self.cost_basis.surface_preparation_cost_total
                + self.cost_basis.fixed_equipment_setup_cost,
            ),
            events=tuple(events),
            extensions=extensions,
        )
        return StrategyStep(
            state=CoatingScenarioState(date=day_input.date, cohorts=tuple(next_cohorts)),
            result=result,
        )
```

Add helper functions at the end of `strategy.py`:

```python
def _hourly_for_day(hourly: pd.DataFrame, day: date) -> pd.DataFrame:
    frame = hourly.loc[pd.DatetimeIndex(hourly.index).date == day]
    if frame.empty:
        raise ValueError(f"missing hourly weather for coating day {day.isoformat()}")
    return frame


def _daily_water(hourly: pd.DataFrame, coating: CoatingConfig, area_m2: float):
    total_condensed = 0.0
    total_potential = 0.0
    total_actual = 0.0
    for _, row in hourly.iterrows():
        surface = calculate_surface_temperature_c(
            air_temperature_c=float(row["temp_air_c"]),
            relative_humidity_pct=float(row["relative_humidity_pct"]),
            wind_speed_m_s=float(row["wind_speed_m_s"]),
            irradiance_w_m2=float(row["ghi_w_m2"]),
            physics=coating.physics,
        )
        water = calculate_condensation(
            air_temperature_c=float(row["temp_air_c"]),
            relative_humidity_pct=float(row["relative_humidity_pct"]),
            surface_temperature_c=surface,
            exposure_hours=1.0,
            area_m2=area_m2,
            water=coating.water,
        )
        total_condensed += water.condensed_liters
        total_potential += water.potentially_collectable_liters
        total_actual += water.actually_collected_liters
    return type(water)(
        dew_point_c=0.0,
        surface_temperature_c=0.0,
        condensed_liters=total_condensed,
        potentially_collectable_liters=total_potential,
        actually_collected_liters=total_actual,
    )


def _mean_cooling_delta(hourly: pd.DataFrame, coating: CoatingConfig) -> float:
    deltas = []
    for _, row in hourly.iterrows():
        surface = calculate_surface_temperature_c(
            air_temperature_c=float(row["temp_air_c"]),
            relative_humidity_pct=float(row["relative_humidity_pct"]),
            wind_speed_m_s=float(row["wind_speed_m_s"]),
            irradiance_w_m2=float(row["ghi_w_m2"]),
            physics=coating.physics,
        )
        if float(row["ghi_w_m2"]) > 5.0:
            deltas.append(max(0.0, float(row["temp_air_c"]) - surface))
    return float(np.mean(deltas)) if deltas else 0.0


def _effectiveness_after_degradation(
    cohort: CoatingCohortState,
    coating: CoatingConfig,
) -> float:
    daily_degradation = coating.physics.annual_degradation_fraction / 365.0
    degraded = cohort.effectiveness_fraction - daily_degradation
    return min(coating.physics.initial_effectiveness_fraction, max(0.0, degraded))


def _average_dust(cohorts: tuple[CoatingCohortState, ...]) -> float:
    total = sum(cohort.panel_count for cohort in cohorts)
    return sum(cohort.panel_count * cohort.dust_soiling_ratio for cohort in cohorts) / total


def _average_effectiveness(cohorts: tuple[CoatingCohortState, ...]) -> float:
    total = sum(cohort.panel_count for cohort in cohorts)
    return sum(cohort.panel_count * cohort.effectiveness_fraction for cohort in cohorts) / total


def _average_bird_loss(cohorts: tuple[CoatingCohortState, ...]) -> float:
    total = sum(cohort.panel_count for cohort in cohorts)
    return sum(cohort.panel_count * cohort.bird_drop_loss_fraction for cohort in cohorts) / total


def _average_cleanliness(cohorts: tuple[CoatingCohortState, ...]) -> float:
    total = sum(cohort.panel_count for cohort in cohorts)
    weighted = 0.0
    for cohort in cohorts:
        weighted += (
            cohort.panel_count
            * cohort.dust_soiling_ratio
            * (1.0 - cohort.bird_drop_loss_fraction)
        )
    return weighted / total
```

Update `src/solarclean/domain/coating/__init__.py`:

```python
from solarclean.domain.coating.costs import CoatingCostBasis, build_coating_cost_basis
from solarclean.domain.coating.strategy import CoatingStrategy

__all__ = ["CoatingCostBasis", "CoatingStrategy", "build_coating_cost_basis"]
```

- [ ] **Step 5: Run strategy tests**

Run:

```powershell
python -m pytest tests/unit/test_coating_strategy.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```powershell
git add src/solarclean/domain/coating/__init__.py src/solarclean/domain/coating/state.py src/solarclean/domain/coating/strategy.py tests/unit/test_coating_strategy.py
git commit -m "Add coating strategy"
```

## Task 4: Application Use Case, CLI, And Generic Output

**Files:**
- Modify: `src/solarclean/application/use_cases.py`
- Modify: `src/solarclean/cli/main.py`
- Test: `tests/regression/test_t3_coating_scenario.py`

- [ ] **Step 1: Write failing regression test**

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd

from solarclean.application.use_cases import RunCoatingSimulation
from solarclean.config.loader import load_config


def test_run_coating_writes_scenario_outputs(tmp_path: Path) -> None:
    config = load_config(
        Path("configs/offline_fixture.yaml"),
        overrides={"output": {"base_directory": tmp_path}},
    )

    result = RunCoatingSimulation(config).run()

    daily = pd.read_csv(result.output_directory / "scenario_daily_results.csv")
    assert result.summary["command"] == "run-coating"
    assert result.summary["scenario_name"] == "coating"
    assert result.summary["event_tape_checksum"]
    assert result.summary["annual_coating_actual_energy_kwh"] <= result.summary["annual_clean_energy_kwh"]
    assert result.summary["annual_condensed_water_liters"] >= result.summary["annual_potentially_collectable_water_liters"]
    assert result.summary["annual_potentially_collectable_water_liters"] >= result.summary["annual_actually_collected_water_liters"]
    assert "extension_optical_effect_kwh" in daily.columns
    assert "extension_temperature_effect_kwh" in daily.columns
    assert "extension_cleanliness_effect_kwh" in daily.columns
    assert (result.output_directory / "scenario_summary.json").exists()
    assert (result.output_directory / "coating_comparison_summary.json").exists()
```

- [ ] **Step 2: Run regression test to verify it fails for missing use case**

Run:

```powershell
python -m pytest tests/regression/test_t3_coating_scenario.py -q
```

Expected: import error for `RunCoatingSimulation`.

- [ ] **Step 3: Implement use case helpers and `RunCoatingSimulation`**

In `src/solarclean/application/use_cases.py`, add imports:

```python
from solarclean.domain.coating.strategy import CoatingStrategy
from solarclean.domain.events.tape import generate_event_tape
from solarclean.domain.scenario.contracts import ScenarioContext
from solarclean.domain.simulation.scenario_engine import ScenarioSimulationEngine
from solarclean.infrastructure.persistence.reports import write_json_report
```

Add this use case class after `RunBaselineSimulation`:

```python
class RunCoatingSimulation:
    def __init__(self, config: SolarCleanConfig) -> None:
        self.config = config

    def run(self) -> UseCaseResult:
        request = _weather_request(self.config)
        weather = _weather_provider(self.config).load(request)
        profile = PVWattsPowerModel().calculate_hourly(weather, self.config.pv_system)
        dates = [pd.Timestamp(str(day)).date() for day in profile.daily.index]
        event_tape = generate_event_tape(
            dates=dates,
            seed=self.config.soiling.random_seed,
            soiling=self.config.soiling,
            rainfall=self.config.rainfall_cleaning,
            farm=self.config.farm,
            birds=self.config.bird_droppings,
        )
        context = ScenarioContext.from_inputs(
            weather=weather,
            clean_energy=profile,
            event_tape=event_tape,
            farm_config=self.config.farm,
            metadata={"event_tape_checksum": event_tape.checksum()},
        )
        strategy = CoatingStrategy(
            coating=self.config.coating,
            soiling=self.config.soiling,
            rainfall=self.config.rainfall_cleaning,
            birds=self.config.bird_droppings,
            farm=self.config.farm,
            pv_system=self.config.pv_system,
        )
        annual = ScenarioSimulationEngine(strategy).run(
            context,
            random_seed=self.config.soiling.random_seed,
        )
        writer = OutputWriter(self.config)
        output_dir = writer.create_run_directory("run-coating")
        writer.write_config(output_dir)
        writer.write_weather(output_dir, weather)
        writer.write_clean_energy(output_dir, profile)
        writer.write_scenario_result(output_dir, annual)
        metadata = _base_metadata(self.config, "run-coating")
        metadata["weather_metadata"] = weather.metadata
        metadata["pv_metadata"] = profile.metadata
        metadata["event_tape_checksum"] = event_tape.checksum()
        writer.write_metadata(output_dir, metadata)
        summary = _coating_summary(annual, event_tape.checksum())
        writer.write_summary(output_dir, summary)
        writer.write_text_summary(output_dir, summary)
        write_json_report(output_dir / "coating_comparison_summary.json", summary)
        return UseCaseResult(output_directory=output_dir, summary=summary)
```

Add this helper after `_baseline_summary()`:

```python
def _coating_summary(annual, event_tape_checksum: str) -> dict[str, object]:
    condensed = sum(
        float(result.extensions["condensed_water_liters"])
        for result in annual.daily_results
    )
    potential = sum(
        float(result.extensions["potentially_collectable_water_liters"])
        for result in annual.daily_results
    )
    actual_water = sum(
        float(result.extensions["actually_collected_water_liters"])
        for result in annual.daily_results
    )
    optical = sum(float(result.extensions["optical_effect_kwh"]) for result in annual.daily_results)
    temperature = sum(
        float(result.extensions["temperature_effect_kwh"])
        for result in annual.daily_results
    )
    cleanliness = sum(
        float(result.extensions["cleanliness_effect_kwh"])
        for result in annual.daily_results
    )
    return {
        "command": "run-coating",
        "scenario_name": annual.scenario_name,
        "event_tape_checksum": event_tape_checksum,
        "annual_clean_energy_kwh": annual.annual_clean_energy_kwh,
        "annual_coating_actual_energy_kwh": annual.annual_actual_energy_kwh,
        "annual_energy_loss_kwh": annual.annual_energy_loss_kwh,
        "annual_energy_loss_percent": annual.annual_energy_loss_percent,
        "annual_optical_effect_kwh": optical,
        "annual_temperature_effect_kwh": temperature,
        "annual_cleanliness_effect_kwh": cleanliness,
        "annual_condensed_water_liters": condensed,
        "annual_potentially_collectable_water_liters": potential,
        "annual_actually_collected_water_liters": actual_water,
        "cost_basis_available": True,
        "water_revenue_included": False,
        "annualization_included": False,
        "paper_source_status": "prompt_quoted_values_only",
    }
```

- [ ] **Step 4: Add CLI command**

In `src/solarclean/cli/main.py`, import `RunCoatingSimulation` and add:

```python
@app.command("run-coating")
def run_coating(config: ConfigPath) -> None:
    result = RunCoatingSimulation(load_config(config)).run()
    typer.echo(f"Coating scenario run written to {result.output_directory}")
```

- [ ] **Step 5: Run regression test**

Run:

```powershell
python -m pytest tests/regression/test_t3_coating_scenario.py -q
```

Expected: `1 passed`.

- [ ] **Step 6: Run CLI smoke test**

Run:

```powershell
solarclean run-coating --config configs/offline_fixture.yaml
```

Expected: prints `Coating scenario run written to outputs\offline-fixture-run-coating-...`.

- [ ] **Step 7: Commit**

```powershell
git add src/solarclean/application/use_cases.py src/solarclean/cli/main.py tests/regression/test_t3_coating_scenario.py
git commit -m "Add coating scenario application command"
```

## Task 5: Presets And Paper Calibration Fixture

**Files:**
- Add: `configs/coating_weak.yaml`
- Add: `configs/coating_central.yaml`
- Add: `configs/coating_strong.yaml`
- Add: `configs/coating_paper_calibration.yaml`
- Test: `tests/regression/test_t3_coating_scenario.py`

- [ ] **Step 1: Add failing preset and calibration tests**

Append to `tests/regression/test_t3_coating_scenario.py`:

```python
def test_coating_presets_load() -> None:
    for path, preset in [
        ("configs/coating_weak.yaml", "weak"),
        ("configs/coating_central.yaml", "central"),
        ("configs/coating_strong.yaml", "strong"),
        ("configs/coating_paper_calibration.yaml", "paper_calibration"),
    ]:
        config = load_config(Path(path))
        assert config.coating.preset == preset
        assert config.coating.costs.material_cost_per_m2 > 0.0


def test_paper_calibration_reproduces_water_target(tmp_path: Path) -> None:
    config = load_config(
        Path("configs/coating_paper_calibration.yaml"),
        overrides={"output": {"base_directory": tmp_path}},
    )

    result = RunCoatingSimulation(config).run()

    condensed_per_m2 = (
        result.summary["annual_condensed_water_liters"]
        / config.farm.total_panels
        / config.coating.deployment.area_per_panel_m2
    )
    assert condensed_per_m2 == pytest.approx(0.128, abs=0.035)
    assert result.summary["paper_source_status"] == "prompt_quoted_values_only"
```

- [ ] **Step 2: Run preset tests to verify they fail for missing config files**

Run:

```powershell
python -m pytest tests/regression/test_t3_coating_scenario.py::test_coating_presets_load tests/regression/test_t3_coating_scenario.py::test_paper_calibration_reproduces_water_target -q
```

Expected: failures because the new config files do not exist.

- [ ] **Step 3: Add preset config files**

Create `configs/coating_central.yaml` by copying `configs/offline_fixture.yaml` and adding:

```yaml
coating:
  enabled: true
  preset: central
  physics:
    optical_transmittance_multiplier: 0.913
    emissivity_atmospheric_window: 0.90
    contact_angle_degrees: 167
    sliding_angle_degrees: 3
    dust_accumulation_multiplier: 0.35
    initial_effectiveness_fraction: 1.0
    annual_degradation_fraction: 0.08
    max_surface_cooling_c: 7.0
    humidity_cooling_reference_pct: 80
    wind_cooling_decay_per_m_s: 0.08
    daytime_cooling_fraction: 0.35
    passive_cleaning_base_efficiency: 0.55
    passive_cleaning_tilt_reference_degrees: 25
    bird_removal_efficiency: 0.08
    max_bird_removal_fraction_per_day: 0.02
  water:
    condensation_liters_per_m2_per_c_hour: 0.0142
    minimum_relative_humidity_pct: 60
    collectable_water_efficiency_fraction: 0.65
    actual_collection_efficiency_fraction: 0.50
  deployment:
    mode: factory_preinstall
    area_per_panel_m2: 2.0
    useful_life_years: 5
    reapplication_interval_years: 5
    thermal_treatment_temperature_c: 400
    thermal_treatment_duration_minutes: 30
    field_application_demonstrated: false
  costs:
    material_loading_g_per_m2: 12.5
    material_cost_per_m2: 4.0
    surface_preparation_cost_per_m2: 1.5
    application_labor_hours_per_m2: 0.03
    process_energy_kwh_per_m2: 0.2
    fixed_equipment_setup_cost: 5000
    inspection_hours_per_year: 40
    maintenance_cost_per_year: 1200
    useful_life_years: 5
    reapplication_interval_years: 5
    water_collection_infrastructure_cost: 0
    assumption_level: central
    source_status: provisional
```

Create `configs/coating_weak.yaml` with the same base config and these coating differences:

```yaml
coating:
  enabled: true
  preset: weak
  physics:
    optical_transmittance_multiplier: 0.900
    emissivity_atmospheric_window: 0.86
    contact_angle_degrees: 155
    sliding_angle_degrees: 8
    dust_accumulation_multiplier: 0.60
    initial_effectiveness_fraction: 0.85
    annual_degradation_fraction: 0.16
    max_surface_cooling_c: 4.0
    humidity_cooling_reference_pct: 85
    wind_cooling_decay_per_m_s: 0.12
    daytime_cooling_fraction: 0.20
    passive_cleaning_base_efficiency: 0.30
    passive_cleaning_tilt_reference_degrees: 25
    bird_removal_efficiency: 0.03
    max_bird_removal_fraction_per_day: 0.01
  water:
    condensation_liters_per_m2_per_c_hour: 0.0070
    minimum_relative_humidity_pct: 70
    collectable_water_efficiency_fraction: 0.45
    actual_collection_efficiency_fraction: 0.35
  deployment:
    mode: retrofit
    area_per_panel_m2: 2.0
    useful_life_years: 3
    reapplication_interval_years: 3
    thermal_treatment_temperature_c: 400
    thermal_treatment_duration_minutes: 30
    field_application_demonstrated: false
  costs:
    material_loading_g_per_m2: 20
    material_cost_per_m2: 7.0
    surface_preparation_cost_per_m2: 3.0
    application_labor_hours_per_m2: 0.06
    process_energy_kwh_per_m2: 0.4
    fixed_equipment_setup_cost: 9000
    inspection_hours_per_year: 70
    maintenance_cost_per_year: 2500
    useful_life_years: 3
    reapplication_interval_years: 3
    water_collection_infrastructure_cost: 5000
    assumption_level: weak
    source_status: provisional
```

Create `configs/coating_strong.yaml` with the same base config and these coating differences:

```yaml
coating:
  enabled: true
  preset: strong
  physics:
    optical_transmittance_multiplier: 0.930
    emissivity_atmospheric_window: 0.93
    contact_angle_degrees: 170
    sliding_angle_degrees: 2
    dust_accumulation_multiplier: 0.20
    initial_effectiveness_fraction: 1.0
    annual_degradation_fraction: 0.04
    max_surface_cooling_c: 9.0
    humidity_cooling_reference_pct: 78
    wind_cooling_decay_per_m_s: 0.06
    daytime_cooling_fraction: 0.45
    passive_cleaning_base_efficiency: 0.75
    passive_cleaning_tilt_reference_degrees: 25
    bird_removal_efficiency: 0.12
    max_bird_removal_fraction_per_day: 0.03
  water:
    condensation_liters_per_m2_per_c_hour: 0.020
    minimum_relative_humidity_pct: 55
    collectable_water_efficiency_fraction: 0.75
    actual_collection_efficiency_fraction: 0.65
  deployment:
    mode: factory_preinstall
    area_per_panel_m2: 2.0
    useful_life_years: 7
    reapplication_interval_years: 7
    thermal_treatment_temperature_c: 400
    thermal_treatment_duration_minutes: 30
    field_application_demonstrated: false
  costs:
    material_loading_g_per_m2: 8
    material_cost_per_m2: 2.5
    surface_preparation_cost_per_m2: 1.0
    application_labor_hours_per_m2: 0.02
    process_energy_kwh_per_m2: 0.15
    fixed_equipment_setup_cost: 3500
    inspection_hours_per_year: 25
    maintenance_cost_per_year: 800
    useful_life_years: 7
    reapplication_interval_years: 7
    water_collection_infrastructure_cost: 0
    assumption_level: strong
    source_status: provisional
```

Create `configs/coating_paper_calibration.yaml` with one controlled fixture day and the central coating values:

```yaml
simulation:
  start: "2025-01-01T00:00:00+03:00"
  end: "2025-01-01T23:00:00+03:00"
  target_timezone: Asia/Riyadh
  run_id_prefix: coating-paper-calibration
site:
  name: KAUST paper calibration fixture
  latitude: 22.305
  longitude: 39.104
  timezone: Asia/Riyadh
weather:
  provider: fixture
  cache_enabled: true
  cache_directory: data/cache/weather
  missing_data_policy: error
pv_system:
  panel_count: 10000
  panel_capacity_w: 400
  tilt_degrees: 25
  azimuth_degrees: 180
  inverter_efficiency: 0.96
  dc_ac_ratio: 1.15
farm:
  representation: cohort
  total_panels: 10000
  panel_capacity_w: 400
  cohort_count: 100
  panels_per_cohort: 100
  store_cohort_daily_details: true
  cohort_soiling_variation_fraction: 0.0
soiling:
  base_daily_soiling_loss_fraction: 0.000083
  seasonal_multipliers:
    1: 1.0
  dust_event_probability: 0.0
  dust_event_loss_min_fraction: 0.0
  dust_event_loss_max_fraction: 0.0
  minimum_soiling_ratio: 0.70
  stochastic_std_fraction: 0.0
  random_seed: 42
rainfall_cleaning:
  partial_rain_threshold_mm: 1.0
  full_rain_cleaning_threshold_mm: 5.0
  partial_rain_cleaning_efficiency: 0.45
  full_rain_cleaning_efficiency: 0.95
bird_droppings:
  event_probability_per_cohort_day: 0.0
  coverage_min_fraction: 0.0
  coverage_max_fraction: 0.0
  loss_per_coverage_fraction: 0.8
  rain_removal_efficiency: 0.3
coating:
  enabled: true
  preset: paper_calibration
  physics:
    optical_transmittance_multiplier: 0.913
    emissivity_atmospheric_window: 0.90
    contact_angle_degrees: 167
    sliding_angle_degrees: 3
    dust_accumulation_multiplier: 0.05
    initial_effectiveness_fraction: 1.0
    annual_degradation_fraction: 0.02
    max_surface_cooling_c: 7.0
    humidity_cooling_reference_pct: 80
    wind_cooling_decay_per_m_s: 0.08
    daytime_cooling_fraction: 0.35
    passive_cleaning_base_efficiency: 0.75
    passive_cleaning_tilt_reference_degrees: 25
    bird_removal_efficiency: 0.08
    max_bird_removal_fraction_per_day: 0.02
  water:
    condensation_liters_per_m2_per_c_hour: 0.0142
    minimum_relative_humidity_pct: 60
    collectable_water_efficiency_fraction: 0.65
    actual_collection_efficiency_fraction: 0.50
  deployment:
    mode: factory_preinstall
    area_per_panel_m2: 2.0
    useful_life_years: 5
    reapplication_interval_years: 5
    thermal_treatment_temperature_c: 400
    thermal_treatment_duration_minutes: 30
    field_application_demonstrated: false
  costs:
    material_loading_g_per_m2: 12.5
    material_cost_per_m2: 4.0
    surface_preparation_cost_per_m2: 1.5
    application_labor_hours_per_m2: 0.03
    process_energy_kwh_per_m2: 0.2
    fixed_equipment_setup_cost: 5000
    inspection_hours_per_year: 40
    maintenance_cost_per_year: 1200
    useful_life_years: 5
    reapplication_interval_years: 5
    water_collection_infrastructure_cost: 0
    assumption_level: central
    source_status: prompt_quoted
output:
  base_directory: outputs
  include_cohort_daily_details: true
logging:
  level: INFO
```

- [ ] **Step 4: Run preset and calibration tests**

Run:

```powershell
python -m pytest tests/regression/test_t3_coating_scenario.py -q
```

Expected: all tests in that file pass.

- [ ] **Step 5: Commit**

```powershell
git add configs/coating_weak.yaml configs/coating_central.yaml configs/coating_strong.yaml configs/coating_paper_calibration.yaml tests/regression/test_t3_coating_scenario.py
git commit -m "Add coating presets and calibration fixture"
```

## Task 6: Documentation And Progress

**Files:**
- Create: `docs/data_contracts/coating_scenario.md`
- Create: `docs/assumptions/coating_scenario.md`
- Create: `docs/adr/ADR-010-t3-coating-scenario.md`
- Modify: `PROGRESS.md`

- [ ] **Step 1: Write docs**

Create `docs/data_contracts/coating_scenario.md`:

```markdown
# T3 Coating Scenario Data Contract

The coating scenario is a T1 `MitigationStrategy` named `coating`.

Daily coating outputs are stored in `DailyScenarioResult.extensions` and persisted with the `extension_` prefix by `OutputWriter.write_scenario_result()`.

Required extension keys:

| Key | Unit | Meaning |
| --- | --- | --- |
| `clean_reference_energy_kwh` | kWh/day | Unmodified clean PV reference energy. |
| `optical_effect_kwh` | kWh/day | Energy effect of coating optical transmittance. |
| `temperature_effect_kwh` | kWh/day | Energy effect of coated-surface cooling. |
| `cleanliness_effect_kwh` | kWh/day | Energy effect of dust and bird contamination. |
| `final_coated_energy_kwh` | kWh/day | Final scenario energy after separated mechanisms. |
| `condensed_water_liters` | L/day | Total condensed water. |
| `potentially_collectable_water_liters` | L/day | Condensed water after collection hardware efficiency. |
| `actually_collected_water_liters` | L/day | Collected water after actual collection efficiency. |
| `coating_age_days` | days | Age of the oldest active coating state. |
| `coating_effectiveness_fraction` | fraction | Panel-count weighted coating effectiveness. |
| `average_dust_soiling_ratio` | fraction | Panel-count weighted dust ratio. |
| `average_bird_loss_fraction` | fraction | Panel-count weighted bird-dropping loss. |
| `coated_area_m2` | m^2 | Total coated module area. |
| `coating_cost_basis` | JSON object | T4-ready cost quantities without annualization or revenue. |
| `event_tape_checksum` | SHA-256 string | Shared exogenous event tape checksum. |

The scenario does not value collected water as revenue. T4 owns monetary valuation.
```

Create `docs/assumptions/coating_scenario.md`:

```markdown
# T3 Coating Scenario Assumptions

The named coating paper was not available as a PDF or extracted text in the workspace. The implementation uses only the prompt-provided paper facts as calibration anchors.

Prompt-derived anchors:

- 91.3% solar transmittance.
- 0.90 emissivity across the 8-13 um atmospheric window.
- 167 degree contact angle and 3 degree sliding angle.
- Six-month coated-panel power loss near 1.5%, compared with about 28% uncoated.
- Outdoor water yield near 128 g/m^2 per night under the tested conditions.
- Nighttime humidity range of 72-92%.
- 400 C, 30 minute thermal treatment.

Commercial assumptions are provisional. The coating is never treated as free. Material loading, industrial process cost, field application labor, and scalable retrofit feasibility require T5 evidence. The paper's 400 C treatment means direct field application to installed PV modules is not demonstrated.

Condensed water, potentially collectable water, and actually collected water are reported separately. The coating scenario assigns no water revenue.
```

Create `docs/adr/ADR-010-t3-coating-scenario.md`:

```markdown
# ADR-010: T3 Coating Scenario Uses T1 Strategy Extensions

## Status

Accepted.

## Context

Scenario 3 needs coating physics, water accounting, and cost-ready quantities while T4 economics and T5 calibration are developed independently.

## Decision

Implement the coating scenario as `CoatingStrategy`, a T1 `MitigationStrategy`. Store coating-specific values in `DailyScenarioResult.extensions` and `AnnualScenarioResult.extensions`. Expose `CoatingCostBasis` as quantities only, without annualization, tariffs, discounted cash flow, or water revenue.

## Consequences

The shared `ScenarioSimulationEngine` remains the only annual loop. Baseline and coating can share the same exogenous event tape. T4 can consume coating outputs without importing coating physics internals.
```

Append this section to `PROGRESS.md` under Checkpoints:

```markdown
### Checkpoint 12: T3 KAUST-Inspired Coating Scenario

- Status: completed.
- Built:
  - `CoatingStrategy` implemented through the shared `ScenarioSimulationEngine`.
  - Coating physics for dew point, coated-surface cooling, condensation, passive dust cleaning, limited bird-dropping removal, optical effect, thermal effect, and cleanliness effect.
  - `CoatingCostBasis` with coated area, material loading, material cost, surface preparation, application labor, process energy, setup cost, inspection/maintenance quantities, useful life, reapplication interval, and deployment mode.
  - `run-coating` CLI and generic scenario output artifacts.
  - Weak, central, strong, and paper-calibration coating configs.
- Source limitation:
  - The named paper PDF was not present in the workspace. The implementation uses prompt-provided paper facts as calibration anchors and marks cost/process values provisional unless directly prompt-quoted.
- Deployment limitation:
  - The prompt reports a 400 C, 30 minute treatment. Direct field application to installed PV modules is not demonstrated.
- T4/T5 interface requests:
  - T4 should annualize coating cost and value optional water collection outside coating physics.
  - T5 should replace provisional material loading, industrial process, application labor, maintenance, and useful-life assumptions with sourced registry values.
```

- [ ] **Step 2: Commit**

```powershell
git add docs/data_contracts/coating_scenario.md docs/assumptions/coating_scenario.md docs/adr/ADR-010-t3-coating-scenario.md PROGRESS.md
git commit -m "Document T3 coating scenario"
```

## Task 7: Final Verification

**Files:**
- Inspect all changed files.

- [ ] **Step 1: Run focused coating tests**

Run:

```powershell
python -m pytest tests/unit/test_coating_physics.py tests/unit/test_coating_costs.py tests/unit/test_coating_strategy.py tests/regression/test_t3_coating_scenario.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full suite**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass with the existing NASA live test skipped unless explicitly enabled.

- [ ] **Step 3: Run coverage**

Run:

```powershell
python -m pytest --cov=solarclean --cov-report=term-missing
```

Expected: tests pass and coverage remains at or above the previous project threshold shown by project history.

- [ ] **Step 4: Run format and lint checks**

Run:

```powershell
python -m ruff format --check .
python -m ruff check .
```

Expected: format check passes and Ruff reports no lint errors.

- [ ] **Step 5: Run type check**

Run:

```powershell
python -m mypy src
```

Expected: `Success: no issues found`.

- [ ] **Step 6: Run coating CLI smoke test**

Run:

```powershell
solarclean run-coating --config configs/offline_fixture.yaml
```

Expected: command succeeds and writes weather, clean energy, `scenario_daily_results.csv`, `scenario_events.csv`, `scenario_summary.json`, and `coating_comparison_summary.json` under an `outputs/offline-fixture-run-coating-*` directory.

- [ ] **Step 7: Inspect changed files**

Run:

```powershell
git status --short
git diff --stat HEAD
```

Expected: only T3 coating implementation, config, tests, and documentation files changed since the last commit.

## Self-Review Notes

Spec coverage:

- Shared T1 engine integration: Task 3 and Task 4.
- Same event tape checksum: Task 3 and Task 4.
- Physical coating state and degradation: Task 3.
- Dew point, condensation, water accounting, passive cleaning, bird-removal limits, optical/cooling/cleanliness separation: Task 2 and Task 3.
- Cost basis and no free coating: Task 1 and Task 4.
- No economic engine or water revenue: Task 1, Task 4, and Task 6.
- Weak, central, strong, paper-calibration presets: Task 5.
- Documentation and progress update: Task 6.
- Verification gates: Task 7.

Type consistency:

- Config class names used in tests and implementation are defined in Task 1.
- `CoatingStrategy` constructor parameters match Task 3 tests and Task 4 application code.
- Extension keys used in tests, summary code, and docs match the strategy output keys.
