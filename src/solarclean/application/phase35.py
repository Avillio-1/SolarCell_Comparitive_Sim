from __future__ import annotations

import hashlib
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from solarclean.application.use_cases import _weather_provider, _weather_request
from solarclean.config.models import FarmConfig, SolarCleanConfig
from solarclean.domain.contamination.soiling import KimberStyleSoilingModel
from solarclean.domain.environment.weather import CANONICAL_WEATHER_COLUMNS, WeatherDataset
from solarclean.domain.events.tape import generate_event_tape
from solarclean.domain.farm.representation import CohortFarm, RepresentativePanelFarm
from solarclean.domain.pv.model import CleanEnergyProfile
from solarclean.domain.simulation.baseline import BaselineSimulationEngine, BaselineSimulationResult
from solarclean.domain.validation.reports import (
    EnergyValidationReport,
    FarmEquivalenceReport,
    PerformanceReport,
    WeatherValidationReport,
)
from solarclean.infrastructure.persistence.outputs import OutputWriter
from solarclean.infrastructure.persistence.reports import write_json_report
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel


@dataclass(frozen=True)
class Phase35Result:
    output_directory: Path
    summary: dict[str, object]


class Phase35Validator:
    def __init__(self, config: SolarCleanConfig) -> None:
        self.config = config

    def run(self) -> Phase35Result:
        writer = OutputWriter(self.config)
        output_dir = writer.create_run_directory("phase-3-5")
        start_time = time.perf_counter()
        tracemalloc.start()
        try:
            request = _weather_request(self.config)
            weather = _weather_provider(self.config).load(request)
            clean = PVWattsPowerModel().calculate_hourly(weather, self.config.pv_system)
            dates = [
                datetime.fromisoformat(str(day)).date() for day in clean.daily.index.astype(str)
            ]
            event_tape = generate_event_tape(
                dates=dates,
                seed=self.config.soiling.random_seed,
                soiling=self.config.soiling,
                rainfall=self.config.rainfall_cleaning,
                farm=self.config.farm,
                birds=self.config.bird_droppings,
            )
            farm = (
                CohortFarm(self.config.farm, self.config.bird_droppings)
                if self.config.farm.representation == "cohort"
                else None
            )
            baseline = BaselineSimulationEngine(
                KimberStyleSoilingModel(self.config.soiling, self.config.rainfall_cleaning),
                farm=farm,
                farm_config=self.config.farm,
            ).run(clean, weather, self.config.soiling.random_seed, event_tape=event_tape)
            weather_report = validate_weather_dataset(
                weather,
                expected_start=self.config.simulation.start,
                expected_end=self.config.simulation.end,
            )
            energy_report = build_energy_report(clean, baseline, self.config)
            farm_report = validate_farm_equivalence(clean, self.config.farm)
            writer.write_config(output_dir)
            writer.write_weather(output_dir, weather)
            writer.write_clean_energy(output_dir, clean)
            writer.write_baseline(output_dir, baseline, self.config)
            write_json_report(output_dir / "phase35_weather_report.json", weather_report.to_dict())
            write_json_report(output_dir / "phase35_energy_report.json", energy_report.to_dict())
            write_json_report(
                output_dir / "phase35_farm_equivalence_report.json", farm_report.to_dict()
            )
            write_json_report(
                output_dir / "phase35_event_tape.json",
                {
                    "checksum_sha256": event_tape.checksum(),
                    "tape": {
                        "seed": event_tape.seed,
                        "metadata": dict(event_tape.metadata),
                        "events": event_tape.to_records(),
                    },
                },
            )
            current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        runtime_seconds = time.perf_counter() - start_time
        performance = PerformanceReport(
            runtime_seconds=runtime_seconds,
            peak_memory_mb=peak / (1024 * 1024),
            output_size_mb=_directory_size_mb(output_dir),
        )
        write_json_report(output_dir / "phase35_performance_report.json", performance.to_dict())
        summary = {
            "command": "validate-phase-3-5",
            "annual_clean_energy_kwh": energy_report.annual_clean_energy_kwh,
            "annual_actual_energy_kwh": energy_report.annual_actual_energy_kwh,
            "specific_yield_kwh_per_kwp": energy_report.specific_yield_kwh_per_kwp,
            "capacity_factor_percent": energy_report.capacity_factor_percent,
            "soiling_loss_percent": energy_report.annual_soiling_loss_percent,
            "event_tape_checksum": event_tape.checksum(),
            "farm_equivalence_passed": farm_report.passed,
            "runtime_seconds": performance.runtime_seconds,
            "peak_memory_mb": performance.peak_memory_mb,
            "output_size_mb": performance.output_size_mb,
        }
        write_json_report(output_dir / "phase35_summary.json", summary)
        writer.write_summary(output_dir, summary)
        writer.write_text_summary(output_dir, summary)
        return Phase35Result(output_directory=output_dir, summary=summary)


