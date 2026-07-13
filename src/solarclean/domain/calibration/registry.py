from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self

import yaml

from solarclean.config.models import RainfallCleaningConfig, SoilingConfig

VALIDATION_DISCLAIMER = (
    "Internally verified simulation calibrated to literature and provisional assumptions; "
    "absolute energy, cost, and ROI outputs have not been validated against measured "
    "production data from an operating site."
)


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
        if self.evidence_type not in {
            "measured",
            "calculated",
            "inferred",
            "quoted",
            "assumed",
            "literature",
        }:
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

    def checksum(self) -> str:
        payload = {
            "metadata": dict(self.metadata),
            "parameters": self.to_records(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def with_central_value(self, name: str, value: float) -> Self:
        """Return a copy of this registry with one parameter's central_value replaced.

        Used by T7 sensitivity/break-even sweeps to perturb a single economics
        parameter (e.g. ``economics.electricity_tariff_sar_per_kwh``) without
        mutating the on-disk registry. The replacement value must stay within the
        parameter's own [low_value, high_value] band — sweeps are only meaningful
        within the T5-sourced uncertainty range, and CalibrationParameter.validate()
        enforces this ordering the same way it does when loading from YAML.
        """
        existing = self.get(name)
        updated = replace(existing, central_value=float(value))
        updated.validate()
        parameters = tuple(
            updated if parameter.name == name else parameter for parameter in self.parameters
        )
        return type(self)(metadata=self.metadata, parameters=parameters)


def build_validation_status(registry: ParameterRegistry) -> dict[str, object]:
    """Summarize the evidence quality of every parameter in a registry."""

    status_counts: dict[str, int] = {}
    evidence_counts: dict[str, int] = {}
    confidence_rank = {"high": 2, "medium": 1, "low": 0}
    lowest_confidence: str | None = None
    uncertain_parameters: list[tuple[float, CalibrationParameter]] = []

    for parameter in registry.parameters:
        status_counts[parameter.status] = status_counts.get(parameter.status, 0) + 1
        evidence_counts[parameter.evidence_type] = (
            evidence_counts.get(parameter.evidence_type, 0) + 1
        )
        if (
            lowest_confidence is None
            or confidence_rank[parameter.confidence] < confidence_rank[lowest_confidence]
        ):
            lowest_confidence = parameter.confidence
        if parameter.central_value != 0:
            relative_range = (parameter.high_value - parameter.low_value) / abs(
                parameter.central_value
            )
            uncertain_parameters.append((relative_range, parameter))

    uncertain_parameters.sort(key=lambda item: (-item[0], item[1].name))
    key_uncertain_parameters = [
        {
            "name": parameter.name,
            "central_value": parameter.central_value,
            "low_value": parameter.low_value,
            "high_value": parameter.high_value,
            "confidence": parameter.confidence,
            "status": parameter.status,
        }
        for _, parameter in uncertain_parameters[:5]
    ]
    return {
        # This must remain false until the validate-field harness is run against measured
        # production from an operating site and establishes an accepted validation result.
        "absolute_outputs_field_validated": False,
        "parameter_counts_by_status": status_counts,
        "parameter_counts_by_evidence_type": evidence_counts,
        "lowest_confidence": lowest_confidence,
        "key_uncertain_parameters": key_uncertain_parameters,
        "disclaimer": VALIDATION_DISCLAIMER,
    }


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
                        base_daily_soiling_loss_fraction=0.0005,
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
                        base_daily_soiling_loss_fraction=0.001,
                        seasonal_multipliers={3: 1.1, 4: 1.15, 5: 1.1},
                        dust_event_probability=0.03,
                        dust_event_loss_min_fraction=0.005,
                        dust_event_loss_max_fraction=0.03,
                        minimum_soiling_ratio=0.55,
                        stochastic_std_fraction=0.1,
                        random_seed=42,
                    ),
                    rainfall=RainfallCleaningConfig(),
                    notes="Central-v2 provisional assumption used by T6 corrected comparison.",
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
