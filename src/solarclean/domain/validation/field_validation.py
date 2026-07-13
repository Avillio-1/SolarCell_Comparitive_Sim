from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

SIMULATED_COLUMN = "simulated_energy_kwh"
MEASURED_COLUMN = "measured_energy_kwh"
CLEAN_REFERENCE_COLUMN = "clean_energy_kwh"
MINIMUM_OVERLAP_DAYS = 30


def daily_align(simulated: pd.Series, measured: pd.Series) -> pd.DataFrame:
    """Inner-align two daily energy series on unique, normalized calendar dates."""

    simulated_daily = _daily_series(simulated, SIMULATED_COLUMN)
    measured_daily = _daily_series(measured, MEASURED_COLUMN)
    aligned = pd.concat([simulated_daily, measured_daily], axis=1, join="inner").dropna()
    if len(aligned) < MINIMUM_OVERLAP_DAYS:
        raise ValueError(
            "field validation requires at least "
            f"{MINIMUM_OVERLAP_DAYS} overlapping days; found {len(aligned)}"
        )
    return aligned.sort_index()


def mae(df: pd.DataFrame) -> float:
    return float(_errors(df).abs().mean())


def rmse(df: pd.DataFrame) -> float:
    errors = _errors(df)
    return float(np.sqrt(float((errors**2).mean())))


def mbe(df: pd.DataFrame) -> float:
    """Mean bias error in kWh, using simulated minus measured."""

    return float(_errors(df).mean())


def r2(df: pd.DataFrame) -> float:
    simulated, measured = _energy_columns(df)
    residual_sum = float(((measured - simulated) ** 2).sum())
    total_sum = float(((measured - measured.mean()) ** 2).sum())
    if total_sum == 0.0:
        return 1.0 if residual_sum == 0.0 else 0.0
    return float(1.0 - residual_sum / total_sum)


def metric_summary(df: pd.DataFrame) -> dict[str, float | int | None]:
    """Return daily error metrics and percent errors relative to mean measured energy."""

    _require_nonempty(df)
    measured_mean = float(df[MEASURED_COLUMN].mean())
    mae_value = mae(df)
    rmse_value = rmse(df)
    mbe_value = mbe(df)
    mae_percent = None if measured_mean == 0.0 else mae_value / measured_mean * 100.0
    rmse_percent = None if measured_mean == 0.0 else rmse_value / measured_mean * 100.0
    mbe_percent = None if measured_mean == 0.0 else mbe_value / measured_mean * 100.0
    return {
        "days_used": len(df),
        "mae_kwh": mae_value,
        "mae_percent": mae_percent,
        "rmse_kwh": rmse_value,
        "rmse_percent": rmse_percent,
        "mbe_kwh": mbe_value,
        "mbe_percent": mbe_percent,
        "r2": r2(df),
    }


def stage_metrics(
    df: pd.DataFrame,
    precip_daily_mm: pd.Series,
    cleaning_flags: pd.Series,
    full_rain_threshold_mm: float,
    *,
    holdout_start: date | str | pd.Timestamp | None = None,
) -> dict[str, dict[str, object]]:
    """Compute staged diagnostics for clean generation, decline, recovery, and holdout."""

    _require_nonempty(df)
    if full_rain_threshold_mm < 0.0:
        raise ValueError("full_rain_threshold_mm must be non-negative")
    index = _date_index(df.index)
    working = df.copy()
    working.index = index
    precipitation = _aligned_numeric(precip_daily_mm, index, default=0.0)
    cleaning = _aligned_numeric(cleaning_flags, index, default=0.0).astype(bool)
    reset_events = cleaning | (precipitation >= full_rain_threshold_mm)

    clean_mask = pd.Series(False, index=index)
    for event_day in index[reset_events.to_numpy()]:
        elapsed = (index - event_day).days
        clean_mask |= (elapsed >= 0) & (elapsed <= 2)
    clean_frame = working.loc[clean_mask]

    dry_spells = _dry_spells(index, reset_events)
    simulated_slopes: list[float] = []
    measured_slopes: list[float] = []
    for spell in dry_spells:
        spell_frame = working.loc[spell]
        simulated_pi, measured_pi = _performance_indices(spell_frame)
        x = np.arange(len(simulated_pi), dtype=float)
        simulated_slopes.append(float(np.polyfit(x, simulated_pi.to_numpy(), 1)[0]))
        measured_slopes.append(float(np.polyfit(x, measured_pi.to_numpy(), 1)[0]))
    simulated_mean_slope = _mean_or_none(simulated_slopes)
    measured_mean_slope = _mean_or_none(measured_slopes)
    slope_ratio = (
        None
        if simulated_mean_slope is None or measured_mean_slope is None or measured_mean_slope == 0.0
        else simulated_mean_slope / measured_mean_slope
    )

    simulated_recoveries: list[float] = []
    measured_recoveries: list[float] = []
    index_positions = {timestamp: position for position, timestamp in enumerate(index)}
    for event_day in index[reset_events.to_numpy()]:
        position = index_positions[event_day]
        if position == 0 or (index[position] - index[position - 1]).days != 1:
            continue
        current = working.iloc[position]
        previous = working.iloc[position - 1]
        simulated_recoveries.append(float(current[SIMULATED_COLUMN] - previous[SIMULATED_COLUMN]))
        measured_recoveries.append(float(current[MEASURED_COLUMN] - previous[MEASURED_COLUMN]))

    holdout_frame = working.iloc[0:0]
    if holdout_start is not None:
        holdout_day = pd.Timestamp(holdout_start).normalize().tz_localize(None)
        holdout_frame = working.loc[working.index >= holdout_day]

    return {
        "clean_days": _optional_metric_summary(clean_frame),
        "decline_slopes": {
            "days_used": sum(len(spell) for spell in dry_spells),
            "dry_spell_count": len(dry_spells),
            "minimum_dry_spell_days": 10,
            "simulated_mean_slope_per_day": simulated_mean_slope,
            "measured_mean_slope_per_day": measured_mean_slope,
            "simulated_to_measured_slope_ratio": slope_ratio,
        },
        "recovery": {
            "days_used": len(simulated_recoveries),
            "event_count": len(simulated_recoveries),
            "simulated_mean_step_change_kwh": _mean_or_none(simulated_recoveries),
            "measured_mean_step_change_kwh": _mean_or_none(measured_recoveries),
        },
        "holdout": _optional_metric_summary(holdout_frame),
    }


