from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from solarclean.config.loader import load_config
from solarclean.domain.calibration.registry import CalibrationParameter, ParameterRegistry
from solarclean.domain.economics.calibration import build_economics_from_parameter_registry

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "data" / "calibration" / "parameter_registry.yaml"
PRESET_DIR = ROOT / "configs" / "calibration"

REQUIRED_FIELDS = {
    "name",
    "configuration_path",
    "category",
    "central_value",
    "low_value",
    "high_value",
    "unit",
    "source",
    "evidence_type",
    "source_geography_and_climate",
    "applicability_to_saudi_conditions",
    "confidence",
    "status",
    "rationale",
    "limitations",
    "responsible_module_or_owner",
}

REQUIRED_CATEGORIES = {
    "soiling",
    "seasonality",
    "dust_events",
    "rainfall_cleaning",
    "bird_droppings",
    "computer_vision",
    "drone_inspection_cleaning",
    "coating",
    "economics",
}


def test_authoritative_parameter_registry_is_complete_and_queryable() -> None:
    registry = ParameterRegistry.from_yaml(REGISTRY_PATH)

    assert registry.metadata["registry_name"] == "solarclean_dt_t5_parameter_registry"
    assert registry.metadata["target_site"] == "Riyadh, Saudi Arabia"
    assert len(registry.parameters) >= 35
    assert {parameter.category for parameter in registry.parameters} >= REQUIRED_CATEGORIES

    names = [parameter.name for parameter in registry.parameters]
    assert len(names) == len(set(names))

    for parameter in registry.parameters:
        record = parameter.to_record()
        assert record.keys() >= REQUIRED_FIELDS
        assert parameter.evidence_type in {
            "measured",
            "calculated",
            "inferred",
            "quoted",
            "assumed",
        }
        assert parameter.confidence in {"high", "medium", "low"}
        assert parameter.status in {"validated", "provisional", "blocked", "unsourced"}
        assert parameter.low_value <= parameter.central_value <= parameter.high_value
        assert parameter.configuration_path
        assert parameter.responsible_module_or_owner

    soiling_rate = registry.get("soiling.base_daily_loss_fraction")
    assert soiling_rate.configuration_path == "soiling.base_daily_soiling_loss_fraction"
    assert soiling_rate.status == "provisional"
    assert soiling_rate.central_value == pytest.approx(0.001)

    baseline_target = registry.get("soiling.no_clean_annual_loss_target_fraction")
    assert baseline_target.central_value == pytest.approx(0.25)
    assert baseline_target.low_value == pytest.approx(0.12)
    assert baseline_target.high_value == pytest.approx(0.40)

    coating_multiplier = registry.get("coating.dust_accumulation_multiplier")
    assert coating_multiplier.central_value == pytest.approx(0.70)

    coating_life = registry.get("coating.useful_life_years")
    assert coating_life.central_value == pytest.approx(3.0)


def test_calibration_presets_are_valid_current_config_overlays() -> None:
    allowed_current_sections = {"soiling", "rainfall_cleaning", "bird_droppings", "farm"}
    configs = {}

    for preset_name in ("low", "central", "high"):
        preset_path = PRESET_DIR / f"{preset_name}.yaml"
        config = load_config(
            ROOT / "configs" / "riyadh_2025.yaml",
            overrides=_load_yaml(preset_path),
        )
        configs[preset_name] = config
        assert set(_load_yaml(preset_path)) <= allowed_current_sections
        assert config.weather.provider == "nasa_power"
        assert config.pv_system.panel_count == 10000

    assert (
        configs["low"].soiling.base_daily_soiling_loss_fraction
        < configs["central"].soiling.base_daily_soiling_loss_fraction
        < configs["high"].soiling.base_daily_soiling_loss_fraction
    )
    assert (
        configs["low"].bird_droppings.event_probability_per_cohort_day
        < configs["central"].bird_droppings.event_probability_per_cohort_day
        < configs["high"].bird_droppings.event_probability_per_cohort_day
    )


def test_sensitivity_script_dry_run_uses_phase35_production_interface() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/calibration/run_preset_sensitivity.py",
            "--base-config",
            "configs/offline_fixture.yaml",
            "--preset-dir",
            "configs/calibration",
            "--dry-run",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["mode"] == "dry_run"
    assert payload["production_interface"] == "solarclean.application.phase35.Phase35Validator"
    assert [item["preset"] for item in payload["presets"]] == ["low", "central", "high"]
    assert all("base_daily_soiling_loss_fraction" in item for item in payload["presets"])


