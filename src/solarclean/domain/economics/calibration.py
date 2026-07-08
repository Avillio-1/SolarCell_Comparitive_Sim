from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from solarclean.domain.calibration.registry import CalibrationParameter, ParameterRegistry
from solarclean.domain.economics.adapters import ReactiveCostRates, UnitCostRate
from solarclean.domain.economics.contracts import CostComponent, EconomicConfig

RegistryStatusPolicy = Literal["allow_blocked_with_warnings", "require_validated"]

_TARIFF_KEY = "economics.electricity_tariff_sar_per_kwh"
_LABOUR_KEY = "economics.labour_cost_sar_per_hour"
_WATER_KEY = "economics.water_cost_sar_per_m3"
_DRONE_EQUIPMENT_KEY = "economics.drone_equipment_cost_sar"
_DRONE_FLIGHT_HOUR_KEY = "economics.drone_flight_operation_cost_sar_per_hour"
_REACTIVE_OVERHEAD_OPEX_KEY = "economics.reactive_overhead_opex_sar_per_year"
_DISCOUNT_RATE_KEY = "economics.discount_rate_fraction"
_USEFUL_LIFE_KEY = "economics.useful_life_years"

_REQUIRED_PARAMETER_KEYS = (
    _TARIFF_KEY,
    _LABOUR_KEY,
    _WATER_KEY,
    _DRONE_EQUIPMENT_KEY,
    _DRONE_FLIGHT_HOUR_KEY,
    _REACTIVE_OVERHEAD_OPEX_KEY,
    _DISCOUNT_RATE_KEY,
    _USEFUL_LIFE_KEY,
)

# Public alias: the T5 registry parameter names that build_economics_from_parameter_registry
# reads directly by name (not via configuration_path). T7 sensitivity sweeps use this to know
# which registry entries can be perturbed purely by rebuilding EconomicsCalibration from a
# mutated ParameterRegistry, with no SolarCleanConfig change required.
REQUIRED_ECONOMICS_PARAMETER_KEYS = _REQUIRED_PARAMETER_KEYS


@dataclass(frozen=True)
class RegistryParameterMetadata:
    """Trace metadata copied from a T5 calibration parameter."""

    registry_key: str
    configuration_path: str
    unit: str
    source: str
    status: str
    confidence: str
    evidence_type: str


@dataclass(frozen=True)
class EconomicsCalibrationWarning:
    """Non-fatal registry status issue surfaced by permissive mapping."""

    registry_key: str
    status: str
    message: str


@dataclass(frozen=True)
class EconomicsCalibration:
    """T4 runtime economics objects built from the T5 parameter registry."""

    config: EconomicConfig
    reactive_cost_rates: ReactiveCostRates
    equipment_cost_components: tuple[CostComponent, ...]
    warnings: tuple[EconomicsCalibrationWarning, ...]
    parameter_metadata: tuple[RegistryParameterMetadata, ...]


def build_economics_from_parameter_registry(
    registry: ParameterRegistry,
    *,
    status_policy: RegistryStatusPolicy = "allow_blocked_with_warnings",
) -> EconomicsCalibration:
    """Map T5 economics calibration records into T4 runtime economics objects."""

    _validate_status_policy(status_policy)
    parameters = _required_parameters(registry)
    status_warnings = _apply_status_policy(parameters.values(), status_policy)

    config = EconomicConfig(
        tariff_sar_per_kwh=_central_value(parameters[_TARIFF_KEY], expected_unit="SAR/kWh"),
        discount_rate=_central_value(parameters[_DISCOUNT_RATE_KEY], expected_unit="fraction/year"),
        useful_life_years=_useful_life_years(parameters[_USEFUL_LIFE_KEY]),
    )
    rates = ReactiveCostRates(
        crew_hour=_unit_rate(
            parameters[_LABOUR_KEY],
            expected_unit="SAR/worker_hour",
            quantity_unit="hour",
        ),
        water_liter=_water_liter_rate(parameters[_WATER_KEY]),
        drone_flight_hour=_unit_rate(
            parameters[_DRONE_FLIGHT_HOUR_KEY],
            expected_unit="SAR/drone_hour",
            quantity_unit="drone_flight_hour",
        ),
        energy_kwh=_unit_rate(
            parameters[_TARIFF_KEY],
            expected_unit="SAR/kWh",
            quantity_unit="kWh",
        ),
    )
    equipment_components = (
        _drone_equipment_capex_component(parameters[_DRONE_EQUIPMENT_KEY]),
        _reactive_overhead_opex_component(parameters[_REACTIVE_OVERHEAD_OPEX_KEY]),
    )

    return EconomicsCalibration(
        config=config,
        reactive_cost_rates=rates,
        equipment_cost_components=equipment_components,
        warnings=status_warnings,
        parameter_metadata=tuple(
            _parameter_metadata(parameters[key]) for key in _REQUIRED_PARAMETER_KEYS
        ),
    )


