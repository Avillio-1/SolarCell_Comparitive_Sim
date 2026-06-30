from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self

import yaml

from solarclean.config.models import RainfallCleaningConfig, SoilingConfig


@dataclass(frozen=True)
class CalibrationParameter:
    name: str
    configuration_path: str
    category: str
    central_value: float
    low_value: float
    high_value: float
    unit: str
    source: str
    evidence_type: str
    source_geography_and_climate: str
    applicability_to_saudi_conditions: str
    confidence: str
    status: str
    rationale: str
    limitations: str
    responsible_module_or_owner: str

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> Self:
        required = {
            "name",
            "configuration_path",
            "category",
            "central_value",
            "low_value",
            "high_value",
            "unit",
            "source",
            "evidence_type",
            "source_geography_and_climate",
            "applicability_to_saudi_conditions",
            "confidence",
            "status",
            "rationale",
            "limitations",
            "responsible_module_or_owner",
        }
        missing = required.difference(record)
        if missing:
            raise ValueError(f"calibration parameter is missing fields: {sorted(missing)}")
        parameter = cls(
            name=str(record["name"]),
            configuration_path=str(record["configuration_path"]),
            category=str(record["category"]),
            central_value=float(record["central_value"]),
            low_value=float(record["low_value"]),
            high_value=float(record["high_value"]),
            unit=str(record["unit"]),
            source=str(record["source"]),
            evidence_type=str(record["evidence_type"]),
            source_geography_and_climate=str(record["source_geography_and_climate"]),
            applicability_to_saudi_conditions=str(record["applicability_to_saudi_conditions"]),
            confidence=str(record["confidence"]),
            status=str(record["status"]),
            rationale=str(record["rationale"]),
            limitations=str(record["limitations"]),
            responsible_module_or_owner=str(record["responsible_module_or_owner"]),
        )
        parameter.validate()
        return parameter

    def validate(self) -> None:
        if self.evidence_type not in {"measured", "calculated", "inferred", "quoted", "assumed"}:
            raise ValueError(f"invalid evidence_type for {self.name}: {self.evidence_type}")
        if self.confidence not in {"high", "medium", "low"}:
            raise ValueError(f"invalid confidence for {self.name}: {self.confidence}")
        if self.status not in {"validated", "provisional", "blocked", "unsourced"}:
            raise ValueError(f"invalid status for {self.name}: {self.status}")
        if self.low_value > self.central_value or self.central_value > self.high_value:
            raise ValueError(f"low/central/high values are not ordered for {self.name}")
        if not self.name or not self.configuration_path:
            raise ValueError("parameter name and configuration_path are required")

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ParameterRegistry:
    metadata: MappingProxyType[str, object]
    parameters: tuple[CalibrationParameter, ...]

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"parameter registry must contain a mapping: {path}")
        raw_parameters = raw.get("parameters", [])
        if not isinstance(raw_parameters, list):
            raise ValueError("parameter registry 'parameters' must be a list")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("parameter registry 'metadata' must be a mapping")
        parameters = tuple(
            CalibrationParameter.from_record(record)
            for record in raw_parameters
            if isinstance(record, dict)
        )
        if len(parameters) != len(raw_parameters):
            raise ValueError("each parameter record must be a mapping")
        names = [parameter.name for parameter in parameters]
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        return cls(metadata=MappingProxyType(dict(metadata)), parameters=parameters)

    def get(self, name: str) -> CalibrationParameter:
        for parameter in self.parameters:
            if parameter.name == name:
                return parameter
        raise KeyError(f"unknown calibration parameter: {name}")

    def by_category(self, category: str) -> tuple[CalibrationParameter, ...]:
        return tuple(parameter for parameter in self.parameters if parameter.category == category)

    def to_records(self) -> list[dict[str, object]]:
        return [parameter.to_record() for parameter in self.parameters]


@dataclass(frozen=True)
class CalibrationPreset:
    name: str
    label: str
    status: str
    soiling: SoilingConfig
    rainfall: RainfallCleaningConfig
    notes: str

    def to_record(self) -> dict[str, object]:
        record = asdict(self)
        record["soiling"] = self.soiling.model_dump(mode="json")
        record["rainfall"] = self.rainfall.model_dump(mode="json")
        return record


class CalibrationRegistry:
    def __init__(self, presets: tuple[CalibrationPreset, ...]) -> None:
        self._presets = {preset.name: preset for preset in presets}

    @classmethod
    def default(cls) -> CalibrationRegistry:
        return cls(
            (
                CalibrationPreset(
                    name="riyadh_low_soiling",
                    label="Provisional low Riyadh soiling assumption",
                    status="provisional_requires_calibration",
                    soiling=SoilingConfig(
                        base_daily_soiling_loss_fraction=0.0012,
                        dust_event_probability=0.015,
                        dust_event_loss_min_fraction=0.003,
                        dust_event_loss_max_fraction=0.015,
                        minimum_soiling_ratio=0.7,
                        stochastic_std_fraction=0.05,
                        random_seed=42,
                    ),
                    rainfall=RainfallCleaningConfig(
                        partial_rain_threshold_mm=1.0,
                        full_rain_cleaning_threshold_mm=5.0,
                        partial_rain_cleaning_efficiency=0.45,
                        full_rain_cleaning_efficiency=0.95,
                    ),
                    notes=(
                        "Lower-bound engineering assumption awaiting measured Riyadh calibration."
                    ),
                ),
                CalibrationPreset(
                    name="riyadh_medium_soiling",
                    label="Provisional medium Riyadh soiling assumption",
                    status="provisional_requires_calibration",
                    soiling=SoilingConfig(
                        base_daily_soiling_loss_fraction=0.0025,
                        seasonal_multipliers={3: 1.1, 4: 1.15, 5: 1.1},
                        dust_event_probability=0.03,
                        dust_event_loss_min_fraction=0.005,
                        dust_event_loss_max_fraction=0.03,
                        minimum_soiling_ratio=0.55,
                        stochastic_std_fraction=0.1,
                        random_seed=42,
                    ),
                    rainfall=RainfallCleaningConfig(),
                    notes="Default provisional assumption used by configs/riyadh_2025.yaml.",
                ),
                CalibrationPreset(
                    name="riyadh_high_soiling",
                    label="Provisional high Riyadh soiling assumption",
                    status="provisional_requires_calibration",
                    soiling=SoilingConfig(
                        base_daily_soiling_loss_fraction=0.004,
                        seasonal_multipliers={3: 1.2, 4: 1.25, 5: 1.2},
                        dust_event_probability=0.06,
                        dust_event_loss_min_fraction=0.01,
                        dust_event_loss_max_fraction=0.05,
                        minimum_soiling_ratio=0.45,
                        stochastic_std_fraction=0.15,
                        random_seed=42,
                    ),
                    rainfall=RainfallCleaningConfig(
                        partial_rain_threshold_mm=1.5,
                        full_rain_cleaning_threshold_mm=6.0,
                        partial_rain_cleaning_efficiency=0.35,
                        full_rain_cleaning_efficiency=0.9,
                    ),
                    notes="Stress-test assumption, not validated Saudi field calibration.",
                ),
            )
        )

    def get(self, name: str) -> CalibrationPreset:
        try:
            return self._presets[name]
        except KeyError as exc:
            raise KeyError(f"unknown calibration preset: {name}") from exc

    def to_records(self) -> list[dict[str, object]]:
        return [preset.to_record() for preset in self._presets.values()]
