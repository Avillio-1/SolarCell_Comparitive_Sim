from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WeatherProviderName = Literal["nasa_power", "csv", "fixture"]
FixtureWeatherProfileName = Literal["riyadh_synthetic", "riyadh_dry", "kaust_paper_favorable"]
FarmRepresentationName = Literal["representative", "cohort"]
MissingDataPolicy = Literal["error", "drop", "interpolate"]
CoatingPresetName = Literal[
    "weak",
    "central",
    "strong",
    "paper_calibration",
    "paper_endpoint_calibration",
    "kaust_paper_strong",
]
CoatingDeploymentMode = Literal["factory_preinstall", "retrofit"]
AssumptionLevel = Literal["weak", "central", "strong"]
SourceStatus = Literal["prompt_quoted", "provisional", "unsourced"]


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
    fixture_profile: FixtureWeatherProfileName = "riyadh_synthetic"
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


class DewCementationConfig(StrictModel):
    """Humidity-driven dust cementation (dew wets deposited dust, which dries
    into an adherent crust). Disabled by default so the frozen Riyadh
    calibration sets keep their exact historical behavior."""

    enabled: bool = False
    onset_relative_humidity_pct: float = Field(default=75.0, ge=0, le=100)
    saturation_relative_humidity_pct: float = Field(default=95.0, ge=0, le=100)
    max_soiling_rate_multiplier: float = Field(default=1.5, ge=1)
    max_rain_efficiency_penalty: float = Field(default=0.5, ge=0, le=1)
    memory_days: float = Field(default=10.0, ge=1)

    @model_validator(mode="after")
    def validate_humidity_range(self) -> DewCementationConfig:
        if self.saturation_relative_humidity_pct <= self.onset_relative_humidity_pct:
            raise ValueError(
                "saturation_relative_humidity_pct must exceed onset_relative_humidity_pct"
            )
        return self


class SoilingConfig(StrictModel):
    base_daily_soiling_loss_fraction: float = Field(default=0.001, ge=0, le=1)
    seasonal_multipliers: dict[int, float] = Field(default_factory=dict)
    dust_event_probability: float = Field(default=0.03, ge=0, le=1)
    dust_event_loss_min_fraction: float = Field(default=0.005, ge=0, le=1)
    dust_event_loss_max_fraction: float = Field(default=0.03, ge=0, le=1)
    minimum_soiling_ratio: float = Field(default=0.55, gt=0, le=1)
    stochastic_std_fraction: float = Field(default=0.1, ge=0)
    random_seed: int = 42
    dew_cementation: DewCementationConfig = Field(default_factory=DewCementationConfig)

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


class ReactiveInspectionConfig(StrictModel):
    interval_days: int = Field(default=15, gt=0)
    first_inspection_day_index: int = Field(default=0, ge=0)
    dirty_soiling_ratio_threshold: float = Field(default=0.92, ge=0, le=1)

    @model_validator(mode="after")
    def validate_offset(self) -> ReactiveInspectionConfig:
        if self.first_inspection_day_index >= self.interval_days:
            raise ValueError("first_inspection_day_index must be less than interval_days")
        return self


class ReactiveDroneConfig(StrictModel):
    cohorts_per_flight: int = Field(default=5, gt=0)
    flights_per_day: int = Field(default=2, gt=0)
    flight_duration_minutes: float = Field(default=18.0, gt=0)
    max_wind_speed_m_s: float = Field(default=12.0, gt=0)
    max_precipitation_mm: float = Field(default=0.2, ge=0)
    energy_kwh_per_flight: float = Field(default=0.35, ge=0)
    compute_energy_kwh_per_image: float = Field(default=0.01, ge=0)

    @property
    def max_cohorts_per_day(self) -> int:
        return self.cohorts_per_flight * self.flights_per_day


class ReactiveCVObserverConfig(StrictModel):
    recall_fraction: float = Field(default=0.80, ge=0, le=1)
    false_positive_rate: float = Field(default=0.05, ge=0, le=1)
    missed_image_fraction: float = Field(default=0.03, ge=0, le=1)
    base_confidence: float = Field(default=0.8, ge=0, le=1)
    confidence_std_fraction: float = Field(default=0.1, ge=0)
    severity_error_std_fraction: float = Field(default=0.15, ge=0)


class ReactiveDispatchConfig(StrictModel):
    estimated_loss_threshold_fraction: float = Field(default=0.04, ge=0, le=1)
    confidence_threshold: float = Field(default=0.5, ge=0, le=1)
    max_queue_age_days: int = Field(default=14, gt=0)


