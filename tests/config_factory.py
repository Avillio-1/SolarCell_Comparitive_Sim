from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from solarclean.config.loader import load_config
from solarclean.config.models import (
    CalibrationConfig,
    CoatingConfig,
    ReactiveCVConfig,
    SolarCleanConfig,
)

DEFAULT_CONFIG_PATH = Path("configs/default.yaml")
RIYADH_FACTORY_CONFIG_PATH = Path("src/solarclean/dashboard/defaults/riyadh_default.yaml")


def _merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def config_from_default(overrides: Mapping[str, Any] | None = None) -> SolarCleanConfig:
    payload = load_config(RIYADH_FACTORY_CONFIG_PATH).model_dump(mode="python")
    return SolarCleanConfig.model_validate(_merge(payload, overrides or {}))


def fixture_config(overrides: Mapping[str, Any] | None = None) -> SolarCleanConfig:
    """Two-day deterministic test config; not a user-facing YAML preset."""

    payload = load_config(RIYADH_FACTORY_CONFIG_PATH).model_dump(mode="python")
    payload = _merge(
        payload,
        {
            "simulation": {
                "start": "2025-01-01T00:00:00+03:00",
                "end": "2025-01-02T23:00:00+03:00",
                "run_id_prefix": "test-fixture",
            },
            "weather": {"provider": "fixture", "fixture_profile": "riyadh_synthetic"},
            "farm": {
                # Keep the frozen regression fixture independent of runtime
                # changes to the default farm resolution.
                "cohort_count": 100,
                "panels_per_cohort": 100,
                "cohort_soiling_variation_fraction": 0.0,
            },
            "soiling": {
                "base_daily_soiling_loss_fraction": 0.0025,
                "seasonal_multipliers": {1: 1.0},
                "dust_event_probability": 0.2,
                "dust_event_loss_min_fraction": 0.005,
                "dust_event_loss_max_fraction": 0.01,
                "minimum_soiling_ratio": 0.7,
                "stochastic_std_fraction": 0.0,
                "random_seed": 42,
            },
            "bird_droppings": {
                "event_probability_per_cohort_day": 0.02,
                "coverage_min_fraction": 0.001,
                "coverage_max_fraction": 0.004,
                "loss_per_coverage_fraction": 0.8,
                "rain_removal_efficiency": 0.3,
            },
            "coating": CoatingConfig().model_dump(mode="python"),
            "reactive_cv": ReactiveCVConfig().model_dump(mode="python"),
            "calibration": CalibrationConfig().model_dump(mode="python"),
        },
    )
    return SolarCleanConfig.model_validate(_merge(payload, overrides or {}))


def full_year_fixture_config(overrides: Mapping[str, Any] | None = None) -> SolarCleanConfig:
    return config_from_default(
        _merge(
            {
                "weather": {"provider": "fixture", "fixture_profile": "riyadh_synthetic"},
                "simulation": {"run_id_prefix": "test-full-year-fixture"},
            },
            overrides or {},
        )
    )


def paper_calibration_config(overrides: Mapping[str, Any] | None = None) -> SolarCleanConfig:
    return fixture_config(
        _merge(
            {
                "simulation": {
                    "end": "2025-01-01T23:00:00+03:00",
                    "run_id_prefix": "test-paper-calibration",
                },
                "site": {
                    "name": "KAUST paper smoke fixture",
                    "latitude": 22.305,
                    "longitude": 39.104,
                },
                "weather": {
                    "provider": "csv",
                    "local_csv_path": Path("data/fixtures/coating_paper_calibration_weather.csv"),
                    "timestamp_column": "timestamp",
                },
                "soiling": {
                    "base_daily_soiling_loss_fraction": 0.0015555555555555555,
                    "dust_event_probability": 0.0,
                    "dust_event_loss_min_fraction": 0.0,
                    "dust_event_loss_max_fraction": 0.0,
                },
                "bird_droppings": {
                    "event_probability_per_cohort_day": 0.0,
                    "coverage_min_fraction": 0.0,
                    "coverage_max_fraction": 0.0,
                },
                "coating": {
                    "preset": "paper_calibration",
                    "physics": {
                        "source_optical_transmittance_absolute_fraction": 0.913,
                        "dust_accumulation_multiplier": 0.05357142857142857,
                        "annual_degradation_fraction": 0.02,
                        "max_surface_cooling_c": 7.0,
                        "daytime_cooling_fraction": 0.0,
                        "passive_cleaning_base_efficiency": 0.0,
                        "bird_removal_efficiency": 0.08,
                        "max_bird_removal_fraction_per_day": 0.02,
                    },
                    "water": {
                        "condensation_liters_per_m2_per_c_hour": 0.0046767,
                        "minimum_relative_humidity_pct": 60,
                        "collectable_water_efficiency_fraction": 1.0,
                        "actual_collection_efficiency_fraction": 1.0,
                    },
                    "deployment": {"useful_life_years": 5},
                    "costs": {"useful_life_years": 5},
                },
            },
            overrides or {},
        )
    )


