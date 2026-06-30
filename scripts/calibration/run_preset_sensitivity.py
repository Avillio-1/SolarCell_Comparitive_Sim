from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from solarclean.application.phase35 import Phase35Validator  # noqa: E402
from solarclean.config.loader import load_config  # noqa: E402
from solarclean.config.models import SolarCleanConfig  # noqa: E402

PRESET_NAMES = ("low", "central", "high")
PRODUCTION_INTERFACE = "solarclean.application.phase35.Phase35Validator"


def run_preset_sensitivity(
    *,
    base_config_path: Path,
    preset_dir: Path,
    dry_run: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "mode": "dry_run" if dry_run else "execute",
        "production_interface": PRODUCTION_INTERFACE,
        "base_config": str(base_config_path),
        "preset_directory": str(preset_dir),
        "presets": [],
    }
    preset_summaries: list[dict[str, object]] = []
    for preset_name in PRESET_NAMES:
        config = _load_with_overlay(base_config_path, preset_dir / f"{preset_name}.yaml")
        summary = _summarize_config(preset_name, config)
        if not dry_run:
            result = Phase35Validator(config).run()
            summary["output_directory"] = str(result.output_directory)
            summary["phase35_summary"] = result.summary
        preset_summaries.append(summary)
    payload["presets"] = preset_summaries
    return payload


def _load_with_overlay(base_config_path: Path, overlay_path: Path) -> SolarCleanConfig:
    with overlay_path.open("r", encoding="utf-8") as handle:
        overlay = yaml.safe_load(handle) or {}
    if not isinstance(overlay, dict):
        raise ValueError(f"preset overlay must contain a mapping: {overlay_path}")
    return load_config(base_config_path, overrides=overlay)


def _summarize_config(preset: str, config: SolarCleanConfig) -> dict[str, object]:
    return {
        "preset": preset,
        "base_daily_soiling_loss_fraction": config.soiling.base_daily_soiling_loss_fraction,
        "dust_event_probability": config.soiling.dust_event_probability,
        "dust_event_loss_min_fraction": config.soiling.dust_event_loss_min_fraction,
        "dust_event_loss_max_fraction": config.soiling.dust_event_loss_max_fraction,
        "partial_rain_threshold_mm": config.rainfall_cleaning.partial_rain_threshold_mm,
        "full_rain_cleaning_threshold_mm": config.rainfall_cleaning.full_rain_cleaning_threshold_mm,
        "bird_event_probability_per_cohort_day": (
            config.bird_droppings.event_probability_per_cohort_day
        ),
        "cohort_soiling_variation_fraction": config.farm.cohort_soiling_variation_fraction,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run or dry-run SolarClean-DT calibration presets through production models."
    )
    parser.add_argument(
        "--base-config",
        type=Path,
        default=Path("configs/offline_fixture.yaml"),
        help="Base SolarClean config accepted by SolarCleanConfig.",
    )
    parser.add_argument(
        "--preset-dir",
        type=Path,
        default=Path("configs/calibration"),
        help="Directory containing low.yaml, central.yaml, and high.yaml overlays.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve configs and print inputs without running Phase35Validator.",
    )
    args = parser.parse_args(argv)
    payload = run_preset_sensitivity(
        base_config_path=args.base_config,
        preset_dir=args.preset_dir,
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(_json_safe(payload), indent=2, sort_keys=True))
    return 0


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