class ReactiveCrewConfig(StrictModel):
    daily_capacity_cohorts: int = Field(default=6, gt=0)
    setup_minutes_per_cohort: float = Field(default=8.0, ge=0)
    cleaning_minutes_per_cohort: float = Field(default=25.0, ge=0)
    water_liters_per_cohort: float = Field(default=150.0, ge=0)
    dust_removal_efficiency: float = Field(default=0.92, ge=0, le=1)
    bird_removal_efficiency: float = Field(default=0.95, ge=0, le=1)


class ReactiveCVConfig(StrictModel):
    enabled: bool = True
    perfect_information_benchmark: bool = False
    inspection: ReactiveInspectionConfig = Field(default_factory=ReactiveInspectionConfig)
    drone: ReactiveDroneConfig = Field(default_factory=ReactiveDroneConfig)
    observer: ReactiveCVObserverConfig = Field(default_factory=ReactiveCVObserverConfig)
    dispatch: ReactiveDispatchConfig = Field(default_factory=ReactiveDispatchConfig)
    crew: ReactiveCrewConfig = Field(default_factory=ReactiveCrewConfig)


class CoatingPhysicsConfig(StrictModel):
    optical_transmittance_multiplier: float = Field(default=1.0, gt=0, le=1.2)
    source_optical_transmittance_absolute_fraction: float | None = Field(default=None, gt=0, le=1)
    emissivity_atmospheric_window: float = Field(default=0.90, ge=0, le=1)
    contact_angle_degrees: float = Field(default=167.0, ge=0, le=180)
    sliding_angle_degrees: float = Field(default=3.0, ge=0, le=90)
    dust_accumulation_multiplier: float = Field(default=0.70, ge=0, le=1)
    initial_effectiveness_fraction: float = Field(default=1.0, ge=0, le=1)
    annual_degradation_fraction: float = Field(default=0.05, ge=0, le=1)
    max_surface_cooling_c: float = Field(default=0.0, ge=0)
    humidity_cooling_reference_pct: float = Field(default=80.0, ge=1, le=100)
    humidity_cooling_mode: Literal["threshold", "smooth"] = "threshold"
    humidity_cooling_dry_reference_pct: float = Field(default=40.0, ge=0, lt=100)
    humidity_cooling_floor_fraction: float = Field(default=0.0, ge=0, le=1)
    cementation_suppression_fraction: float = Field(default=0.9, ge=0, le=1)
    wind_cooling_decay_per_m_s: float = Field(default=0.08, ge=0)
    daytime_cooling_fraction: float = Field(default=0.0, ge=0, le=1)
    passive_cleaning_base_efficiency: float = Field(default=0.0, ge=0, le=1)
    passive_cleaning_tilt_reference_degrees: float = Field(default=25.0, ge=1, le=90)
    wind_shedding_threshold_m_s: float = Field(default=999.0, ge=0)
    wind_shedding_reference_m_s: float = Field(default=12.0, gt=0)
    wind_shedding_base_efficiency: float = Field(default=0.0, ge=0, le=1)
    rain_shedding_reference_mm: float = Field(default=5.0, gt=0)
    rain_shedding_base_efficiency: float = Field(default=0.0, ge=0, le=1)
    bird_removal_efficiency: float = Field(default=0.0, ge=0, le=1)
    max_bird_removal_fraction_per_day: float = Field(default=0.0, ge=0, le=1)


class CoatingWaterConfig(StrictModel):
    condensation_liters_per_m2_per_c_hour: float = Field(default=0.0, ge=0)
    minimum_relative_humidity_pct: float = Field(default=100.0, ge=0, le=100)
    collectable_water_efficiency_fraction: float = Field(default=0.0, ge=0, le=1)
    actual_collection_efficiency_fraction: float = Field(default=0.0, ge=0, le=1)


class CoatingDeploymentConfig(StrictModel):
    mode: CoatingDeploymentMode = "factory_preinstall"
    area_per_panel_m2: float = Field(default=2.0, gt=0)
    useful_life_years: float = Field(default=3.0, gt=0)
    reapplication_supported: bool = False
    reapplication_interval_years: float | None = Field(default=None, gt=0)
    thermal_treatment_temperature_c: float = Field(default=400.0, gt=0)
    thermal_treatment_duration_minutes: float = Field(default=30.0, gt=0)
    field_application_demonstrated: bool = False

    @model_validator(mode="after")
    def validate_reapplication_interval(self) -> CoatingDeploymentConfig:
        if not self.reapplication_supported and self.reapplication_interval_years is not None:
            raise ValueError(
                "reapplication interval requires a supported replacement or refurbishment pathway"
            )
        if (
            self.reapplication_interval_years is not None
            and self.reapplication_interval_years > self.useful_life_years
        ):
            raise ValueError("reapplication interval cannot exceed useful life")
        if (
            self.reapplication_supported
            and self.mode == "retrofit"
            and not self.field_application_demonstrated
        ):
            raise ValueError("retrofit reapplication requires demonstrated field application")
        if self.mode == "retrofit" and not self.field_application_demonstrated:
            raise ValueError("retrofit deployment requires demonstrated field application")
        return self


