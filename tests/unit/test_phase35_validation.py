from __future__ import annotations

from pathlib import Path

from tests.unit.test_weather import _request

from solarclean.application.phase35 import (
    Phase35Validator,
    validate_farm_equivalence,
    validate_weather_dataset,
)
from solarclean.config.loader import load_config
from solarclean.config.models import FarmConfig
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider


def test_weather_validation_reports_timestamps_units_ranges_and_checksum() -> None:
    weather = FixtureWeatherProvider().load(_request())

    report = validate_weather_dataset(
        weather, expected_start=_request().start, expected_end=_request().end
    )

    assert report.row_count == 48
    assert report.expected_row_count == 48
    assert report.gap_count == 0
    assert report.duplicate_count == 0
    assert report.timezone == "Asia/Riyadh"
    assert report.checksum_sha256
    assert report.canonical_units["ghi_w_m2"] == "W/m2"
    assert "ghi_w_m2" in report.ranges
    assert report.suspicious_value_count == 0


def test_phase35_validator_reports_energy_soiling_events_and_outputs(tmp_path: Path) -> None:
    config = load_config(
        Path("configs/offline_fixture.yaml"), overrides={"output": {"base_directory": tmp_path}}
    )

    result = Phase35Validator(config).run()

    assert result.output_directory.exists()
    assert (result.output_directory / "phase35_weather_report.json").exists()
    assert (result.output_directory / "phase35_energy_report.json").exists()
    assert (result.output_directory / "phase35_farm_equivalence_report.json").exists()
    assert result.summary["annual_clean_energy_kwh"] > result.summary["annual_actual_energy_kwh"]
    assert result.summary["specific_yield_kwh_per_kwp"] > 0
    assert result.summary["capacity_factor_percent"] > 0
    assert result.summary["soiling_loss_percent"] > 0
    assert result.summary["event_tape_checksum"]


def test_homogeneous_representative_and_cohort_farms_match() -> None:
    weather = FixtureWeatherProvider().load(_request())
    clean = PVWattsPowerModel().calculate_hourly(weather)
    farm = FarmConfig(
        total_panels=10000,
        panel_capacity_w=400,
        cohort_count=100,
        panels_per_cohort=100,
        cohort_soiling_variation_fraction=0.0,
    )

    report = validate_farm_equivalence(clean, farm)

    assert report.passed is True
    assert report.absolute_difference_kwh <= report.tolerance_kwh
