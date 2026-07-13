from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from solarclean.domain.validation.field_validation import (
    CLEAN_REFERENCE_COLUMN,
    MEASURED_COLUMN,
    SIMULATED_COLUMN,
    daily_align,
    mae,
    mbe,
    metric_summary,
    r2,
    rmse,
    stage_metrics,
)


def test_daily_align_inner_joins_calendar_dates() -> None:
    index = pd.date_range("2025-01-01", periods=31, freq="D")
    simulated = pd.Series(np.arange(31, dtype=float), index=index)
    measured = pd.Series(np.arange(30, dtype=float), index=index[1:])

    aligned = daily_align(simulated, measured)

    assert list(aligned.columns) == [SIMULATED_COLUMN, MEASURED_COLUMN]
    assert len(aligned) == 30
    assert aligned.index[0] == pd.Timestamp("2025-01-02")


def test_daily_align_rejects_less_than_thirty_days() -> None:
    index = pd.date_range("2025-01-01", periods=29, freq="D")
    with pytest.raises(ValueError, match="at least 30 overlapping days; found 29"):
        daily_align(pd.Series(1.0, index=index), pd.Series(1.0, index=index))


def test_error_metrics_have_exact_expected_values() -> None:
    frame = pd.DataFrame(
        {
            SIMULATED_COLUMN: [2.0, 4.0, 6.0, 8.0, 10.0],
            MEASURED_COLUMN: [1.0, 5.0, 5.0, 9.0, 10.0],
        }
    )

    assert mae(frame) == pytest.approx(0.8)
    assert rmse(frame) == pytest.approx(np.sqrt(0.8))
    assert mbe(frame) == pytest.approx(0.0)
    assert r2(frame) == pytest.approx(12.0 / 13.0)
    assert metric_summary(frame)["mae_percent"] == pytest.approx(40.0 / 3.0)


def test_percent_metrics_are_unavailable_for_zero_mean_measured_energy() -> None:
    frame = pd.DataFrame(
        {
            SIMULATED_COLUMN: [1.0, 2.0],
            MEASURED_COLUMN: [0.0, 0.0],
        }
    )

    summary = metric_summary(frame)

    assert summary["mae_kwh"] == pytest.approx(1.5)
    assert summary["mae_percent"] is None
    assert summary["rmse_percent"] is None
    assert summary["mbe_percent"] is None


def test_stage_metrics_selects_clean_days_recovery_and_holdout() -> None:
    index = pd.date_range("2025-01-01", periods=8, freq="D")
    clean = pd.Series(100.0, index=index)
    simulated = pd.Series(100.0 - np.arange(8, dtype=float), index=index)
    measured = pd.Series(100.0 - 2.0 * np.arange(8, dtype=float), index=index)
    frame = pd.DataFrame(
        {
            SIMULATED_COLUMN: simulated,
            MEASURED_COLUMN: measured,
            CLEAN_REFERENCE_COLUMN: clean,
        }
    )
    precipitation = pd.Series(0.0, index=index)
    precipitation.iloc[0] = 10.0
    cleaning = pd.Series(0, index=index)
    cleaning.iloc[4] = 1

    stages = stage_metrics(
        frame,
        precipitation,
        cleaning,
        5.0,
        holdout_start="2025-01-07",
    )

    assert stages["clean_days"]["days_used"] == 6
    assert stages["recovery"]["event_count"] == 1
    assert stages["recovery"]["simulated_mean_step_change_kwh"] == pytest.approx(-1.0)
    assert stages["recovery"]["measured_mean_step_change_kwh"] == pytest.approx(-2.0)
    assert stages["holdout"]["days_used"] == 2


def test_stage_metrics_computes_ten_day_dry_spell_slopes() -> None:
    index = pd.date_range("2025-01-01", periods=10, freq="D")
    frame = pd.DataFrame(
        {
            SIMULATED_COLUMN: 100.0 - np.arange(10, dtype=float),
            MEASURED_COLUMN: 100.0 - 2.0 * np.arange(10, dtype=float),
            CLEAN_REFERENCE_COLUMN: 100.0,
        },
        index=index,
    )

    stages = stage_metrics(
        frame,
        pd.Series(0.0, index=index),
        pd.Series(0, index=index),
        5.0,
    )

    assert stages["decline_slopes"]["dry_spell_count"] == 1
    assert stages["decline_slopes"]["simulated_mean_slope_per_day"] == pytest.approx(-0.01)
    assert stages["decline_slopes"]["measured_mean_slope_per_day"] == pytest.approx(-0.02)
    assert stages["decline_slopes"]["simulated_to_measured_slope_ratio"] == pytest.approx(0.5)
