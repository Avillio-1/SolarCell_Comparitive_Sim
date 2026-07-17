from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from solarclean.config.loader import load_config
from solarclean.config.models import (
    RainfallCleaningConfig,
    ReactiveCVObserverConfig,
    SoilingConfig,
    SolarCleanConfig,
)


def test_loads_default_riyadh_site_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
simulation:
  start: "2025-01-01T00:00:00+03:00"
  end: "2025-01-03T23:00:00+03:00"
  target_timezone: Asia/Riyadh
site:
  name: Riyadh
  latitude: 24.7136
  longitude: 46.6753
  timezone: Asia/Riyadh
weather:
  provider: fixture
pv_system:
  panel_count: 10000
  panel_capacity_w: 400
farm:
  representation: cohort
  total_panels: 10000
  panel_capacity_w: 400
  cohort_count: 100
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.site.name == "Riyadh"
    assert config.site.latitude == pytest.approx(24.7136)
    assert config.weather.provider == "fixture"
    assert config.simulation.start.tzinfo is not None
    assert config.simulation.target_timezone == "Asia/Riyadh"


def test_invalid_cohort_product_fails() -> None:
    with pytest.raises(ValueError, match="cohort_count .* panels_per_cohort"):
        SolarCleanConfig.model_validate(
            {
                "simulation": {
                    "start": datetime(2025, 1, 1, tzinfo=ZoneInfo("Asia/Riyadh")),
                    "end": datetime(2025, 1, 2, tzinfo=ZoneInfo("Asia/Riyadh")),
                    "target_timezone": "Asia/Riyadh",
                },
                "site": {
                    "name": "Riyadh",
                    "latitude": 24.7136,
                    "longitude": 46.6753,
                    "timezone": "Asia/Riyadh",
                },
                "weather": {"provider": "fixture"},
                "pv_system": {"panel_count": 10000, "panel_capacity_w": 400},
                "farm": {
                    "representation": "cohort",
                    "total_panels": 10000,
                    "panel_capacity_w": 400,
                    "cohort_count": 99,
                    "panels_per_cohort": 100,
                },
            }
        )


def test_invalid_weather_provider_fails() -> None:
    with pytest.raises(ValueError, match="weather.provider"):
        SolarCleanConfig.model_validate(
            {
                "simulation": {
                    "start": datetime(2025, 1, 1, tzinfo=ZoneInfo("Asia/Riyadh")),
                    "end": datetime(2025, 1, 2, tzinfo=ZoneInfo("Asia/Riyadh")),
                    "target_timezone": "Asia/Riyadh",
                },
                "site": {
                    "name": "Riyadh",
                    "latitude": 24.7136,
                    "longitude": 46.6753,
                    "timezone": "Asia/Riyadh",
                },
                "weather": {"provider": "unknown"},
                "pv_system": {"panel_count": 10000, "panel_capacity_w": 400},
                "farm": {
                    "representation": "representative",
                    "total_panels": 10000,
                    "panel_capacity_w": 400,
                },
            }
        )


def test_end_must_be_after_start() -> None:
    with pytest.raises(ValueError, match="after simulation.start"):
        SolarCleanConfig.model_validate(
            {
                "simulation": {
                    "start": datetime(2025, 1, 2, tzinfo=ZoneInfo("Asia/Riyadh")),
                    "end": datetime(2025, 1, 1, tzinfo=ZoneInfo("Asia/Riyadh")),
                    "target_timezone": "Asia/Riyadh",
                },
                "site": {
                    "name": "Riyadh",
                    "latitude": 24.7136,
                    "longitude": 46.6753,
                    "timezone": "Asia/Riyadh",
                },
                "weather": {"provider": "fixture"},
                "pv_system": {"panel_count": 10000, "panel_capacity_w": 400},
                "farm": {
                    "representation": "representative",
                    "total_panels": 10000,
                    "panel_capacity_w": 400,
                },
            }
        )


def test_site_and_simulation_timezones_must_match() -> None:
    payload = load_config(Path("configs/default.yaml")).model_dump(mode="python")
    payload["site"]["timezone"] = "UTC"

    with pytest.raises(ValueError, match="site.timezone must equal simulation.target_timezone"):
        SolarCleanConfig.model_validate(payload)


def test_dst_timezone_accepts_offsets_that_match_each_local_date() -> None:
    payload = load_config(Path("configs/default.yaml")).model_dump(mode="python")
    timezone = ZoneInfo("Europe/Berlin")
    payload["simulation"].update(
        {
            "start": datetime(2025, 6, 1, tzinfo=timezone),
            "end": datetime(2025, 12, 31, 23, tzinfo=timezone),
            "target_timezone": "Europe/Berlin",
        }
    )
    payload["site"]["timezone"] = "Europe/Berlin"

    config = SolarCleanConfig.model_validate(payload)

    assert config.simulation.start.isoformat() == "2025-06-01T00:00:00+02:00"
    assert config.simulation.end.isoformat() == "2025-12-31T23:00:00+01:00"


def test_timezone_name_with_incorrect_numeric_offset_is_rejected() -> None:
    payload = load_config(Path("configs/default.yaml")).model_dump(mode="python")
    payload["simulation"].update(
        {
            "start": datetime.fromisoformat("2025-06-01T00:00:00+03:00"),
            "end": datetime.fromisoformat("2025-12-31T23:00:00+03:00"),
            "target_timezone": "Europe/Berlin",
        }
    )
    payload["site"]["timezone"] = "Europe/Berlin"

    with pytest.raises(ValueError, match="UTC offset does not match"):
        SolarCleanConfig.model_validate(payload)


@pytest.mark.parametrize("field", ["partial_rain_threshold_mm", "full_rain_cleaning_threshold_mm"])
def test_zero_rain_threshold_is_rejected(field: str) -> None:
    with pytest.raises(ValueError):
        RainfallCleaningConfig.model_validate({field: 0.0})


@pytest.mark.parametrize(
    "multipliers",
    [
        {0: 1.0},
        {13: 1.0},
        {1: -1.0},
        {1: float("inf")},
    ],
)
def test_invalid_seasonal_multiplier_is_rejected(multipliers: dict[int, float]) -> None:
    with pytest.raises(ValueError, match="seasonal multiplier"):
        SoilingConfig(seasonal_multipliers=multipliers)


def test_reactive_observer_default_matches_main_config_and_registry_central() -> None:
    config = load_config(Path("configs/default.yaml"))
    registry = Path("data/calibration/parameter_registry.yaml")
    assert ReactiveCVObserverConfig().false_positive_rate == pytest.approx(0.08)
    assert config.reactive_cv.observer.false_positive_rate == pytest.approx(0.08)
    assert "central_value: 0.08" in registry.read_text(encoding="utf-8")
