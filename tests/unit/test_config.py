from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from solarclean.config.loader import load_config
from solarclean.config.models import SolarCleanConfig


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
