from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pandas as pd

from solarclean.config.models import RainfallCleaningConfig, SoilingConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "benchmark_soiling_vs_published.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("benchmark_soiling_vs_published", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_hourly_weather() -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=30 * 24, freq="h", tz="Asia/Riyadh")
    frame = pd.DataFrame(
        {
            "precipitation_mm": 0.0,
            "relative_humidity_pct": 30.0,
        },
        index=index,
    )
    frame.loc[pd.Timestamp("2025-01-21 12:00", tz="Asia/Riyadh"), "precipitation_mm"] = 10.0
    return frame


def test_project_model_decreases_when_dry_and_jumps_on_rain() -> None:
    module = _load_script()
    _, daily = module.derive_weather_inputs(_synthetic_hourly_weather(), "Asia/Riyadh")
    soiling = SoilingConfig(stochastic_std_fraction=0.0, dust_event_probability=0.0)
    ratios = module.run_project_model(
        daily,
        soiling,
        RainfallCleaningConfig(),
        seed=0,
    )

    assert len(ratios) == 30
    assert ratios.iloc[18] < ratios.iloc[0]
    assert ratios.iloc[19] < ratios.iloc[18]
    assert ratios.iloc[20] > ratios.iloc[19]
    assert ratios.iloc[-1] < ratios.iloc[20]


def test_kimber_ratio_is_restored_after_rain() -> None:
    module = _load_script()
    hourly_rain, _ = module.derive_weather_inputs(_synthetic_hourly_weather(), "Asia/Riyadh")
    ratios = module.run_kimber_model(
        hourly_rain,
        soiling_loss_rate=0.001,
        cleaning_threshold=5.0,
    )
    daily_ratios = module.daily_end(ratios)

    assert len(daily_ratios) == 30
    assert daily_ratios.iloc[19] < 1.0
    assert daily_ratios.iloc[20] == 1.0
