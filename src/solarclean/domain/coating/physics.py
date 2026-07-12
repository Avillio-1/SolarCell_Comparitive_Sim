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
    if physics.humidity_cooling_mode == "smooth":
        # Water vapour progressively closes the 8-13um atmospheric window, so
        # cooling declines continuously from the dry reference instead of
        # holding full strength until a threshold.
        span = 100.0 - physics.humidity_cooling_dry_reference_pct
        humidity_factor = float(
            min(
                1.0,
                max(0.0, (100.0 - relative_humidity_pct) / span),
            )
            ** 0.5
        )
    elif relative_humidity_pct <= physics.humidity_cooling_reference_pct:
        humidity_factor = 1.0
    else:
        humidity_factor = max(
            0.0,
            (100.0 - relative_humidity_pct) / (100.0 - physics.humidity_cooling_reference_pct),
        )
    # Radiative cooling does not vanish at saturation: the KAUST coating paper
    # (10.1002/eem2.70350, Figure 3a) predicts ~6.1 C of sub-ambient cooling at
    # 90% RH versus 8.0 C at 50% RH, and field data show condensation-enabling
    # cooling on 90%+ RH nights. The floor preserves that residual capability.
    floor = physics.humidity_cooling_floor_fraction
    humidity_factor = floor + (1.0 - floor) * humidity_factor
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
        or surface_temperature_c > dew_point
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
    wind_speed_m_s: float = 0.0,
    precipitation_mm: float = 0.0,
) -> float:
    recoverable = max(0.0, 1.0 - current_dust_soiling_ratio)
    if recoverable == 0.0 or coating_effectiveness <= 0.0:
        return 0.0
    tilt_factor = min(
        1.0,
        max(0.0, tilt_degrees / physics.passive_cleaning_tilt_reference_degrees),
    )
    # Normalize surface mobility to the central characterized coating. Lower
    # contact angles or higher sliding angles reduce passive shedding; the
    # factor is capped at one so these descriptors cannot create energy from
    # an uncalibrated super-performance extrapolation.
    contact_factor = min(1.0, max(0.0, physics.contact_angle_degrees / 167.0))
    sliding_factor = min(1.0, 3.0 / max(1e-9, physics.sliding_angle_degrees))
    surface_mobility_factor = contact_factor * sliding_factor
    water_factor = min(1.0, condensed_liters_per_m2 / 0.128)
    dew_efficiency = (
        physics.passive_cleaning_base_efficiency
        * tilt_factor
        * water_factor
        * surface_mobility_factor
    )
    wind_efficiency = 0.0
    if wind_speed_m_s > physics.wind_shedding_threshold_m_s:
        denominator = max(
            1e-9, physics.wind_shedding_reference_m_s - physics.wind_shedding_threshold_m_s
        )
        wind_factor = min(
            1.0, max(0.0, (wind_speed_m_s - physics.wind_shedding_threshold_m_s) / denominator)
        )
        wind_efficiency = physics.wind_shedding_base_efficiency * tilt_factor * wind_factor
    rain_factor = min(1.0, max(0.0, precipitation_mm) / physics.rain_shedding_reference_mm)
    rain_efficiency = physics.rain_shedding_base_efficiency * tilt_factor * rain_factor
    combined_efficiency = 1.0
    for efficiency in (dew_efficiency, wind_efficiency, rain_efficiency):
        combined_efficiency *= 1.0 - min(1.0, max(0.0, efficiency))
    restored = recoverable * (1.0 - combined_efficiency) * coating_effectiveness
    return min(recoverable, restored)


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
    optical_multiplier = min(1.2, max(0.0, optical_transmittance_multiplier))
    clean_ratio = min(1.0, max(0.0, cleanliness_ratio))
    temperature_multiplier = max(0.0, 1.0 + abs(gamma_pdc_per_c) * max(0.0, cooling_delta_c))
    after_optical = clean * optical_multiplier
    after_cleanliness = after_optical * clean_ratio
    final = max(0.0, after_cleanliness * temperature_multiplier)
    optical_effect = after_optical - clean
    cleanliness_effect = after_cleanliness - after_optical
    temperature_effect = final - after_cleanliness
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
