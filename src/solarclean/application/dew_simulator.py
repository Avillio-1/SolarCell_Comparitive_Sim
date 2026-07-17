from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from solarclean.config.models import SolarCleanConfig
from solarclean.domain.coating.physics import (
    calculate_condensation,
    calculate_surface_temperature_c,
)


@dataclass(frozen=True)
class DewSimulationResult:
    """One transparent, nighttime coating-water calculation.

    The simulator deliberately reuses the coating domain physics. The web
    dashboard only supplies inputs and renders this record; it does not carry
    a second copy of the dew model in JavaScript.
    """

    air_temperature_c: float
    relative_humidity_pct: float
    wind_speed_m_s: float
    dew_point_c: float
    coated_surface_temperature_c: float
    cooling_delta_c: float
    dew_margin_c: float
    minimum_relative_humidity_pct: float
    humidity_gate_margin_pct_points: float
    dew_eligible: bool
    harvest_active: bool
    status_code: str
    status_message: str
    condensed_liters_per_m2_hour: float
    harvested_liters_per_m2_hour: float
    whole_farm_harvested_liters_per_hour: float
    coated_area_m2: float
    exposure_hours: float = 1.0
    irradiance_w_m2: float = 0.0

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def simulate_nighttime_dew(
    config: SolarCleanConfig,
    *,
    air_temperature_c: float,
    relative_humidity_pct: float,
    wind_speed_m_s: float,
) -> DewSimulationResult:
    """Evaluate the configured coating for one representative night hour."""

    temperature = _finite_input("air_temperature_c", air_temperature_c, low=-40.0, high=70.0)
    humidity = _finite_input(
        "relative_humidity_pct",
        relative_humidity_pct,
        low=1.0,
        high=100.0,
    )
    wind = _finite_input("wind_speed_m_s", wind_speed_m_s, low=0.0, high=40.0)
    coating = config.coating
    area_m2 = float(config.farm.total_panels) * coating.deployment.area_per_panel_m2
    surface_temperature = calculate_surface_temperature_c(
        air_temperature_c=temperature,
        relative_humidity_pct=humidity,
        wind_speed_m_s=wind,
        irradiance_w_m2=0.0,
        physics=coating.physics,
    )
    water = calculate_condensation(
        air_temperature_c=temperature,
        relative_humidity_pct=humidity,
        surface_temperature_c=surface_temperature,
        exposure_hours=1.0,
        area_m2=1.0,
        water=coating.water,
    )

    coating_enabled = coating.enabled
    condensed_per_m2 = water.condensed_liters if coating_enabled else 0.0
    harvested_per_m2 = water.actually_collected_liters if coating_enabled else 0.0
    dew_eligible = condensed_per_m2 > 0.0
    harvest_active = harvested_per_m2 > 0.0
    status_code, status_message = _status(
        coating_enabled=coating_enabled,
        relative_humidity_pct=humidity,
        minimum_relative_humidity_pct=coating.water.minimum_relative_humidity_pct,
        dew_margin_c=water.dew_point_c - surface_temperature,
        dew_eligible=dew_eligible,
        harvest_active=harvest_active,
        condensation_coefficient=coating.water.condensation_liters_per_m2_per_c_hour,
    )
    return DewSimulationResult(
        air_temperature_c=temperature,
        relative_humidity_pct=humidity,
        wind_speed_m_s=wind,
        dew_point_c=water.dew_point_c,
        coated_surface_temperature_c=surface_temperature,
        cooling_delta_c=max(0.0, temperature - surface_temperature),
        dew_margin_c=water.dew_point_c - surface_temperature,
        minimum_relative_humidity_pct=coating.water.minimum_relative_humidity_pct,
        humidity_gate_margin_pct_points=(humidity - coating.water.minimum_relative_humidity_pct),
        dew_eligible=dew_eligible,
        harvest_active=harvest_active,
        status_code=status_code,
        status_message=status_message,
        condensed_liters_per_m2_hour=condensed_per_m2,
        harvested_liters_per_m2_hour=harvested_per_m2,
        whole_farm_harvested_liters_per_hour=harvested_per_m2 * area_m2,
        coated_area_m2=area_m2,
    )


def _status(
    *,
    coating_enabled: bool,
    relative_humidity_pct: float,
    minimum_relative_humidity_pct: float,
    dew_margin_c: float,
    dew_eligible: bool,
    harvest_active: bool,
    condensation_coefficient: float,
) -> tuple[str, str]:
    if not coating_enabled:
        status = ("coating_disabled", "The coating is disabled in this run configuration.")
    elif condensation_coefficient <= 0.0:
        status = (
            "water_model_disabled",
            "This run does not enable a coating-water yield model.",
        )
    elif relative_humidity_pct < minimum_relative_humidity_pct:
        shortfall = minimum_relative_humidity_pct - relative_humidity_pct
        status = (
            "below_humidity_gate",
            f"Relative humidity is {shortfall:.1f} percentage points below the collection gate.",
        )
    elif dew_margin_c < 0.0:
        status = (
            "surface_above_dew_point",
            f"The coated surface is {-dew_margin_c:.1f} °C too warm for dew.",
        )
    elif not dew_eligible:
        status = ("no_condensation", "The configured model produces no condensation here.")
    elif not harvest_active:
        status = (
            "collection_disabled",
            "Dew forms, but this run does not route it to collection.",
        )
    else:
        status = (
            "harvesting",
            "The coated surface is below the dew point and harvesting water.",
        )
    return status


def _finite_input(name: str, value: float, *, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if not low <= number <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return number
