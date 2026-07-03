from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pandas as pd

from solarclean.config.models import SolarCleanConfig
from solarclean.domain.coating.strategy import CoatingStrategy
from solarclean.domain.contamination.soiling import KimberStyleSoilingModel
from solarclean.domain.environment.weather import (
    CANONICAL_WEATHER_COLUMNS,
    WeatherProvider,
    WeatherRequest,
)
from solarclean.domain.events.tape import generate_event_tape
from solarclean.domain.farm.representation import CohortFarm
from solarclean.domain.reactive_cv.metrics import summarize_detection_performance
from solarclean.domain.reactive_cv.strategy import ReactiveCVStrategy
from solarclean.domain.scenario.contracts import AnnualScenarioResult, ScenarioContext
from solarclean.domain.simulation.baseline import BaselineSimulationEngine, BaselineSimulationResult
from solarclean.domain.simulation.scenario_engine import ScenarioSimulationEngine
from solarclean.infrastructure.persistence.outputs import OutputWriter
from solarclean.infrastructure.persistence.plots import write_baseline_diagnostic_plot
from solarclean.infrastructure.persistence.reports import write_json_report
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


class RunCoatingSimulation:
    def __init__(self, config: SolarCleanConfig) -> None:
        self.config = config

    def run(self) -> UseCaseResult:
        request = _weather_request(self.config)
        weather = _weather_provider(self.config).load(request)
        profile = PVWattsPowerModel().calculate_hourly(weather, self.config.pv_system)
        dates = [pd.Timestamp(str(day)).date() for day in profile.daily.index]
        event_tape = generate_event_tape(
            dates=dates,
            seed=self.config.soiling.random_seed,
            soiling=self.config.soiling,
            rainfall=self.config.rainfall_cleaning,
            farm=self.config.farm,
            birds=self.config.bird_droppings,
        )
        context = ScenarioContext.from_inputs(
            weather=weather,
            clean_energy=profile,
            event_tape=event_tape,
            farm_config=self.config.farm,
            metadata={"event_tape_checksum": event_tape.checksum()},
        )
        strategy = CoatingStrategy(
            coating=self.config.coating,
            soiling=self.config.soiling,
            rainfall=self.config.rainfall_cleaning,
            birds=self.config.bird_droppings,
            farm=self.config.farm,
            pv_system=self.config.pv_system,
        )
        coating = ScenarioSimulationEngine(strategy).run(
            context,
            random_seed=self.config.soiling.random_seed,
        )
        baseline_farm = (
            CohortFarm(self.config.farm, self.config.bird_droppings)
            if self.config.farm.representation == "cohort"
            else None
        )
        baseline = BaselineSimulationEngine(
            KimberStyleSoilingModel(self.config.soiling, self.config.rainfall_cleaning),
            farm=baseline_farm,
            farm_config=self.config.farm,
        ).run(
            profile,
            weather,
            random_seed=self.config.soiling.random_seed,
            event_tape=event_tape,
        )
        writer = OutputWriter(self.config)
        output_dir = writer.create_run_directory("run-coating")
        writer.write_config(output_dir)
        writer.write_weather(output_dir, weather)
        writer.write_clean_energy(output_dir, profile)
        writer.write_scenario_result(output_dir, coating)
        metadata = _base_metadata(self.config, "run-coating")
        metadata["weather_metadata"] = weather.metadata
        metadata["pv_metadata"] = profile.metadata
        metadata["event_tape_checksum"] = event_tape.checksum()
        writer.write_metadata(output_dir, metadata)
        summary = _coating_summary(
            coating,
            baseline,
            config=self.config,
            event_tape_checksum=event_tape.checksum(),
        )
        writer.write_summary(output_dir, summary)
        writer.write_text_summary(output_dir, summary)
        write_json_report(output_dir / "coating_comparison_summary.json", summary)
        return UseCaseResult(output_directory=output_dir, summary=summary)