def endpoint_calibration_config(overrides: Mapping[str, Any] | None = None) -> SolarCleanConfig:
    return fixture_config(
        _merge(
            {
                "simulation": {
                    "end": "2025-06-29T23:00:00+03:00",
                    "run_id_prefix": "test-endpoint-calibration",
                },
                "weather": {"provider": "fixture", "fixture_profile": "riyadh_synthetic"},
                "soiling": {
                    "base_daily_soiling_loss_fraction": 0.0015555555555555555,
                    "seasonal_multipliers": {month: 1.0 for month in range(1, 7)},
                    "dust_event_probability": 0.0,
                    "dust_event_loss_min_fraction": 0.0,
                    "dust_event_loss_max_fraction": 0.0,
                    "minimum_soiling_ratio": 0.70,
                    "stochastic_std_fraction": 0.0,
                },
                "rainfall_cleaning": {
                    "partial_rain_threshold_mm": 999.0,
                    "full_rain_cleaning_threshold_mm": 999.0,
                    "partial_rain_cleaning_efficiency": 0.0,
                    "full_rain_cleaning_efficiency": 0.0,
                },
                "bird_droppings": {
                    "event_probability_per_cohort_day": 0.0,
                    "coverage_min_fraction": 0.0,
                    "coverage_max_fraction": 0.0,
                    "rain_removal_efficiency": 0.0,
                },
                "coating": {
                    "preset": "paper_endpoint_calibration",
                    "physics": {
                        "source_optical_transmittance_absolute_fraction": 0.913,
                        "dust_accumulation_multiplier": 0.05357142857142857,
                        "annual_degradation_fraction": 0.0,
                        "max_surface_cooling_c": 0.0,
                        "daytime_cooling_fraction": 0.0,
                        "passive_cleaning_base_efficiency": 0.0,
                        "bird_removal_efficiency": 0.0,
                        "max_bird_removal_fraction_per_day": 0.0,
                    },
                    "water": {"condensation_liters_per_m2_per_c_hour": 0.0},
                    "deployment": {"useful_life_years": 5},
                    "costs": {"useful_life_years": 5},
                },
            },
            overrides or {},
        )
    )


def kaust_strong_config(overrides: Mapping[str, Any] | None = None) -> SolarCleanConfig:
    return endpoint_calibration_config(
        _merge(
            {
                "simulation": {"run_id_prefix": "test-kaust-strong"},
                "weather": {"fixture_profile": "kaust_paper_favorable"},
                "coating": {
                    "preset": "kaust_paper_strong",
                    "physics": {
                        "dust_accumulation_multiplier": 0.90,
                        "max_surface_cooling_c": 7.0,
                        "passive_cleaning_base_efficiency": 0.110,
                        "wind_shedding_threshold_m_s": 8.0,
                        "wind_shedding_reference_m_s": 14.0,
                        "wind_shedding_base_efficiency": 0.05,
                        "rain_shedding_base_efficiency": 0.20,
                        "bird_removal_efficiency": 0.05,
                        "max_bird_removal_fraction_per_day": 0.01,
                    },
                    "water": {
                        "condensation_liters_per_m2_per_c_hour": 0.0046767,
                        "minimum_relative_humidity_pct": 65,
                        "collectable_water_efficiency_fraction": 1.0,
                        "actual_collection_efficiency_fraction": 1.0,
                    },
                },
            },
            overrides or {},
        )
    )
