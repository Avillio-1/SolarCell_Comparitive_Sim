from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from solarclean.config.loader import load_config
from solarclean.domain.calibration.registry import ParameterRegistry

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


def _load_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    assert isinstance(raw, dict)
    return raw
