from __future__ import annotations

import pytest

from solarclean.config.models import CoatingPhysicsConfig, CoatingWaterConfig
from solarclean.domain.coating.physics import (
    apply_bird_removal,
    calculate_condensation,
    calculate_dew_point_c,
    calculate_energy_mechanisms,
    calculate_passive_dust_cleaning,
    calculate_surface_temperature_c,
)


def test_dew_point_and_condensation_require_surface_below_dew_point() -> None:
    dew_point = calculate_dew_point_c(air_temperature_c=20.0, relative_humidity_pct=80.0)
    surface = calculate_surface_temperature_c(
        air_temperature_c=20.0,
        relative_humidity_pct=80.0,
        wind_speed_m_s=0.5,
        irradiance_w_m2=0.0,
        physics=CoatingPhysicsConfig(max_surface_cooling_c=7.0),
    )
    condensation = calculate_condensation(
        air_temperature_c=20.0,
        relative_humidity_pct=80.0,
        surface_temperature_c=surface,
        exposure_hours=1.0,
        area_m2=10.0,
        water=CoatingWaterConfig(condensation_liters_per_m2_per_c_hour=0.01),
    )

    assert dew_point == pytest.approx(16.44, abs=0.15)
    assert surface < dew_point
    assert condensation.condensed_liters > 0.0
    assert condensation.potentially_collectable_liters <= condensation.condensed_liters
    assert condensation.actually_collected_liters <= condensation.potentially_collectable_liters


def test_no_condensation_when_humidity_or_temperature_conditions_fail() -> None:
    low_humidity = calculate_condensation(
        air_temperature_c=28.0,
        relative_humidity_pct=35.0,
        surface_temperature_c=10.0,
        exposure_hours=1.0,
        area_m2=20.0,
        water=CoatingWaterConfig(minimum_relative_humidity_pct=60.0),
    )
    warm_surface = calculate_condensation(
        air_temperature_c=20.0,
        relative_humidity_pct=80.0,
        surface_temperature_c=19.0,
        exposure_hours=1.0,
        area_m2=20.0,
        water=CoatingWaterConfig(),
    )

    assert low_humidity.condensed_liters == 0.0
    assert warm_surface.condensed_liters == 0.0


def test_condensation_allows_surface_at_dew_point() -> None:
    dew_point = calculate_dew_point_c(air_temperature_c=20.0, relative_humidity_pct=80.0)

    condensation = calculate_condensation(
        air_temperature_c=20.0,
        relative_humidity_pct=80.0,
        surface_temperature_c=dew_point,
        exposure_hours=1.0,
        area_m2=20.0,
        water=CoatingWaterConfig(condensation_liters_per_m2_per_c_hour=0.01),
    )

    assert condensation.condensed_liters == pytest.approx(0.0)


def test_humidity_raises_dew_point_but_reduces_radiative_cooling() -> None:
    physics = CoatingPhysicsConfig(max_surface_cooling_c=7.0, humidity_cooling_reference_pct=80)

    dew_at_70 = calculate_dew_point_c(air_temperature_c=20.0, relative_humidity_pct=70.0)
    dew_at_95 = calculate_dew_point_c(air_temperature_c=20.0, relative_humidity_pct=95.0)
    surface_at_70 = calculate_surface_temperature_c(
        air_temperature_c=20.0,
        relative_humidity_pct=70.0,
        wind_speed_m_s=0.5,
        irradiance_w_m2=0.0,
        physics=physics,
    )
    surface_at_95 = calculate_surface_temperature_c(
        air_temperature_c=20.0,
        relative_humidity_pct=95.0,
        wind_speed_m_s=0.5,
        irradiance_w_m2=0.0,
        physics=physics,
    )

    assert dew_at_95 > dew_at_70
    assert surface_at_95 > surface_at_70


def test_wind_decay_and_cooling_bounds() -> None:
    physics = CoatingPhysicsConfig(max_surface_cooling_c=7.0, emissivity_atmospheric_window=0.9)
    calm_surface = calculate_surface_temperature_c(
        air_temperature_c=20.0,
        relative_humidity_pct=70.0,
        wind_speed_m_s=0.0,
        irradiance_w_m2=0.0,
        physics=physics,
    )
    windy_surface = calculate_surface_temperature_c(
        air_temperature_c=20.0,
        relative_humidity_pct=70.0,
        wind_speed_m_s=8.0,
        irradiance_w_m2=0.0,
        physics=physics,
    )
    calm_cooling = 20.0 - calm_surface
    windy_cooling = 20.0 - windy_surface

    assert windy_cooling < calm_cooling
    assert calm_cooling <= physics.max_surface_cooling_c


def test_passive_cleaning_and_bird_removal_are_bounded() -> None:
    physics = CoatingPhysicsConfig(
        passive_cleaning_base_efficiency=0.5,
        max_bird_removal_fraction_per_day=0.02,
        bird_removal_efficiency=0.5,
    )

    dust_restored = calculate_passive_dust_cleaning(
        current_dust_soiling_ratio=0.80,
        condensed_liters_per_m2=0.20,
        tilt_degrees=25.0,
        coating_effectiveness=0.9,
        physics=physics,
    )
    bird = apply_bird_removal(
        current_coverage_fraction=0.10,
        condensed_liters_per_m2=0.20,
        coating_effectiveness=0.9,
        physics=physics,
    )

    assert 0.0 < dust_restored <= 0.20
    assert bird.removed_coverage_fraction == pytest.approx(0.02)
    assert bird.remaining_coverage_fraction == pytest.approx(0.08)


def test_energy_mechanisms_report_realized_sequential_contributions() -> None:
    result = calculate_energy_mechanisms(
        clean_energy_kwh=100.0,
        cleanliness_ratio=0.80,
        optical_transmittance_multiplier=0.97,
        cooling_delta_c=5.0,
        gamma_pdc_per_c=-0.0035,
    )

    assert result.optical_effect_kwh < 0.0
    assert result.temperature_effect_kwh > 0.0
    assert result.cleanliness_effect_kwh == pytest.approx(-19.4)
    assert result.final_energy_kwh == pytest.approx(
        result.clean_reference_energy_kwh
        + result.optical_effect_kwh
        + result.cleanliness_effect_kwh
        + result.temperature_effect_kwh
    )


def test_cooling_can_exceed_uncoated_clean_reference_without_contamination() -> None:
    result = calculate_energy_mechanisms(
        clean_energy_kwh=100.0,
        cleanliness_ratio=1.0,
        optical_transmittance_multiplier=1.0,
        cooling_delta_c=5.0,
        gamma_pdc_per_c=-0.0035,
    )

    assert result.optical_effect_kwh == pytest.approx(0.0)
    assert result.cleanliness_effect_kwh == pytest.approx(0.0)
    assert result.temperature_effect_kwh == pytest.approx(1.75)
    assert result.final_energy_kwh == pytest.approx(101.75)