def validate_weather_dataset(
    weather: WeatherDataset,
    *,
    expected_start: datetime,
    expected_end: datetime,
) -> WeatherValidationReport:
    index = pd.DatetimeIndex(weather.hourly.index)
    expected = pd.date_range(
        pd.Timestamp(expected_start).tz_convert(index.tz),
        pd.Timestamp(expected_end).tz_convert(index.tz),
        freq="h",
    )
    missing = expected.difference(index)
    duplicate_count = int(index.duplicated().sum())
    ranges = {
        column: {
            "min": float(weather.hourly[column].min()),
            "max": float(weather.hourly[column].max()),
            "mean": float(weather.hourly[column].mean()),
        }
        for column in CANONICAL_WEATHER_COLUMNS
    }
    suspicious = _count_suspicious_weather_values(weather.hourly)
    units = weather.metadata.get("normalized_units", {})
    canonical_units = {
        column: str(units.get(column, "")) if isinstance(units, dict) else ""
        for column in CANONICAL_WEATHER_COLUMNS
    }
    return WeatherValidationReport(
        row_count=len(weather.hourly),
        expected_row_count=len(expected),
        start_timestamp=index.min().isoformat(),
        end_timestamp=index.max().isoformat(),
        timezone=str(index.tz),
        gap_count=len(missing),
        duplicate_count=duplicate_count,
        canonical_units=canonical_units,
        ranges=ranges,
        suspicious_value_count=suspicious,
        metadata_keys=sorted(weather.metadata.keys()),
        checksum_sha256=_frame_checksum(weather.hourly),
    )


def build_energy_report(
    clean: CleanEnergyProfile,
    baseline: BaselineSimulationResult,
    config: SolarCleanConfig,
) -> EnergyValidationReport:
    daily = baseline.daily.copy()
    daily.index = pd.to_datetime(daily.index)
    monthly_clean = _monthly_totals(daily, "clean_energy_kwh")
    monthly_actual = _monthly_totals(daily, "actual_energy_kwh")
    dc_capacity_kw = config.pv_system.total_dc_capacity_w / 1000.0
    hours = len(clean.hourly)
    dc_energy_kwh = float(clean.hourly["clean_dc_power_w"].sum() / 1000.0)
    clipping = float(
        (clean.hourly["clean_dc_power_w"] - clean.hourly["clean_ac_power_w"]).clip(lower=0).sum()
        / 1000.0
    )
    contamination_events = sum(
        1
        for event in baseline.events
        if event.event_type in {"dust_accumulation", "heavy_dust_event", "bird_dropping_event"}
    )
    rain_events = sum(1 for event in baseline.events if "rain_cleaning" in event.event_type)
    return EnergyValidationReport(
        annual_clean_energy_kwh=baseline.annual_clean_energy_kwh,
        annual_actual_energy_kwh=baseline.annual_actual_energy_kwh,
        annual_soiling_loss_kwh=baseline.annual_soiling_loss_kwh,
        annual_soiling_loss_percent=baseline.annual_soiling_loss_percent,
        monthly_clean_energy_kwh=monthly_clean,
        monthly_actual_energy_kwh=monthly_actual,
        specific_yield_kwh_per_kwp=baseline.annual_clean_energy_kwh / dc_capacity_kw,
        capacity_factor_percent=baseline.annual_clean_energy_kwh / (dc_capacity_kw * hours) * 100.0,
        clipping_energy_kwh=clipping,
        clipping_percent_of_dc_energy=clipping / dc_energy_kwh * 100.0
        if dc_energy_kwh > 0
        else 0.0,
        contamination_event_count=contamination_events,
        rain_event_count=rain_events,
    )


def validate_farm_equivalence(
    clean: CleanEnergyProfile,
    farm: FarmConfig,
    *,
    tolerance_kwh: float = 1e-6,
) -> FarmEquivalenceReport:
    representative = RepresentativePanelFarm(farm)
    cohort = CohortFarm(farm)
    representative_total = 0.0
    cohort_total = 0.0
    rng = np.random.default_rng(0)
    for day_index, row in clean.daily.iterrows():
        day = datetime.fromisoformat(str(day_index)).date()
        clean_per_panel = float(row["clean_ac_energy_kwh"]) / farm.total_panels
        representative_state = representative.initial_state(day, rng)
        cohort_state = cohort.initial_state(day, rng)
        representative_total += representative.calculate_daily_energy(
            representative_state, clean_per_panel
        ).actual_energy_kwh
        cohort_total += cohort.calculate_daily_energy(
            cohort_state, clean_per_panel
        ).actual_energy_kwh
    difference = abs(representative_total - cohort_total)
    return FarmEquivalenceReport(
        representative_energy_kwh=representative_total,
        cohort_energy_kwh=cohort_total,
        absolute_difference_kwh=difference,
        tolerance_kwh=tolerance_kwh,
        passed=difference <= tolerance_kwh,
    )


def _monthly_totals(frame: pd.DataFrame, column: str) -> dict[str, float]:
    index = pd.DatetimeIndex(frame.index)
    return {
        str(period): float(value)
        for period, value in frame.groupby(index.to_period("M"))[column].sum().items()
    }


def _frame_checksum(frame: pd.DataFrame) -> str:
    payload = frame.to_csv(index=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _count_suspicious_weather_values(frame: pd.DataFrame) -> int:
    suspicious = 0
    suspicious += int((frame["ghi_w_m2"] > 1400).sum())
    suspicious += int((frame["dni_w_m2"] > 1400).sum())
    suspicious += int((frame["dhi_w_m2"] > 800).sum())
    suspicious += int(((frame["temp_air_c"] < -20) | (frame["temp_air_c"] > 65)).sum())
    suspicious += int((frame["wind_speed_m_s"] > 60).sum())
    suspicious += int((frame["precipitation_mm"] > 200).sum())
    return suspicious


def _directory_size_mb(path: Path) -> float:
    total = sum(file.stat().st_size for file in path.rglob("*") if file.is_file())
    return total / (1024 * 1024)
