from __future__ import annotations

import json
import subprocess
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

from solarclean import __version__
from solarclean.config.models import SolarCleanConfig
from solarclean.domain.environment.weather import WeatherDataset
from solarclean.domain.pv.model import CleanEnergyProfile
from solarclean.domain.scenario.contracts import (
    AnnualScenarioResult,
    DomainEvent,
    ScenarioOutputBundle,
    ordered_domain_events,
)
from solarclean.domain.simulation.baseline import BaselineSimulationResult

_SCENARIO_EVENT_COLUMNS = [
    "date",
    "scenario_name",
    "event_sequence",
    "event_phase",
    "effective_for_energy_date",
    "event_type",
    "magnitude",
    "description",
    "cohort_id",
    "metadata",
]

_BASELINE_EVENT_COLUMNS = [
    "date",
    "event_sequence",
    "event_phase",
    "effective_for_energy_date",
    "event_type",
    "magnitude",
    "description",
    "cohort_id",
    "metadata",
]


@lru_cache(maxsize=1)
def code_version_metadata() -> dict[str, object]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty_result = subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        commit = ""
        dirty: bool | None = None
    else:
        dirty = bool(dirty_result.stdout.strip())
    return {
        "solarclean_version": __version__,
        "git_commit": commit or None,
        "git_worktree_dirty": dirty,
    }