def _required_parameters(registry: ParameterRegistry) -> dict[str, CalibrationParameter]:
    parameters: dict[str, CalibrationParameter] = {}
    missing: list[str] = []

    for key in _REQUIRED_PARAMETER_KEYS:
        try:
            parameters[key] = registry.get(key)
        except KeyError:
            missing.append(key)

    if missing:
        raise ValueError(
            "missing required economics calibration parameter(s): " + ", ".join(missing)
        )

    return parameters


def _validate_status_policy(status_policy: RegistryStatusPolicy) -> None:
    if status_policy not in {"allow_blocked_with_warnings", "require_validated"}:
        raise ValueError(f"unknown registry status policy: {status_policy}")


def _apply_status_policy(
    parameters: Iterable[CalibrationParameter],
    status_policy: RegistryStatusPolicy,
) -> tuple[EconomicsCalibrationWarning, ...]:
    parameter_tuple = tuple(parameters)
    non_validated = tuple(
        parameter for parameter in parameter_tuple if parameter.status != "validated"
    )

    if status_policy == "require_validated":
        if non_validated:
            issues = ", ".join(
                f"{parameter.name} (status={parameter.status})" for parameter in non_validated
            )
            raise ValueError(
                "require_validated rejected non-validated economics calibration "
                f"parameter(s): {issues}"
            )
        return ()

    return tuple(
        EconomicsCalibrationWarning(
            registry_key=parameter.name,
            status=parameter.status,
            message=(
                f"{parameter.name} has status {parameter.status}; "
                "allow_blocked_with_warnings permits use for research/sensitivity only."
            ),
        )
        for parameter in non_validated
    )


def _central_value(parameter: CalibrationParameter, *, expected_unit: str) -> float:
    _require_unit(parameter, expected_unit)
    return parameter.central_value


def _useful_life_years(parameter: CalibrationParameter) -> int:
    _require_unit(parameter, "years")
    if not parameter.central_value.is_integer():
        raise ValueError(
            f"{parameter.name} central value must be a whole number of years: "
            f"{parameter.central_value:g}"
        )
    return int(parameter.central_value)


def _unit_rate(
    parameter: CalibrationParameter,
    *,
    expected_unit: str,
    quantity_unit: str,
) -> UnitCostRate:
    _require_unit(parameter, expected_unit)
    return UnitCostRate(
        amount_sar_per_unit=parameter.central_value,
        quantity_unit=quantity_unit,
        source=parameter.source,
        source_status=parameter.status,
        notes=_metadata_notes(parameter),
    )


def _water_liter_rate(parameter: CalibrationParameter) -> UnitCostRate:
    _require_unit(parameter, "SAR/m3")
    return UnitCostRate(
        amount_sar_per_unit=parameter.central_value / 1000.0,
        quantity_unit="liter",
        source=parameter.source,
        source_status=parameter.status,
        notes=_metadata_notes(parameter, conversion="1 m3 = 1000 liters"),
    )


def _drone_equipment_capex_component(parameter: CalibrationParameter) -> CostComponent:
    _require_unit(parameter, "SAR")
    return CostComponent(
        name="drone equipment capex",
        category="capex",
        amount_sar=parameter.central_value,
        unit="SAR",
        source=parameter.source,
        source_status=parameter.status,
        notes=_metadata_notes(
            parameter,
            extra=(
                "mapped as a capex component, not a flight-hour rate; "
                "the registry value is a total equipment cost"
            ),
        ),
    )


def _reactive_overhead_opex_component(parameter: CalibrationParameter) -> CostComponent:
    _require_unit(parameter, "SAR/year")
    return CostComponent(
        name="reactive annual overhead opex",
        category="opex",
        amount_sar=parameter.central_value,
        unit="SAR/year",
        source=parameter.source,
        source_status=parameter.status,
        notes=_metadata_notes(
            parameter,
            extra=(
                "explicit annual OPEX target for supervision, software, maintenance, "
                "insurance, spares, and mobilization not captured by variable rates"
            ),
        ),
    )


def _require_unit(parameter: CalibrationParameter, expected_unit: str) -> None:
    if parameter.unit != expected_unit:
        raise ValueError(
            f"{parameter.name} uses unit {parameter.unit!r}; expected {expected_unit!r}."
        )


def _metadata_notes(
    parameter: CalibrationParameter,
    *,
    conversion: str | None = None,
    extra: str | None = None,
) -> str:
    parts = [
        f"registry_key={parameter.name}",
        f"configuration_path={parameter.configuration_path}",
        f"registry_unit={parameter.unit}",
        f"evidence_type={parameter.evidence_type}",
        f"confidence={parameter.confidence}",
    ]
    if conversion is not None:
        parts.append(f"conversion={conversion}")
    if extra is not None:
        parts.append(extra)
    return "; ".join(parts)


def _parameter_metadata(parameter: CalibrationParameter) -> RegistryParameterMetadata:
    return RegistryParameterMetadata(
        registry_key=parameter.name,
        configuration_path=parameter.configuration_path,
        unit=parameter.unit,
        source=parameter.source,
        status=parameter.status,
        confidence=parameter.confidence,
        evidence_type=parameter.evidence_type,
    )
