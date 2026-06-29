from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WeatherProviderName = Literal["nasa_power", "csv", "fixture"]
FarmRepresentationName = Literal["representative", "cohort"]
MissingDataPolicy = Literal["error", "drop", "interpolate"]


def _validate_timezone_name(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {value}") from exc
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SimulationConfig(StrictModel):
    start: datetime
    end: datetime
    target_timezone: str = "Asia/Riyadh"
    run_id_prefix: str = "solarclean"

    @field_validator("start", "end")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("simulation datetimes must be timezone-aware")
        return value

    @field_validator("target_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _validate_timezone_name(value)

    @model_validator(mode="after")
    def validate_date_range(self) -> SimulationConfig:
        if self.end <= self.start:
            raise ValueError("simulation.end must be after simulation.start")
        return self


class SiteConfig(StrictModel):
    name: str = "Riyadh"
    latitude: float = Field(default=24.7136, ge=-90, le=90)
    longitude: float = Field(default=46.6753, ge=-180, le=180)
    timezone: str = "Asia/Riyadh"
    elevation_m: float | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _validate_timezone_name(value)


class WeatherConfig(StrictModel):
    provider: WeatherProviderName = "nasa_power"
    cache_enabled: bool = True
    cache_directory: Path = Path("data/cache/weather")
    local_csv_path: Path | None = None
    timestamp_column: str = "timestamp"
    column_mapping: dict[str, str] = Field(default_factory=dict)
    unit_mapping: dict[str, str] = Field(default_factory=dict)
    missing_data_policy: MissingDataPolicy = "error"
    timeout_seconds: float = Field(default=30.0, gt=0)

    @field_validator("provider", mode="before")
    @classmethod
    def provider_error_message(cls, value: object) -> object:
        allowed = {"nasa_power", "csv", "fixture"}
        if isinstance(value, str) and value not in allowed:
            raise ValueError("weather.provider must be one of nasa_power, csv, fixture")
        return value


class PVSystemConfig(StrictModel):
    panel_count: int = Field(default=10000, gt=0)
    panel_capacity_w: float = Field(default=400.0, gt=0)
    tilt_degrees: float = Field(default=25.0, ge=0, le=90)
    azimuth_degrees: float = Field(default=180.0, ge=0, le=360)
    inverter_efficiency: float = Field(default=0.96, gt=0, le=1)
    dc_ac_ratio: float = Field(default=1.15, gt=0)
    gamma_pdc_per_c: float = -0.0035
    module_temperature_model: Literal["pvsyst_cell", "sapm_open_rack_glass_glass"] = "pvsyst_cell"

    @property
    def total_dc_capacity_w(self) -> float:
        return float(self.panel_count) * self.panel_capacity_w


class FarmConfig(StrictModel):
    representation: FarmRepresentationName = "cohort"
    total_panels: int = Field(default=10000, gt=0)
    panel_capacity_w: float = Field(default=400.0, gt=0)
    cohort_count: int = Field(default=100, gt=0)
    panels_per_cohort: int = Field(default=100, gt=0)
    store_cohort_daily_details: bool = True
    cohort_soiling_variation_fraction: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_cohort_product(self) -> FarmConfig:
        if self.representation == "cohort":
            product = self.cohort_count * self.panels_per_cohort
            if product != self.total_panels:
                raise ValueError(
                    "cohort_count * panels_per_cohort must equal total_panels "
                    f"({product} != {self.total_panels})"
                )
        return self


class SoilingConfig(StrictModel):
    base_daily_soiling_loss_fraction: float = Field(default=0.0025, ge=0, le=1)
    seasonal_multipliers: dict[int, float] = Field(default_factory=dict)
    dust_event_probability: float = Field(default=0.03, ge=0, le=1)
    dust_event_loss_min_fraction: float = Field(default=0.005, ge=0, le=1)
    dust_event_loss_max_fraction: float = Field(default=0.03, ge=0, le=1)
    minimum_soiling_ratio: float = Field(default=0.55, gt=0, le=1)
    stochastic_std_fraction: float = Field(default=0.1, ge=0)
    random_seed: int = 42

    @model_validator(mode="after")
    def validate_dust_event_range(self) -> SoilingConfig:
        if self.dust_event_loss_max_fraction < self.dust_event_loss_min_fraction:
            raise ValueError("dust_event_loss_max_fraction must be >= min")
        return self


class RainfallCleaningConfig(StrictModel):
    partial_rain_threshold_mm: float = Field(default=1.0, ge=0)
    full_rain_cleaning_threshold_mm: float = Field(default=5.0, ge=0)
    partial_rain_cleaning_efficiency: float = Field(default=0.45, ge=0, le=1)
    full_rain_cleaning_efficiency: float = Field(default=0.95, ge=0, le=1)

    @model_validator(mode="after")
    def validate_thresholds(self) -> RainfallCleaningConfig:
        if self.full_rain_cleaning_threshold_mm < self.partial_rain_threshold_mm:
            raise ValueError("full rain threshold must be >= partial rain threshold")
        return self


class BirdDroppingConfig(StrictModel):
    event_probability_per_cohort_day: float = Field(default=0.01, ge=0, le=1)
    coverage_min_fraction: float = Field(default=0.001, ge=0, le=1)
    coverage_max_fraction: float = Field(default=0.01, ge=0, le=1)
    loss_per_coverage_fraction: float = Field(default=0.8, ge=0)
    rain_removal_efficiency: float = Field(default=0.3, ge=0, le=1)

    @model_validator(mode="after")
    def validate_coverage_range(self) -> BirdDroppingConfig:
        if self.coverage_max_fraction < self.coverage_min_fraction:
            raise ValueError("coverage_max_fraction must be >= coverage_min_fraction")
        return self


class OutputConfig(StrictModel):
    base_directory: Path = Path("outputs")
    include_cohort_daily_details: bool = True
    csv_float_format: str = "%.10f"


class LoggingConfig(StrictModel):
    level: str = "INFO"


class SolarCleanConfig(StrictModel):
    simulation: SimulationConfig
    site: SiteConfig = Field(default_factory=SiteConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    pv_system: PVSystemConfig = Field(default_factory=PVSystemConfig)
    farm: FarmConfig = Field(default_factory=FarmConfig)
    soiling: SoilingConfig = Field(default_factory=SoilingConfig)
    rainfall_cleaning: RainfallCleaningConfig = Field(default_factory=RainfallCleaningConfig)
    bird_droppings: BirdDroppingConfig = Field(default_factory=BirdDroppingConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @model_validator(mode="after")
    def validate_cross_section_consistency(self) -> SolarCleanConfig:
        if self.pv_system.panel_count != self.farm.total_panels:
            raise ValueError("pv_system.panel_count must equal farm.total_panels")
        if self.pv_system.panel_capacity_w != self.farm.panel_capacity_w:
            raise ValueError("pv_system.panel_capacity_w must equal farm.panel_capacity_w")
        return self