class RunReactiveSimulation:
    def __init__(self, config: SolarCleanConfig) -> None:
        self.config = config

    def run(self) -> UseCaseResult:
        request = _weather_request(self.config)
        weather = _weather_provider(self.config).load(request)
        profile = PVWattsPowerModel().calculate_hourly(weather, self.config.pv_system)
        dates = [pd.Timestamp(str(day)).date() for day in profile.daily.index]
        event_tape = generate_event_tape(
            dates=dates,
            seed=self.config.soiling.random_seed,
            soiling=self.config.soiling,
            rainfall=self.config.rainfall_cleaning,
            farm=self.config.farm,
            birds=self.config.bird_droppings,
        )
        context = ScenarioContext.from_inputs(
            weather=weather,
            clean_energy=profile,
            event_tape=event_tape,
            farm_config=self.config.farm,
            metadata={"event_tape_checksum": event_tape.checksum()},
        )
        strategy = ReactiveCVStrategy(
            reactive=self.config.reactive_cv,
            soiling=self.config.soiling,
            rainfall=self.config.rainfall_cleaning,
            birds=self.config.bird_droppings,
            farm=self.config.farm,
        )
        reactive = ScenarioSimulationEngine(strategy).run(
            context,
            random_seed=self.config.soiling.random_seed,
        )
        perfect_info: AnnualScenarioResult | None = None
        if self.config.reactive_cv.perfect_information_benchmark:
            benchmark_strategy = ReactiveCVStrategy(
                reactive=self.config.reactive_cv,
                soiling=self.config.soiling,
                rainfall=self.config.rainfall_cleaning,
                birds=self.config.bird_droppings,
                farm=self.config.farm,
                perfect_information=True,
            )
            perfect_info = ScenarioSimulationEngine(benchmark_strategy).run(
                context,
                random_seed=self.config.soiling.random_seed,
            )
        baseline_farm = (
            CohortFarm(self.config.farm, self.config.bird_droppings)
            if self.config.farm.representation == "cohort"
            else None
        )
        baseline = BaselineSimulationEngine(
            KimberStyleSoilingModel(self.config.soiling, self.config.rainfall_cleaning),
            farm=baseline_farm,
            farm_config=self.config.farm,
        ).run(
            profile,
            weather,
            random_seed=self.config.soiling.random_seed,
            event_tape=event_tape,
        )
        writer = OutputWriter(self.config)
        output_dir = writer.create_run_directory("run-reactive")
        writer.write_config(output_dir)
        writer.write_weather(output_dir, weather)
        writer.write_clean_energy(output_dir, profile)
        writer.write_scenario_result(output_dir, reactive)
        metadata = _base_metadata(self.config, "run-reactive")
        metadata["weather_metadata"] = weather.metadata
        metadata["pv_metadata"] = profile.metadata
        metadata["event_tape_checksum"] = event_tape.checksum()
        writer.write_metadata(output_dir, metadata)
        summary = _reactive_summary(
            reactive,
            baseline,
            perfect_info=perfect_info,
            event_tape_checksum=event_tape.checksum(),
        )
        writer.write_summary(output_dir, summary)
        writer.write_text_summary(output_dir, summary)
        write_json_report(output_dir / "reactive_comparison_summary.json", summary)
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


