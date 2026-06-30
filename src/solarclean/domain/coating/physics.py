from __future__ import annotations

import math
from dataclasses import dataclass

from solarclean.config.models import CoatingPhysicsConfig, CoatingWaterConfig


@dataclass(frozen=True)
class CondensationResult:
    dew_point_c: float
    surface_temperature_c: float
    condensed_liters: float
    potentially_collectable_liters: float
    actually_collected_liters: float


@dataclass(frozen=True)
class BirdRemovalResult:
    removed_coverage_fraction: float
    remaining_coverage_fraction: float


@dataclass(frozen=True)
class EnergyMechanismResult:
    clean_reference_energy_kwh: float
    optical_effect_kwh: float
    temperature_effect_kwh: float
    cleanliness_effect_kwh: float
    final_energy_kwh: float
    optical_multiplier: float
    temperature_multiplier: float
    cleanliness_ratio: float


def calculate_dew_point_c(air_temperature_c: float, relative_humidity_pct: float) -> float:
    humidity = min(100.0, max(1e-6, relative_humidity_pct))
    a = 17.625
    b = 243.04
    alpha = math.log(humidity / 100.0) + (a * air_temperature_c) / (b + air_temperature_c)
    return (b * alpha) / (a - alpha)


def calculate_surface_temperature_c(
    *,
    air_temperature_c: float,
    relative_humidity_pct: float,
    wind_speed_m_s: float,
    irradiance_w_m2: float,
    physics: CoatingPhysicsConfig,
) -> float:
    humidity_factor = min(
        1.2,
        max(0.0, relative_humidity_pct / physics.humidity_cooling_reference_pct),
    )
    wind_factor = math.exp(-physics.wind_cooling_decay_per_m_s * max(0.0, wind_speed_m_s))
    night_factor = 1.0 if irradiance_w_m2 <= 5.0 else physics.daytime_cooling_fraction
    cooling = (
        physics.max_surface_cooling_c
        * physics.emissivity_atmospheric_window
        * humidity_factor
        * wind_factor
        * night_factor
    )
    return air_temperature_c - cooling


def calculate_condensation(
    *,
    air_temperature_c: float,
    relative_humidity_pct: float,
    surface_temperature_c: float,
    exposure_hours: float,
    area_m2: float,
    water: CoatingWaterConfig,
) -> CondensationResult:
    dew_point = calculate_dew_point_c(air_temperature_c, relative_humidity_pct)
    if (
        relative_humidity_pct < water.minimum_relative_humidity_pct
        or surface_temperature_c >= dew_point
        or exposure_hours <= 0.0
        or area_m2 <= 0.0
    ):
        condensed = 0.0
    else:
        depression = dew_point - surface_temperature_c
        condensed = (
            depression * exposure_hours * area_m2 * water.condensation_liters_per_m2_per_c_hour
        )
    potential = condensed * water.collectable_water_efficiency_fraction
    actual = potential * water.actual_collection_efficiency_fraction
    return CondensationResult(
        dew_point_c=dew_point,
        surface_temperature_c=surface_temperature_c,
        condensed_liters=condensed,
        potentially_collectable_liters=potential,
        actually_collected_liters=actual,
    )


def calculate_passive_dust_cleaning(
    *,
    current_dust_soiling_ratio: float,
    condensed_liters_per_m2: float,
    tilt_degrees: float,
    coating_effectiveness: float,
    physics: CoatingPhysicsConfig,
) -> float:
    recoverable = max(0.0, 1.0 - current_dust_soiling_ratio)
    if recoverable == 0.0 or condensed_liters_per_m2 <= 0.0 or coating_effectiveness <= 0.0:
        return 0.0
    tilt_factor = min(
        1.0,
        max(0.0, tilt_degrees / physics.passive_cleaning_tilt_reference_degrees),
    )
    water_factor = min(1.0, condensed_liters_per_m2 / 0.128)
    restored = recoverable * physics.passive_cleaning_base_efficiency * tilt_factor * water_factor
    return min(recoverable, restored * coating_effectiveness)


def apply_bird_removal(
    *,
    current_coverage_fraction: float,
    condensed_liters_per_m2: float,
    coating_effectiveness: float,
    physics: CoatingPhysicsConfig,
) -> BirdRemovalResult:
    if (
        current_coverage_fraction <= 0.0
        or condensed_liters_per_m2 <= 0.0
        or coating_effectiveness <= 0.0
    ):
        removed = 0.0
    else:
        water_factor = min(1.0, condensed_liters_per_m2 / 0.128)
        candidate = current_coverage_fraction * physics.bird_removal_efficiency * water_factor
        removed = min(
            current_coverage_fraction,
            physics.max_bird_removal_fraction_per_day,
            candidate * coating_effectiveness,
        )
    return BirdRemovalResult(
        removed_coverage_fraction=removed,
        remaining_coverage_fraction=max(0.0, current_coverage_fraction - removed),
    )


def calculate_energy_mechanisms(
    *,
    clean_energy_kwh: float,
    cleanliness_ratio: float,
    optical_transmittance_multiplier: float,
    cooling_delta_c: float,
    gamma_pdc_per_c: float,
) -> EnergyMechanismResult:
    clean = max(0.0, clean_energy_kwh)
    optical_multiplier = min(1.0, max(0.0, optical_transmittance_multiplier))
    clean_ratio = min(1.0, max(0.0, cleanliness_ratio))
    temperature_multiplier = max(0.0, 1.0 + abs(gamma_pdc_per_c) * max(0.0, cooling_delta_c))
    optical_effect = clean * (optical_multiplier - 1.0)
    temperature_effect = clean * optical_multiplier * clean_ratio * (temperature_multiplier - 1.0)
    cleanliness_effect = clean * (clean_ratio - 1.0)
    final = clean + optical_effect + temperature_effect + cleanliness_effect
    final = min(clean, max(0.0, final))
    return EnergyMechanismResult(
        clean_reference_energy_kwh=clean,
        optical_effect_kwh=optical_effect,
        temperature_effect_kwh=temperature_effect,
        cleanliness_effect_kwh=cleanliness_effect,
        final_energy_kwh=final,
        optical_multiplier=optical_multiplier,
        temperature_multiplier=temperature_multiplier,
        cleanliness_ratio=clean_ratio,
    )
