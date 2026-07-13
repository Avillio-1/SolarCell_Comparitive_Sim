from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pandas as pd

from solarclean.domain.environment.weather import CANONICAL_WEATHER_COLUMNS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "crosscheck_pvgis_irradiance.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("crosscheck_pvgis_irradiance", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_pvgis_tmy_produces_canonical_timezone_aware_frame() -> None:
    script = _load_script()
    payload = {
        "outputs": {
            "tmy_hourly": [
                {
                    "time(UTC)": f"20190101:{hour:02d}00",
                    "T2m": 15.0 + hour,
                    "RH": 40.0 + hour,
                    "G(h)": 100.0 * hour,
                    "Gb(n)": 80.0 * hour,
                    "Gd(h)": 20.0 * hour,
                    "WS10m": 2.0 + hour / 10.0,
                }
                for hour in range(6)
            ]
        }
    }

    frame = script.normalize_pvgis_tmy(payload)

    assert list(frame.columns) == list(CANONICAL_WEATHER_COLUMNS)
    assert isinstance(frame.index, pd.DatetimeIndex)
    assert frame.index.tz is not None
    assert str(frame.index.tz) == "Asia/Riyadh"
    assert frame.index[0] == pd.Timestamp("2025-01-01T03:00:00+03:00")
    assert frame.iloc[3].to_dict() == {
        "ghi_w_m2": 300.0,
        "dni_w_m2": 240.0,
        "dhi_w_m2": 60.0,
        "temp_air_c": 18.0,
        "wind_speed_m_s": 2.3,
        "relative_humidity_pct": 43.0,
        "precipitation_mm": 0.0,
    }