def _coating_summary(
    coating: AnnualScenarioResult,
    baseline: BaselineSimulationResult,
    *,
    config: SolarCleanConfig,
    event_tape_checksum: str,
) -> dict[str, object]:
    condensed = _sum_daily_extension(coating, "condensed_water_liters")
    potential = _sum_daily_extension(coating, "potentially_collectable_water_liters")
    actual_water = _sum_daily_extension(coating, "actually_collected_water_liters")
    optical = _sum_daily_extension(coating, "optical_effect_kwh")
    temperature = _sum_daily_extension(coating, "temperature_effect_kwh")
    cleanliness = _sum_daily_extension(coating, "cleanliness_effect_kwh")
    coated_area_m2 = _first_daily_extension_float(coating, "coated_area_m2")
    cleanliness_improvement = _sum_cleanliness_improvement_vs_baseline(coating, baseline)
    period = _period_metadata(coating)
    payload = {
        "command": "run-coating",
        "scenario_name": coating.scenario_name,
        "event_tape_checksum": event_tape_checksum,
        **period,
        "coating_preset": config.coating.preset,
        "calibration_fixture": config.coating.preset
        in {"paper_calibration", "paper_endpoint_calibration"},
        "annual_field_basis": "simulated_period_total",
        "clean_energy_reference": (
            "clean uncoated PVWatts AC energy at the modeled operating temperature"
        ),
        "above_clean_reference_allowed": True,
        "optical_multiplier_basis": "relative coated-versus-uncoated PV performance",
        "source_optical_transmittance_absolute_fraction": (
            config.coating.physics.source_optical_transmittance_absolute_fraction
        ),
        "annual_clean_energy_kwh": coating.annual_clean_energy_kwh,
        "annual_baseline_actual_energy_kwh": baseline.annual_actual_energy_kwh,
        "annual_coating_actual_energy_kwh": coating.annual_actual_energy_kwh,
        "coating_minus_baseline_energy_kwh": (
            coating.annual_actual_energy_kwh - baseline.annual_actual_energy_kwh
        ),
        "annual_energy_loss_kwh": coating.annual_energy_loss_kwh,
        "annual_energy_loss_percent": coating.annual_energy_loss_percent,
        "annual_optical_effect_kwh": optical,
        "annual_temperature_effect_kwh": temperature,
        "annual_cleanliness_effect_kwh": cleanliness,
        "annual_cleanliness_improvement_vs_baseline_kwh": cleanliness_improvement,
        "annual_condensed_water_liters": condensed,
        "annual_potentially_collectable_water_liters": potential,
        "annual_actually_collected_water_liters": actual_water,
        "coated_area_m2": coated_area_m2,
        "water_scope": "whole simulated coated farm over the simulated period",
        "annual_condensed_water_liters_per_m2": _safe_divide(condensed, coated_area_m2),
        "annual_potentially_collectable_water_liters_per_m2": _safe_divide(
            potential, coated_area_m2
        ),
        "annual_actually_collected_water_liters_per_m2": _safe_divide(actual_water, coated_area_m2),
        "cost_basis_available": True,
        "water_revenue_included": False,
        "annualization_included": False,
        "paper_source_status": "prompt_quoted_values_only",
    }
    payload.update(
        {
            "period_clean_energy_kwh": payload["annual_clean_energy_kwh"],
            "period_baseline_actual_energy_kwh": payload["annual_baseline_actual_energy_kwh"],
            "period_coating_actual_energy_kwh": payload["annual_coating_actual_energy_kwh"],
            "period_energy_loss_kwh": payload["annual_energy_loss_kwh"],
            "period_energy_loss_percent": payload["annual_energy_loss_percent"],
            "period_optical_effect_kwh": optical,
            "period_temperature_effect_kwh": temperature,
            "period_cleanliness_effect_kwh": cleanliness,
            "period_cleanliness_improvement_vs_baseline_kwh": cleanliness_improvement,
            "period_condensed_water_liters": condensed,
            "period_potentially_collectable_water_liters": potential,
            "period_actually_collected_water_liters": actual_water,
            "period_condensed_water_liters_per_m2": payload["annual_condensed_water_liters_per_m2"],
            "period_potentially_collectable_water_liters_per_m2": payload[
                "annual_potentially_collectable_water_liters_per_m2"
            ],
            "period_actually_collected_water_liters_per_m2": payload[
                "annual_actually_collected_water_liters_per_m2"
            ],
        }
    )
    return payload