def test_economics_registry_bridge_builds_expected_config() -> None:
    registry = ParameterRegistry.from_yaml(REGISTRY_PATH)

    calibration = build_economics_from_parameter_registry(registry)

    assert calibration.config.tariff_sar_per_kwh == pytest.approx(0.18)
    assert calibration.config.discount_rate == pytest.approx(0.08)
    assert calibration.config.useful_life_years == 15

    crew_rate = calibration.reactive_cost_rates.crew_hour
    assert crew_rate is not None
    assert crew_rate.amount_sar_per_unit == pytest.approx(35.0)
    assert crew_rate.quantity_unit == "hour"

    assert len(calibration.equipment_cost_components) == 2
    drone_capex = calibration.equipment_cost_components[0]
    assert drone_capex.name == "drone equipment capex"
    assert drone_capex.category == "capex"
    assert drone_capex.amount_sar == pytest.approx(150_000.0)
    overhead = calibration.equipment_cost_components[1]
    assert overhead.name == "reactive annual overhead opex"
    assert overhead.category == "opex"
    assert overhead.amount_sar == pytest.approx(100_000.0)

    drone_rate = calibration.reactive_cost_rates.drone_flight_hour
    assert drone_rate is not None
    assert drone_rate.amount_sar_per_unit == pytest.approx(180.0)
    energy_rate = calibration.reactive_cost_rates.energy_kwh
    assert energy_rate is not None
    assert energy_rate.amount_sar_per_unit == pytest.approx(0.18)


def test_economics_registry_bridge_converts_water_m3_to_liter_rate() -> None:
    registry = ParameterRegistry.from_yaml(REGISTRY_PATH)

    calibration = build_economics_from_parameter_registry(registry)

    water_rate = calibration.reactive_cost_rates.water_liter
    assert water_rate is not None
    assert water_rate.amount_sar_per_unit == pytest.approx(0.006)
    assert water_rate.quantity_unit == "liter"
    assert "conversion=1 m3 = 1000 liters" in str(water_rate.notes)


def test_economics_registry_bridge_preserves_metadata_and_status() -> None:
    registry = ParameterRegistry.from_yaml(REGISTRY_PATH)

    calibration = build_economics_from_parameter_registry(registry)
    metadata_by_key = {
        metadata.registry_key: metadata for metadata in calibration.parameter_metadata
    }

    labour_metadata = metadata_by_key["economics.labour_cost_sar_per_hour"]
    crew_rate = calibration.reactive_cost_rates.crew_hour
    assert crew_rate is not None
    assert crew_rate.source == labour_metadata.source
    assert crew_rate.source_status == "blocked"
    assert labour_metadata.status == "blocked"
    assert labour_metadata.confidence == "low"
    assert labour_metadata.evidence_type == "inferred"
    assert labour_metadata.unit == "SAR/worker_hour"
    assert "registry_key=economics.labour_cost_sar_per_hour" in str(crew_rate.notes)
    assert "evidence_type=inferred" in str(crew_rate.notes)
    assert "confidence=low" in str(crew_rate.notes)

    drone_capex = calibration.equipment_cost_components[0]
    assert drone_capex.source_status == "blocked"
    assert "registry_key=economics.drone_equipment_cost_sar" in str(drone_capex.notes)
    assert "total equipment cost" in str(drone_capex.notes)


def test_economics_registry_bridge_warns_for_blocked_values_by_default() -> None:
    registry = ParameterRegistry.from_yaml(REGISTRY_PATH)

    calibration = build_economics_from_parameter_registry(registry)
    warnings_by_key = {warning.registry_key: warning for warning in calibration.warnings}

    warning = warnings_by_key["economics.electricity_tariff_sar_per_kwh"]
    assert warning.status == "blocked"
    assert "economics.electricity_tariff_sar_per_kwh has status blocked" in warning.message


def test_economics_registry_bridge_strict_policy_rejects_blocked_values() -> None:
    registry = ParameterRegistry.from_yaml(REGISTRY_PATH)

    with pytest.raises(
        ValueError,
        match=r"economics\.electricity_tariff_sar_per_kwh \(status=blocked\)",
    ):
        build_economics_from_parameter_registry(
            registry,
            status_policy="require_validated",
        )


def test_economics_registry_bridge_rejects_unknown_water_units() -> None:
    registry = ParameterRegistry.from_yaml(REGISTRY_PATH)
    water = registry.get("economics.water_cost_sar_per_m3")
    registry_with_bad_water_unit = _registry_with_parameter(
        registry,
        replace(water, unit="SAR/gallon"),
    )

    with pytest.raises(
        ValueError,
        match=r"economics\.water_cost_sar_per_m3 uses unit 'SAR/gallon'; expected 'SAR/m3'",
    ):
        build_economics_from_parameter_registry(registry_with_bad_water_unit)


def test_economics_registry_bridge_missing_keys_fail_clearly() -> None:
    registry = ParameterRegistry.from_yaml(REGISTRY_PATH)
    registry_without_water = ParameterRegistry(
        metadata=registry.metadata,
        parameters=tuple(
            parameter
            for parameter in registry.parameters
            if parameter.name != "economics.water_cost_sar_per_m3"
        ),
    )

    with pytest.raises(
        ValueError,
        match=r"missing required economics calibration parameter\(s\): "
        r"economics\.water_cost_sar_per_m3",
    ):
        build_economics_from_parameter_registry(registry_without_water)


def _registry_with_parameter(
    registry: ParameterRegistry,
    replacement_parameter: CalibrationParameter,
) -> ParameterRegistry:
    return ParameterRegistry(
        metadata=registry.metadata,
        parameters=tuple(
            replacement_parameter if parameter.name == replacement_parameter.name else parameter
            for parameter in registry.parameters
        ),
    )


def _load_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    assert isinstance(raw, dict)
    return raw
