from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from solarclean.config.models import SolarCleanConfig
from solarclean.domain.contamination.soiling import KimberStyleSoilingModel
from solarclean.domain.environment.weather import (
    CANONICAL_WEATHER_COLUMNS,
    WeatherProvider,
    WeatherRequest,
)
from solarclean.domain.farm.representation import CohortFarm
from solarclean.domain.simulation.baseline import BaselineSimulationEngine, BaselineSimulationResult
from solarclean.infrastructure.persistence.outputs import OutputWriter
from solarclean.infrastructure.persistence.plots import write_baseline_diagnostic_plot
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.csv_provider import CsvWeatherProvider
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider
from solarclean.infrastructure.weather.nasa_power import NasaPowerWeatherProvider


@dataclass(frozen=True)
class UseCaseResult:
    output_directory: Path
    summary: dict[str, object]


class FetchWeather:
    def __init__(self, config: SolarCleanConfig) -> None:
        self.config = config

    def run(self) -> UseCaseResult:
        request = _weather_request(self.config)
        weather = _weather_provider(self.config).load(request)
        writer = OutputWriter(self.config)
        output_dir = writer.create_run_directory("fetch-weather")
        writer.write_config(output_dir)
        writer.write_weather(output_dir, weather)
        metadata = _base_metadata(self.config, "fetch-weather")
        metadata["weather_metadata"] = weather.metadata
        writer.write_metadata(output_dir, metadata)
        summary = {
            "command": "fetch-weather",
            "weather_rows": len(weather.hourly),
            "provider": weather.metadata.get("provider"),
        }
        writer.write_summary(output_dir, summary)
        return UseCaseResult(output_directory=output_dir, summary=summary)


class RunCleanPVSimulation:
    def __init__(self, config: SolarCleanConfig) -> None:
        self.config = config

    def run(self) -> UseCaseResult:
        request = _weather_request(self.config)
        weather = _weather_provider(self.config).load(request)
        profile = PVWattsPowerModel().calculate_hourly(weather, self.config.pv_system)
        writer = OutputWriter(self.config)
        output_dir = writer.create_run_directory("run-clean")
        writer.write_config(output_dir)
        writer.write_weather(output_dir, weather)
        writer.write_clean_energy(output_dir, profile)
        metadata = _base_metadata(self.config, "run-clean")
        metadata["weather_metadata"] = weather.metadata
        metadata["pv_metadata"] = profile.metadata
        writer.write_metadata(output_dir, metadata)
        summary = {
            "command": "run-clean",
            "annual_clean_energy_kwh": profile.annual_clean_energy_kwh,
            "weather_provider": weather.metadata.get("provider"),
        }
        writer.write_summary(output_dir, summary)
        writer.write_text_summary(output_dir, summary)
        return UseCaseResult(output_directory=output_dir, summary=summary)


class RunBaselineSimulation:
    def __init__(self, config: SolarCleanConfig) -> None:
        self.config = config

    def run(self) -> UseCaseResult:
        request = _weather_request(self.config)
        weather = _weather_provider(self.config).load(request)
        profile = PVWattsPowerModel().calculate_hourly(weather, self.config.pv_system)
        farm = (
            CohortFarm(self.config.farm, self.config.bird_droppings)
            if self.config.farm.representation == "cohort"
            else None
        )
        engine = BaselineSimulationEngine(
            KimberStyleSoilingModel(self.config.soiling, self.config.rainfall_cleaning),
            farm=farm,
            farm_config=self.config.farm,
        )
        baseline = engine.run(profile, weather, self.config.soiling.random_seed)
        writer = OutputWriter(self.config)
        output_dir = writer.create_run_directory("run-baseline")
        writer.write_config(output_dir)
        writer.write_weather(output_dir, weather)
        writer.write_clean_energy(output_dir, profile)
        writer.write_baseline(output_dir, baseline, self.config)
        write_baseline_diagnostic_plot(output_dir / "diagnostic_plot.png", baseline)
        metadata = _base_metadata(self.config, "run-baseline")
        metadata["weather_metadata"] = weather.metadata
        metadata["pv_metadata"] = profile.metadata
        writer.write_metadata(output_dir, metadata)
        summary = _baseline_summary(baseline, self.config)
        writer.write_summary(output_dir, summary)
        writer.write_text_summary(output_dir, summary)
        return UseCaseResult(output_directory=output_dir, summary=summary)


def _weather_request(config: SolarCleanConfig) -> WeatherRequest:
    return WeatherRequest(
        latitude=config.site.latitude,
        longitude=config.site.longitude,
        elevation_m=config.site.elevation_m,
        start=config.simulation.start,
        end=config.simulation.end,
        target_timezone=config.simulation.target_timezone,
        variables=frozenset(CANONICAL_WEATHER_COLUMNS),
    )


def _weather_provider(config: SolarCleanConfig) -> WeatherProvider:
    if config.weather.provider == "fixture":
        return FixtureWeatherProvider()
    if config.weather.provider == "csv":
        if config.weather.local_csv_path is None:
            raise ValueError("weather.local_csv_path is required for csv provider")
        return CsvWeatherProvider(
            csv_path=config.weather.local_csv_path,
            timestamp_column=config.weather.timestamp_column,
            column_mapping=config.weather.column_mapping,
            unit_mapping=config.weather.unit_mapping,
        )
    return NasaPowerWeatherProvider(
        cache_directory=config.weather.cache_directory,
        cache_enabled=config.weather.cache_enabled,
        timeout_seconds=config.weather.timeout_seconds,
    )


def _base_metadata(config: SolarCleanConfig, command: str) -> dict[str, object]:
    return {
        "project": "SolarClean-DT",
        "command": command,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "site": config.site.model_dump(mode="json"),
        "simulation": config.simulation.model_dump(mode="json"),
    }


def _baseline_summary(
    baseline: BaselineSimulationResult,
    config: SolarCleanConfig,
) -> dict[str, object]:
    return {
        "command": "run-baseline",
        "farm_representation": config.farm.representation,
        "annual_clean_energy_kwh": baseline.annual_clean_energy_kwh,
        "annual_actual_energy_kwh": baseline.annual_actual_energy_kwh,
        "annual_soiling_loss_kwh": baseline.annual_soiling_loss_kwh,
        "annual_soiling_loss_percent": baseline.annual_soiling_loss_percent,
        "event_count": len(baseline.events),
        "cohort_daily_rows": 0 if baseline.cohort_daily is None else len(baseline.cohort_daily),
    }


def finite_numeric_frame(frame: pd.DataFrame) -> bool:
    return bool(frame.select_dtypes(include=["number"]).notna().all().all())