class OutputWriter:
    def __init__(self, config: SolarCleanConfig) -> None:
        self.config = config

    def create_run_directory(self, command: str) -> Path:
        output_dir = self.config.output.base_directory / self.build_run_id(command)
        output_dir.mkdir(parents=True, exist_ok=False)
        return output_dir

    def build_run_id(self, command: str) -> str:
        """Generate a run id without touching the filesystem.

        Used by T7 Monte Carlo / sensitivity trials that skip artifact writing
        (`write_artifacts=False`) but still need a unique, traceable run id without
        creating an empty output directory for every one of hundreds of trials.
        """
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        unique_suffix = uuid.uuid4().hex[:8]
        prefix = self.config.simulation.run_id_prefix
        return f"{prefix}-{command}-{timestamp}-{unique_suffix}"

    def write_config(self, output_dir: Path) -> None:
        path = output_dir / "config_resolved.yaml"
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(self.config.model_dump(mode="json"), handle, sort_keys=False)

    def write_metadata(self, output_dir: Path, metadata: dict[str, object]) -> None:
        (output_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    def write_weather(self, output_dir: Path, weather: WeatherDataset) -> None:
        weather.hourly.to_csv(
            output_dir / "weather_hourly.csv",
            index_label="timestamp",
            float_format=self.config.output.csv_float_format,
        )

    def write_clean_energy(self, output_dir: Path, profile: CleanEnergyProfile) -> None:
        profile.hourly.to_csv(
            output_dir / "clean_energy_hourly.csv",
            index_label="timestamp",
            float_format=self.config.output.csv_float_format,
        )
        profile.daily.to_csv(
            output_dir / "daily_clean_energy.csv",
            index_label="date",
            float_format=self.config.output.csv_float_format,
        )
        if not (output_dir / "daily_results.csv").exists():
            profile.daily.to_csv(
                output_dir / "daily_results.csv",
                index_label="date",
                float_format=self.config.output.csv_float_format,
            )

    def write_daily_weather_diagnostics(
        self,
        output_dir: Path,
        weather: WeatherDataset,
        profile: CleanEnergyProfile,
    ) -> None:
        """Persist daily weather/PV drivers used to explain energy variation."""

        records: list[dict[str, object]] = []
        weather_index = pd.DatetimeIndex(weather.hourly.index)
        for raw_day, daily_weather in weather.hourly.groupby(weather_index.date):
            day = pd.Timestamp(str(raw_day)).date()
            daily_pv = profile.hourly.reindex(daily_weather.index)
            daylight = daily_weather["ghi_w_m2"] > 20.0
            if not bool(daylight.any()):
                daylight = pd.Series(True, index=daily_weather.index)
            if "cell_temperature_c" in daily_pv:
                daylight_cell_temperature = float(
                    daily_pv.loc[daylight, "cell_temperature_c"].mean()
                )
            else:
                daylight_cell_temperature = float("nan")
            records.append(
                {
                    "date": day.isoformat(),
                    "daily_ghi_irradiation_kwh_m2": float(daily_weather["ghi_w_m2"].sum() / 1000.0),
                    "daylight_mean_ambient_temperature_c": float(
                        daily_weather.loc[daylight, "temp_air_c"].mean()
                    ),
                    "daylight_mean_cell_temperature_c": daylight_cell_temperature,
                    "rainfall_mm": float(daily_weather["precipitation_mm"].sum()),
                }
            )
        pd.DataFrame.from_records(records).to_csv(
            output_dir / "daily_weather_diagnostics.csv",
            index=False,
            float_format=self.config.output.csv_float_format,
        )

    def write_baseline(
        self,
        output_dir: Path,
        baseline: BaselineSimulationResult,
        config: SolarCleanConfig,
    ) -> None:
        baseline.daily.to_csv(
            output_dir / "daily_results.csv",
            index_label="date",
            float_format=config.output.csv_float_format,
        )
        events = [
            DomainEvent.from_simulation_event(event, scenario_name="baseline")
            for event in baseline.events
        ]
        event_path = output_dir / "events.csv"
        _write_event_csv(
            event_path,
            events,
            columns=_BASELINE_EVENT_COLUMNS,
            include_scenario_name=False,
        )
        include_cohort_details = (
            config.farm.store_cohort_daily_details and config.output.include_cohort_daily_details
        )
        if include_cohort_details and baseline.cohort_daily is not None:
            baseline.cohort_daily.to_csv(
                output_dir / "cohort_daily_results.csv",
                index=False,
                float_format=config.output.csv_float_format,
            )
        elif include_cohort_details:
            (output_dir / "cohort_daily_results.csv").write_text(
                "date,cohort_id,panel_count,dust_soiling_ratio,bird_drop_coverage_fraction,"
                "bird_drop_loss_fraction,actual_energy_kwh\n",
                encoding="utf-8",
            )

    def write_scenario_result(
        self,
        output_dir: Path,
        result: AnnualScenarioResult | ScenarioOutputBundle,
    ) -> None:
        if isinstance(result, AnnualScenarioResult):
            summary = result.summary()
            daily_frame = result.to_daily_frame()
            events = result.events
        else:
            summary = _plain_mapping(result.summary)
            daily_frame = result.daily_frame.copy(deep=True)
            events = result.events
        daily_frame.to_csv(
            output_dir / "scenario_daily_results.csv",
            index=False,
            float_format=self.config.output.csv_float_format,
        )
        _write_event_csv(
            output_dir / "scenario_events.csv",
            events,
            columns=_SCENARIO_EVENT_COLUMNS,
            include_scenario_name=True,
        )
        (output_dir / "scenario_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    def write_summary(self, output_dir: Path, summary: dict[str, object]) -> None:
        (output_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    def write_text_summary(self, output_dir: Path, summary: dict[str, object]) -> None:
        lines = [f"{key}: {value}" for key, value in summary.items()]
        (output_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_event_csv(
    path: Path,
    events: tuple[DomainEvent, ...] | list[DomainEvent],
    *,
    columns: list[str],
    include_scenario_name: bool,
) -> None:
    records = [
        _event_csv_record(event, include_scenario_name=include_scenario_name)
        for event in ordered_domain_events(tuple(events))
    ]
    pd.DataFrame.from_records(records, columns=columns).to_csv(path, index=False)


def _plain_mapping(mapping: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _plain_value(value) for key, value in mapping.items()}


def _plain_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _plain_mapping(value)
    if isinstance(value, tuple | list):
        return [_plain_value(item) for item in value]
    return value


def _event_csv_record(event: DomainEvent, *, include_scenario_name: bool) -> dict[str, object]:
    record = event.to_record()
    record["cohort_id"] = "" if event.cohort_id is None else str(event.cohort_id)
    if not include_scenario_name:
        record.pop("scenario_name", None)
    return record
