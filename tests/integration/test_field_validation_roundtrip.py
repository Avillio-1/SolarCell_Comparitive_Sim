from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import pytest
from tests.config_factory import full_year_fixture_config

from solarclean.application.field_validation import (
    FieldValidationHarness,
    simulate_baseline,
)


def test_field_validation_synthetic_roundtrip_and_negative_control(tmp_path: Path) -> None:
    config = full_year_fixture_config(
        {
            "farm": {"representation": "representative"},
            "output": {
                "base_directory": tmp_path / "outputs",
                "include_cohort_daily_details": False,
            },
        }
    )
    baseline = simulate_baseline(config)
    truth = baseline.daily["actual_energy_kwh"].astype(float)
    dates = pd.DatetimeIndex(pd.to_datetime(truth.index)).tz_localize("Asia/Riyadh")
    rng = np.random.default_rng(0)
    measured = truth.to_numpy() * (1.0 + rng.normal(0.0, 0.02, len(truth)))
    measured_path = tmp_path / "synthetic_measured.csv"
    _write_measured_csv(measured_path, dates, measured)
    holdout_position = int(len(dates) * 0.75)
    holdout_start = dates[holdout_position].date()

    result = FieldValidationHarness(config, measured_path, holdout_start).run()
    overall = cast(dict[str, float], result.report["overall"])
    stages = cast(dict[str, object], result.report["stages"])
    holdout = cast(dict[str, float], stages["holdout"])

    assert overall["r2"] > 0.95
    assert holdout["r2"] > 0.95
    assert abs(overall["mbe_percent"]) < 1.0
    assert 0.5 < overall["mae_percent"] < 5.0
    json_path = result.output_directory / "field_validation_report.json"
    markdown_path = result.output_directory / "field_validation_report.md"
    assert json_path.exists()
    assert markdown_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["overall"]["r2"] > 0.95

    biased_path = tmp_path / "synthetic_measured_biased.csv"
    _write_measured_csv(biased_path, dates, measured * 1.10)
    biased_result = FieldValidationHarness(config, biased_path, holdout_start).run()
    biased_overall = cast(dict[str, float], biased_result.report["overall"])
    assert biased_overall["mbe_percent"] == pytest.approx(-9.1, abs=1.0)


def _write_measured_csv(path: Path, dates: pd.DatetimeIndex, energy: np.ndarray) -> None:
    pd.DataFrame(
        {
            "timestamp": [timestamp.isoformat() for timestamp in dates],
            "measured_ac_energy_kwh": energy,
            "cleaning_event": np.zeros(len(dates), dtype=int),
        }
    ).to_csv(path, index=False)
