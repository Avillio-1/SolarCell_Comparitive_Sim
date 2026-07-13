from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from solarclean.config.models import SolarCleanConfig
from solarclean.domain.contamination.soiling import KimberStyleSoilingModel
from solarclean.domain.events.tape import generate_event_tape
from solarclean.domain.farm.representation import CohortFarm
from solarclean.domain.simulation.baseline import BaselineSimulationEngine, BaselineSimulationResult
from solarclean.domain.validation.field_validation import (
    CLEAN_REFERENCE_COLUMN,
    daily_align,
    metric_summary,
    stage_metrics,
)
from solarclean.infrastructure.persistence.outputs import OutputWriter
from solarclean.infrastructure.persistence.reports import write_json_report
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel

from .use_cases import _weather_provider, _weather_request

TIMESTAMP_COLUMN = "timestamp"
MEASURED_ENERGY_COLUMN = "measured_ac_energy_kwh"
CLEANING_EVENT_COLUMN = "cleaning_event"


@dataclass(frozen=True)
class FieldValidationResult:
    output_directory: Path
    report: dict[str, object]


class FieldValidationHarness:
    def __init__(
        self,
        config: SolarCleanConfig,
        measured_csv: Path,
        holdout_start: date,
    ) -> None:
        self.config = config
        self.measured_csv = measured_csv
        self.holdout_start = holdout_start

    def run(self) -> FieldValidationResult:
        measured, cleaning_flags = load_measured_production_csv(
            self.measured_csv,
            site_timezone=self.config.site.timezone,
        )
        period_config = _config_for_measured_period(self.config, measured.index)
        baseline = simulate_baseline(period_config)
        simulated = _baseline_series(baseline, "actual_energy_kwh")
        clean_reference = _baseline_series(baseline, "clean_energy_kwh")
        precipitation = _baseline_series(baseline, "precipitation_mm")
        aligned = daily_align(simulated, measured)
        aligned[CLEAN_REFERENCE_COLUMN] = clean_reference.reindex(aligned.index)
        if aligned[CLEAN_REFERENCE_COLUMN].isna().any():
            raise ValueError("clean-model energy is missing for one or more aligned days")
        stages = stage_metrics(
            aligned,
            precipitation,
            cleaning_flags,
            period_config.rainfall_cleaning.full_rain_cleaning_threshold_mm,
            holdout_start=self.holdout_start,
        )
        report: dict[str, object] = {
            "report_type": "field_validation",
            "site_name": period_config.site.name,
            "site_timezone": period_config.site.timezone,
            "measured_csv": str(self.measured_csv),
            "period": {
                "start": aligned.index.min().date().isoformat(),
                "end": aligned.index.max().date().isoformat(),
            },
            "holdout_start": self.holdout_start.isoformat(),
            "overall": metric_summary(aligned),
            "stages": stages,
            "predictive_accuracy_note": (
                "Metrics on the tuning period are not evidence of predictive accuracy. "
                "Only metrics for the untouched holdout period assess predictive performance."
            ),
        }
        writer = OutputWriter(period_config)
        output_directory = writer.create_run_directory("validate-field")
        write_json_report(output_directory / "field_validation_report.json", report)
        (output_directory / "field_validation_report.md").write_text(
            _markdown_report(report), encoding="utf-8"
        )
        return FieldValidationResult(output_directory=output_directory, report=report)


def load_measured_production_csv(
    path: Path,
    *,
    site_timezone: str,
) -> tuple[pd.Series, pd.Series]:
    """Load interval production and aggregate energy and cleaning flags to local days."""

    if not path.exists():
        raise FileNotFoundError(f"measured-production CSV does not exist: {path}")
    raw = pd.read_csv(path)
    required = {TIMESTAMP_COLUMN, MEASURED_ENERGY_COLUMN}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"measured-production CSV missing columns: {sorted(missing)}")
    timestamp_values = raw[TIMESTAMP_COLUMN].astype(str)
    for value in timestamp_values:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"invalid ISO 8601 timestamp in measured-production CSV: {value}"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("measured-production CSV timestamps must include timezone offsets")
    timestamps = pd.DatetimeIndex(pd.to_datetime(timestamp_values, utc=True)).tz_convert(
        site_timezone
    )
    energy = pd.to_numeric(raw[MEASURED_ENERGY_COLUMN], errors="coerce")
    if (
        energy.isna().any()
        or not np.isfinite(energy.to_numpy(dtype=float)).all()
        or (energy < 0.0).any()
    ):
        raise ValueError("measured_ac_energy_kwh must contain finite non-negative numbers")
    local_dates = timestamps.tz_localize(None).normalize()
    measured = pd.Series(energy.to_numpy(dtype=float), index=local_dates).groupby(level=0).sum()
    measured.name = MEASURED_ENERGY_COLUMN

    if CLEANING_EVENT_COLUMN in raw:
        cleaning_raw = pd.to_numeric(raw[CLEANING_EVENT_COLUMN], errors="coerce")
        if cleaning_raw.isna().any() or not cleaning_raw.isin([0, 1]).all():
            raise ValueError("cleaning_event must contain only 0 or 1")
        cleaning = (
            pd.Series(cleaning_raw.to_numpy(dtype=int), index=local_dates)
            .groupby(level=0)
            .max()
            .astype(int)
        )
    else:
        cleaning = pd.Series(0, index=measured.index, dtype=int)
    cleaning.name = CLEANING_EVENT_COLUMN
    return measured, cleaning


