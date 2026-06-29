from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from solarclean.config.models import SolarCleanConfig
from solarclean.domain.environment.weather import WeatherDataset
from solarclean.domain.pv.model import CleanEnergyProfile
from solarclean.domain.simulation.baseline import BaselineSimulationResult


class OutputWriter:
    def __init__(self, config: SolarCleanConfig) -> None:
        self.config = config

    def create_run_directory(self, command: str) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id = (
            f"{self.config.simulation.run_id_prefix}-{command}-{timestamp}-{uuid.uuid4().hex[:8]}"
        )
        output_dir = self.config.output.base_directory / run_id
        output_dir.mkdir(parents=True, exist_ok=False)
        return output_dir

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
        events = [event.to_record() for event in baseline.events]
        event_path = output_dir / "events.csv"
        if events:
            pd.DataFrame.from_records(events).to_csv(event_path, index=False)
        else:
            event_path.write_text(
                "date,event_type,magnitude,description,cohort_id\n", encoding="utf-8"
            )
        if config.farm.store_cohort_daily_details and baseline.cohort_daily is not None:
            baseline.cohort_daily.to_csv(
                output_dir / "cohort_daily_results.csv",
                index=False,
                float_format=config.output.csv_float_format,
            )
        elif config.farm.store_cohort_daily_details:
            (output_dir / "cohort_daily_results.csv").write_text(
                "date,cohort_id,panel_count,dust_soiling_ratio,bird_drop_coverage_fraction,"
                "bird_drop_loss_fraction,actual_energy_kwh\n",
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