class CoatingCostConfig(StrictModel):
    material_loading_g_per_m2: float = Field(default=12.5, gt=0)
    material_cost_per_m2: float = Field(default=15.0, gt=0)
    surface_preparation_cost_per_m2: float = Field(default=2.0, ge=0)
    application_labor_hours_per_m2: float = Field(default=0.03, ge=0)
    process_energy_kwh_per_m2: float = Field(default=0.2, ge=0)
    fixed_equipment_setup_cost: float = Field(default=10000.0, ge=0)
    inspection_hours_per_year: float = Field(default=40.0, ge=0)
    maintenance_cost_per_year: float = Field(default=20000.0, ge=0)
    useful_life_years: float = Field(default=3.0, gt=0)
    reapplication_interval_years: float | None = Field(default=None, gt=0)
    water_collection_infrastructure_cost: float = Field(default=0.0, ge=0)
    assumption_level: AssumptionLevel = "central"
    source_status: SourceStatus = "provisional"

    @model_validator(mode="after")
    def validate_cost_life(self) -> CoatingCostConfig:
        if (
            self.reapplication_interval_years is not None
            and self.reapplication_interval_years > self.useful_life_years
        ):
            raise ValueError("reapplication interval cannot exceed useful life")
        return self


class CoatingConfig(StrictModel):
    enabled: bool = True
    preset: CoatingPresetName = "central"
    physics: CoatingPhysicsConfig = Field(default_factory=CoatingPhysicsConfig)
    water: CoatingWaterConfig = Field(default_factory=CoatingWaterConfig)
    deployment: CoatingDeploymentConfig = Field(default_factory=CoatingDeploymentConfig)
    costs: CoatingCostConfig = Field(default_factory=CoatingCostConfig)

    @model_validator(mode="after")
    def validate_lifecycle_basis(self) -> CoatingConfig:
        if (
            self.deployment.useful_life_years != self.costs.useful_life_years
            or self.deployment.reapplication_interval_years
            != self.costs.reapplication_interval_years
        ):
            raise ValueError("coating lifecycle values must match between deployment and costs")
        if (
            not self.deployment.reapplication_supported
            and self.costs.reapplication_interval_years is not None
        ):
            raise ValueError("coating cost reapplication interval requires deployment support")
        return self


class OutputConfig(StrictModel):
    base_directory: Path = Path("outputs")
    include_cohort_daily_details: bool = True
    csv_float_format: str = "%.10f"


class LoggingConfig(StrictModel):
    level: str = "INFO"


class CalibrationConfig(StrictModel):
    assumption_set: str = "legacy_defaults"
    parameter_registry_path: Path = Path("data/calibration/parameter_registry.yaml")
    source_note: str | None = None


class SolarCleanConfig(StrictModel):
    simulation: SimulationConfig
    site: SiteConfig = Field(default_factory=SiteConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    pv_system: PVSystemConfig = Field(default_factory=PVSystemConfig)
    farm: FarmConfig = Field(default_factory=FarmConfig)
    soiling: SoilingConfig = Field(default_factory=SoilingConfig)
    rainfall_cleaning: RainfallCleaningConfig = Field(default_factory=RainfallCleaningConfig)
    bird_droppings: BirdDroppingConfig = Field(default_factory=BirdDroppingConfig)
    coating: CoatingConfig = Field(default_factory=CoatingConfig)
    reactive_cv: ReactiveCVConfig = Field(default_factory=ReactiveCVConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)

    @model_validator(mode="after")
    def validate_cross_section_consistency(self) -> SolarCleanConfig:
        if self.pv_system.panel_count != self.farm.total_panels:
            raise ValueError("pv_system.panel_count must equal farm.total_panels")
        if self.pv_system.panel_capacity_w != self.farm.panel_capacity_w:
            raise ValueError("pv_system.panel_capacity_w must equal farm.panel_capacity_w")
        if self.coating.preset == "paper_endpoint_calibration":
            day_count = (self.simulation.end.date() - self.simulation.start.date()).days + 1
            endpoint_ratio = 1.0 - self.soiling.base_daily_soiling_loss_fraction * day_count
            if self.soiling.minimum_soiling_ratio > endpoint_ratio:
                raise ValueError("soiling floor clips the paper endpoint calibration")
        return self