def _reactive_summary(
    reactive: AnnualScenarioResult,
    baseline: BaselineSimulationResult,
    *,
    perfect_info: AnnualScenarioResult | None,
    event_tape_checksum: str,
) -> dict[str, object]:
    period = _period_metadata(reactive)
    detection = summarize_detection_performance(reactive)
    weather_cancelled_days = sum(
        1
        for daily in reactive.daily_results
        if bool(daily.extensions.get("weather_cancelled_flight", False))
    )
    final_queue_length = (
        int(cast(int, reactive.daily_results[-1].extensions.get("queue_length", 0)))
        if reactive.daily_results
        else 0
    )
    payload: dict[str, object] = {
        "command": "run-reactive",
        "scenario_name": reactive.scenario_name,
        "event_tape_checksum": event_tape_checksum,
        **period,
        "annual_clean_energy_kwh": reactive.annual_clean_energy_kwh,
        "annual_baseline_actual_energy_kwh": baseline.annual_actual_energy_kwh,
        "annual_reactive_actual_energy_kwh": reactive.annual_actual_energy_kwh,
        "reactive_minus_baseline_energy_kwh": (
            reactive.annual_actual_energy_kwh - baseline.annual_actual_energy_kwh
        ),
        "annual_energy_loss_kwh": reactive.annual_energy_loss_kwh,
        "annual_energy_loss_percent": reactive.annual_energy_loss_percent,
        "total_inspections": _sum_operational(reactive, "inspections_count"),
        "total_cleaning_actions": _sum_operational(reactive, "cleaning_actions_count"),
        "total_crew_hours": _sum_operational(reactive, "crew_hours"),
        "total_drone_flight_hours": _sum_operational(reactive, "drone_flight_hours"),
        "total_water_liters": _sum_operational(reactive, "water_liters"),
        "total_operational_energy_used_kwh": _sum_operational(reactive, "energy_used_kwh"),
        "weather_cancelled_flight_days": weather_cancelled_days,
        "final_cleaning_queue_length": final_queue_length,
        "detection_performance": detection.to_record(),
        "cost_basis_available": False,
        "economics_owner": "T4",
    }
    if perfect_info is not None:
        payload.update(
            {
                "perfect_information_scenario_name": perfect_info.scenario_name,
                "annual_perfect_information_actual_energy_kwh": (
                    perfect_info.annual_actual_energy_kwh
                ),
                "cv_error_energy_cost_kwh": (
                    perfect_info.annual_actual_energy_kwh - reactive.annual_actual_energy_kwh
                ),
                "perfect_information_total_inspections": _sum_operational(
                    perfect_info, "inspections_count"
                ),
                "perfect_information_total_cleaning_actions": _sum_operational(
                    perfect_info, "cleaning_actions_count"
                ),
            }
        )
    return payload


def _sum_operational(result: AnnualScenarioResult, attribute: str) -> float:
    return float(sum(getattr(daily.operational, attribute) for daily in result.daily_results))


def _sum_daily_extension(result: AnnualScenarioResult, key: str) -> float:
    total = 0.0
    for daily in result.daily_results:
        value = daily.extensions[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"daily extension {key} must be numeric")
        total += float(value)
    return total


def _first_daily_extension_float(result: AnnualScenarioResult, key: str) -> float:
    if not result.daily_results:
        return 0.0
    value = result.daily_results[0].extensions[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"daily extension {key} must be numeric")
    return float(value)


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator > 0.0 else 0.0


def _sum_cleanliness_improvement_vs_baseline(
    coating: AnnualScenarioResult,
    baseline: BaselineSimulationResult,
) -> float:
    total = 0.0
    for daily in coating.daily_results:
        value = daily.extensions["cleanliness_ratio"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("daily extension cleanliness_ratio must be numeric")
        baseline_actual = float(
            cast(float, baseline.daily.at[daily.date.isoformat(), "actual_energy_kwh"])
        )
        total += daily.clean_energy_kwh * float(value) - baseline_actual
    return total


def _period_metadata(result: AnnualScenarioResult) -> dict[str, object]:
    if not result.daily_results:
        return {
            "period_start_date": None,
            "period_end_date": None,
            "period_day_count": 0,
            "period_is_full_year": False,
        }
    dates = [daily.date for daily in result.daily_results]
    start = min(dates)
    end = max(dates)
    is_full_year = (
        start.month == 1
        and start.day == 1
        and end.month == 12
        and end.day == 31
        and start.year == end.year
        and len(set(dates)) in {365, 366}
    )
    return {
        "period_start_date": start.isoformat(),
        "period_end_date": end.isoformat(),
        "period_day_count": len(set(dates)),
        "period_is_full_year": is_full_year,
    }


def finite_numeric_frame(frame: pd.DataFrame) -> bool:
    return bool(frame.select_dtypes(include=["number"]).notna().all().all())
