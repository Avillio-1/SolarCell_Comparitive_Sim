from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class WeatherValidationReport:
    row_count: int
    expected_row_count: int
    start_timestamp: str
    end_timestamp: str
    timezone: str
    gap_count: int
    duplicate_count: int
    canonical_units: dict[str, str]
    ranges: dict[str, dict[str, float]]
    suspicious_value_count: int
    metadata_keys: list[str]
    checksum_sha256: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EnergyValidationReport:
    annual_clean_energy_kwh: float
    annual_actual_energy_kwh: float
    annual_soiling_loss_kwh: float
    annual_soiling_loss_percent: float
    monthly_clean_energy_kwh: dict[str, float]
    monthly_actual_energy_kwh: dict[str, float]
    specific_yield_kwh_per_kwp: float
    capacity_factor_percent: float
    clipping_energy_kwh: float
    clipping_percent_of_dc_energy: float
    contamination_event_count: int
    rain_event_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FarmEquivalenceReport:
    representative_energy_kwh: float
    cohort_energy_kwh: float
    absolute_difference_kwh: float
    tolerance_kwh: float
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PerformanceReport:
    runtime_seconds: float
    peak_memory_mb: float
    output_size_mb: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