def _daily_series(series: pd.Series, name: str) -> pd.Series:
    if not isinstance(series.index, pd.DatetimeIndex):
        try:
            index = pd.to_datetime(series.index)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} index must contain parseable dates") from exc
    else:
        index = series.index
    values = pd.to_numeric(series, errors="coerce")
    if values.isna().any():
        raise ValueError(f"{name} contains missing or non-numeric values")
    daily = pd.Series(values.to_numpy(dtype=float), index=_date_index(index), name=name)
    if daily.index.has_duplicates:
        raise ValueError(f"{name} must contain at most one value per day")
    return daily


def _date_index(index: pd.Index) -> pd.DatetimeIndex:
    converted = pd.DatetimeIndex(pd.to_datetime(index))
    if converted.tz is not None:
        converted = converted.tz_localize(None)
    return converted.normalize()


def _energy_columns(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    missing = {SIMULATED_COLUMN, MEASURED_COLUMN}.difference(df.columns)
    if missing:
        raise ValueError(f"validation frame missing columns: {sorted(missing)}")
    _require_nonempty(df)
    simulated = pd.to_numeric(df[SIMULATED_COLUMN], errors="coerce")
    measured = pd.to_numeric(df[MEASURED_COLUMN], errors="coerce")
    if simulated.isna().any() or measured.isna().any():
        raise ValueError("validation energy columns contain missing or non-numeric values")
    return simulated, measured


def _errors(df: pd.DataFrame) -> pd.Series:
    simulated, measured = _energy_columns(df)
    return simulated - measured


def _require_nonempty(df: pd.DataFrame) -> None:
    if df.empty:
        raise ValueError("validation metrics require at least one row")


def _aligned_numeric(series: pd.Series, index: pd.DatetimeIndex, *, default: float) -> pd.Series:
    aligned = pd.Series(
        pd.to_numeric(series, errors="coerce").to_numpy(dtype=float),
        index=_date_index(series.index),
    )
    if aligned.index.has_duplicates:
        aligned = aligned.groupby(level=0).max()
    return aligned.reindex(index, fill_value=default).fillna(default)


def _dry_spells(index: pd.DatetimeIndex, reset_events: pd.Series) -> list[pd.DatetimeIndex]:
    spells: list[pd.DatetimeIndex] = []
    current: list[pd.Timestamp] = []
    for position, day in enumerate(index):
        is_contiguous = position == 0 or (day - index[position - 1]).days == 1
        if bool(reset_events.iloc[position]) or not is_contiguous:
            if len(current) >= 10:
                spells.append(pd.DatetimeIndex(current))
            current = []
        if not bool(reset_events.iloc[position]):
            current.append(day)
    if len(current) >= 10:
        spells.append(pd.DatetimeIndex(current))
    return spells


def _performance_indices(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    simulated = frame[SIMULATED_COLUMN].astype(float)
    measured = frame[MEASURED_COLUMN].astype(float)
    if CLEAN_REFERENCE_COLUMN in frame:
        clean = frame[CLEAN_REFERENCE_COLUMN].astype(float).replace(0.0, np.nan)
        simulated_pi = simulated / clean
        measured_pi = measured / clean
        valid = simulated_pi.notna() & measured_pi.notna()
        if int(valid.sum()) >= 2:
            return simulated_pi.loc[valid], measured_pi.loc[valid]
    return simulated / float(simulated.mean()), measured / float(measured.mean())


def _optional_metric_summary(df: pd.DataFrame) -> dict[str, object]:
    if df.empty:
        return {"days_used": 0, "metrics_available": False}
    return {"metrics_available": True, **metric_summary(df)}


def _mean_or_none(values: list[float]) -> float | None:
    return None if not values else float(np.mean(values))