def simulate_baseline(config: SolarCleanConfig) -> BaselineSimulationResult:
    """Run the existing baseline engine in memory without writing its artifact package."""

    weather = _weather_provider(config).load(_weather_request(config))
    profile = PVWattsPowerModel().calculate_hourly(weather, config.pv_system)
    dates = [pd.Timestamp(str(day)).date() for day in profile.daily.index]
    event_tape = generate_event_tape(
        dates=dates,
        seed=config.soiling.random_seed,
        soiling=config.soiling,
        rainfall=config.rainfall_cleaning,
        farm=config.farm,
        birds=config.bird_droppings,
    )
    farm = (
        CohortFarm(config.farm, config.bird_droppings)
        if config.farm.representation == "cohort"
        else None
    )
    return BaselineSimulationEngine(
        KimberStyleSoilingModel(config.soiling, config.rainfall_cleaning),
        farm=farm,
        farm_config=config.farm,
    ).run(profile, weather, config.soiling.random_seed, event_tape=event_tape)


def _config_for_measured_period(config: SolarCleanConfig, index: pd.Index) -> SolarCleanConfig:
    dates = pd.DatetimeIndex(index)
    if dates.empty:
        raise ValueError("measured-production CSV contains no rows")
    timezone = ZoneInfo(config.site.timezone)
    start = datetime.combine(dates.min().date(), time.min, tzinfo=timezone)
    end = datetime.combine(dates.max().date(), time(hour=23), tzinfo=timezone)
    simulation = config.simulation.model_copy(update={"start": start, "end": end})
    return config.model_copy(update={"simulation": simulation})


def _baseline_series(baseline: BaselineSimulationResult, column: str) -> pd.Series:
    series = baseline.daily[column].astype(float).copy()
    series.index = pd.DatetimeIndex(pd.to_datetime(series.index))
    return series


def _markdown_report(report: dict[str, object]) -> str:
    overall = _mapping(report["overall"])
    stages = _mapping(report["stages"])
    clean = _mapping(stages["clean_days"])
    holdout = _mapping(stages["holdout"])
    rows = [
        _metric_row("Overall", overall),
        _metric_row("Clean days (event day through +2)", clean),
        _metric_row("Holdout", holdout),
    ]
    decline = _mapping(stages["decline_slopes"])
    recovery = _mapping(stages["recovery"])
    return "\n".join(
        [
            "# Field Validation Report",
            "",
            f"Site: {report['site_name']}  ",
            f"Period: {_mapping(report['period'])['start']} through "
            f"{_mapping(report['period'])['end']}  ",
            f"Holdout starts: {report['holdout_start']}",
            "",
            "| Stage | Days | MAE (kWh) | MAE (%) | RMSE (kWh) | RMSE (%) | "
            "MBE (kWh) | MBE (%) | R² |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            *rows,
            "",
            "## Decline slopes",
            "",
            f"Dry spells: {decline['dry_spell_count']}; days used: {decline['days_used']}; "
            f"simulated mean PI slope/day: {_display(decline['simulated_mean_slope_per_day'])}; "
            f"measured: {_display(decline['measured_mean_slope_per_day'])}; "
            f"ratio: {_display(decline['simulated_to_measured_slope_ratio'])}.",
            "",
            "## Recovery",
            "",
            f"Events used: {recovery['event_count']}; simulated mean step: "
            f"{_display(recovery['simulated_mean_step_change_kwh'])} kWh; measured mean step: "
            f"{_display(recovery['measured_mean_step_change_kwh'])} kWh.",
            "",
            "## Interpretation warning",
            "",
            str(report["predictive_accuracy_note"]),
            "",
        ]
    )


def _metric_row(label: str, metrics: dict[str, object]) -> str:
    if not bool(metrics.get("metrics_available", True)):
        return (
            f"| {label} | {metrics.get('days_used', 0)} | n/a | n/a | n/a | n/a | n/a | n/a | n/a |"
        )
    keys = (
        "days_used",
        "mae_kwh",
        "mae_percent",
        "rmse_kwh",
        "rmse_percent",
        "mbe_kwh",
        "mbe_percent",
        "r2",
    )
    values = " | ".join(_display(metrics[key]) for key in keys)
    return f"| {label} | {values} |"


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("report section must be a dictionary")
    return value


def _display(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)
