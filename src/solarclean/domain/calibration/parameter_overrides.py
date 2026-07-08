"""T7 sensitivity/break-even override catalog.

The T5 parameter registry (``data/calibration/parameter_registry.yaml``) documents a
``configuration_path`` for every calibration parameter, but that string is *not* always a
literal, resolvable attribute path on ``SolarCleanConfig`` today:

- Several paths point at interface placeholders the registry's own metadata calls out as
  "documented as interface requests until their modules publish strict config models"
  (e.g. ``calibration.central_v2_targets.*``, ``reactive_cv.operations.*``,
  ``reactive_cv.cleaning.*``). These have no backing field at all.
- One path is a composite expression (``coating.costs.material_cost_per_m2 +
  coating.costs.surface_preparation_cost_per_m2``), not a single settable field.
- The ``economics.*`` entries are not ``SolarCleanConfig`` paths at all -- they are consumed
  directly by name inside ``build_economics_from_parameter_registry``.
- One documented path has a stale namespace typo (``coating.performance.annual_degradation_
  fraction`` -- there is no ``performance`` section; the real field is
  ``coating.physics.annual_degradation_fraction``, confirmed by an exact default-value match).

Blindly walking ``configuration_path`` strings with a generic setter would silently apply wrong
overrides (or crash) for any of the above. Instead this module hand-maps every registry
parameter it supports to a verified, single, real field -- cross-checked against
``solarclean.config.models`` field names and current defaults -- and explicitly reports every
registry entry it does *not* support so sensitivity runs never silently skip or misapply a
parameter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from solarclean.config.models import SolarCleanConfig
from solarclean.domain.calibration.registry import CalibrationParameter, ParameterRegistry
from solarclean.domain.economics import REQUIRED_ECONOMICS_PARAMETER_KEYS

OverrideKind = Literal["config", "economics"]

ConfigApplyFn = Callable[[SolarCleanConfig, float], SolarCleanConfig]


@dataclass(frozen=True)
class ParameterOverrideSpec:
    """A registry parameter that T7 knows how to safely perturb."""

    name: str
    kind: OverrideKind
    configuration_path: str
    category: str
    low_value: float
    central_value: float
    high_value: float
    unit: str
    status: str
    confidence: str
    notes: str = ""

    def clamp(self, value: float) -> float:
        return min(max(value, self.low_value), self.high_value)


@dataclass(frozen=True)
class UnsupportedParameter:
    """A registry parameter T7 deliberately excludes, with the reason why."""

    name: str
    configuration_path: str
    reason: str


def _set_coating_useful_life_years(config: SolarCleanConfig, value: float) -> SolarCleanConfig:
    # CoatingConfig.validate_lifecycle_basis requires deployment.useful_life_years ==
    # costs.useful_life_years, so both must be updated together or the model raises.
    new_costs = config.coating.costs.model_copy(update={"useful_life_years": value})
    new_deployment = config.coating.deployment.model_copy(update={"useful_life_years": value})
    new_coating = config.coating.model_copy(
        update={"costs": new_costs, "deployment": new_deployment}
    )
    return config.model_copy(update={"coating": new_coating})


def _set_optical_penalty_fraction(config: SolarCleanConfig, value: float) -> SolarCleanConfig:
    # The registry documents this as a "penalty fraction" (0.0 = no penalty) but the real field
    # is a transmittance *multiplier* (1.0 = no penalty). multiplier = 1 - penalty is the only
    # transform consistent with both the field's own default (1.0) and the registry's central
    # value (0.0): 1 - 0.0 == 1.0.
    multiplier = 1.0 - value
    new_physics = config.coating.physics.model_copy(
        update={"optical_transmittance_multiplier": multiplier}
    )
    new_coating = config.coating.model_copy(update={"physics": new_physics})
    return config.model_copy(update={"coating": new_coating})


def _seasonal_multiplier_setter(month: int) -> ConfigApplyFn:
    def _apply(config: SolarCleanConfig, value: float) -> SolarCleanConfig:
        multipliers = dict(config.soiling.seasonal_multipliers)
        multipliers[month] = value
        new_soiling = config.soiling.model_copy(update={"seasonal_multipliers": multipliers})
        return config.model_copy(update={"soiling": new_soiling})

    return _apply


def _simple_setter(*, section: str, field: str) -> ConfigApplyFn:
    def _apply(config: SolarCleanConfig, value: float) -> SolarCleanConfig:
        section_obj = getattr(config, section)
        new_section = section_obj.model_copy(update={field: value})
        return config.model_copy(update={section: new_section})

    return _apply


def _nested_setter(*, section: str, subsection: str, field: str) -> ConfigApplyFn:
    def _apply(config: SolarCleanConfig, value: float) -> SolarCleanConfig:
        section_obj = getattr(config, section)
        subsection_obj = getattr(section_obj, subsection)
        new_subsection = subsection_obj.model_copy(update={field: value})
        new_section = section_obj.model_copy(update={subsection: new_subsection})
        return config.model_copy(update={section: new_section})

    return _apply


# Verified against src/solarclean/config/models.py field-by-field (see module docstring).
# Every entry here was checked to resolve to a real, single pydantic field whose current
# default matches (or is a documented, deliberate transform of) the registry's central_value.
_CONFIG_OVERRIDES: dict[str, ConfigApplyFn] = {
    "soiling.base_daily_loss_fraction": _simple_setter(
        section="soiling", field="base_daily_soiling_loss_fraction"
    ),
    "soiling.minimum_soiling_ratio": _simple_setter(
        section="soiling", field="minimum_soiling_ratio"
    ),
    "soiling.stochastic_std_fraction": _simple_setter(
        section="soiling", field="stochastic_std_fraction"
    ),
    "seasonality.march_multiplier": _seasonal_multiplier_setter(3),
    "seasonality.april_multiplier": _seasonal_multiplier_setter(4),
    "seasonality.may_multiplier": _seasonal_multiplier_setter(5),
    "dust_events.daily_probability": _simple_setter(
        section="soiling", field="dust_event_probability"
    ),
    "dust_events.loss_min_fraction": _simple_setter(
        section="soiling", field="dust_event_loss_min_fraction"
    ),
    "dust_events.loss_max_fraction": _simple_setter(
        section="soiling", field="dust_event_loss_max_fraction"
    ),
    "rainfall.partial_threshold_mm": _simple_setter(
        section="rainfall_cleaning", field="partial_rain_threshold_mm"
    ),
    "rainfall.full_threshold_mm": _simple_setter(
        section="rainfall_cleaning", field="full_rain_cleaning_threshold_mm"
    ),
    "rainfall.partial_efficiency": _simple_setter(
        section="rainfall_cleaning", field="partial_rain_cleaning_efficiency"
    ),
    "rainfall.full_efficiency": _simple_setter(
        section="rainfall_cleaning", field="full_rain_cleaning_efficiency"
    ),
    "bird.event_probability_per_cohort_day": _simple_setter(
        section="bird_droppings", field="event_probability_per_cohort_day"
    ),
    "bird.coverage_min_fraction": _simple_setter(
        section="bird_droppings", field="coverage_min_fraction"
    ),
    "bird.coverage_max_fraction": _simple_setter(
        section="bird_droppings", field="coverage_max_fraction"
    ),
    "bird.loss_per_coverage_fraction": _simple_setter(
        section="bird_droppings", field="loss_per_coverage_fraction"
    ),
    "bird.rain_removal_efficiency": _simple_setter(
        section="bird_droppings", field="rain_removal_efficiency"
    ),
    "cv.true_positive_rate": _nested_setter(
        section="reactive_cv", subsection="observer", field="recall_fraction"
    ),
    "cv.false_positive_rate": _nested_setter(
        section="reactive_cv", subsection="observer", field="false_positive_rate"
    ),
    "inspection.drone_flight_duration_minutes": _nested_setter(
        section="reactive_cv", subsection="drone", field="flight_duration_minutes"
    ),
    "cleaning.trigger_loss_fraction": _nested_setter(
        section="reactive_cv", subsection="dispatch", field="estimated_loss_threshold_fraction"
    ),
    "coating.dust_accumulation_multiplier": _nested_setter(
        section="coating", subsection="physics", field="dust_accumulation_multiplier"
    ),
    # Registry documents "coating.performance.annual_degradation_fraction", which does not
    # exist (CoatingConfig has no `performance` section). The real field is
    # coating.physics.annual_degradation_fraction; its default (0.05) exactly matches the
    # registry's central_value (0.05), confirming this is the intended parameter.
    "coating.annual_degradation_fraction": _nested_setter(
        section="coating", subsection="physics", field="annual_degradation_fraction"
    ),
    "coating.annual_opex_reserve_sar_per_year": _nested_setter(
        section="coating", subsection="costs", field="maintenance_cost_per_year"
    ),
    "coating.useful_life_years": _set_coating_useful_life_years,
    "coating.optical_penalty_fraction": _set_optical_penalty_fraction,
}

# Registry names read directly by build_economics_from_parameter_registry -- overriding these
# means mutating the ParameterRegistry's central_value and rebuilding EconomicsCalibration,
# never touching SolarCleanConfig.
_ECONOMICS_OVERRIDES: frozenset[str] = frozenset(REQUIRED_ECONOMICS_PARAMETER_KEYS)

_UNSUPPORTED_REASONS: dict[str, str] = {
    "soiling.no_clean_annual_loss_target_fraction": (
        "configuration_path is an unimplemented calibration.central_v2_targets placeholder"
    ),
    "bird.persistence_days_without_rain": (
        "BirdDroppingConfig has no persistence_days_without_rain field (status: blocked)"
    ),
    "inspection.whole_farm_surveys_per_year": (
        "configuration_path (reactive_cv.inspection.interval_days) is a unit mismatch, not a "
        "direct override target; status: blocked"
    ),
    "inspection.battery_sets_per_drone": (
        "configuration_path (reactive_cv.operations.*) is an unimplemented interface request"
    ),
    "cleaning.panels_per_worker_hour": (
        "configuration_path (reactive_cv.cleaning.*) is an unimplemented interface request"
    ),
    "cleaning.water_liters_per_panel": (
        "configuration_path (reactive_cv.cleaning.*) is an unimplemented interface request"
    ),
    "cleaning.labour_hours_per_action": (
        "configuration_path (reactive_cv.cleaning.*) is an unimplemented interface request"
    ),
    "coating.capex_sar_per_m2": (
        "configuration_path is a composite expression (two fields summed), not a single "
        "settable field"
    ),
    "coating.installed_capex_sar": (
        "configuration_path is an unimplemented calibration.central_v2_targets placeholder"
    ),
    "coating.residual_annual_loss_target_fraction": (
        "configuration_path is an unimplemented calibration.central_v2_targets placeholder"
    ),
    "coating.dust_adhesion_reduction_fraction": (
        "configuration_path is an unimplemented calibration.central_v2_targets placeholder"
    ),
    "coating.cell_temperature_reduction_c": (
        "configuration_path (coating.performance.*) does not exist on CoatingConfig"
    ),
    "coating.dew_soiling_multiplier": (
        "configuration_path (coating.performance.*) does not exist on CoatingConfig"
    ),
    "coating.optical_relative_energy_effect_fraction": (
        "configuration_path is an unimplemented calibration.central_v2_targets placeholder"
    ),
    "coating.water_collection_l_per_m2_day": (
        "configuration_path (coating.performance.*) does not exist on CoatingConfig"
    ),
    "cv.false_negative_rate": (
        "same underlying field as cv.true_positive_rate (recall_fraction) -- overriding both "
        "in the same sweep would be contradictory, so only true_positive_rate is exposed"
    ),
    "cv.severity_mae_fraction": (
        "configuration_path (reactive_cv.observer.severity_error_std_fraction) is a std-dev "
        "proxy for a documented MAE parameter, not the same statistic -- excluded to avoid "
        "misrepresenting the override"
    ),
}


def build_parameter_catalog(
    registry: ParameterRegistry,
) -> tuple[tuple[ParameterOverrideSpec, ...], tuple[UnsupportedParameter, ...]]:
    """Split the T5 registry into T7-sweepable parameters and explicitly excluded ones.

    Ranges (low/central/high) are always read live from the given registry, so calibration
    updates automatically flow through to sensitivity sweeps. Only the *mapping* from
    registry name to config/economics override is fixed in this module.
    """
    supported: list[ParameterOverrideSpec] = []
    unsupported: list[UnsupportedParameter] = []
    for parameter in registry.parameters:
        kind = _override_kind(parameter.name)
        if kind is None:
            reason = _UNSUPPORTED_REASONS.get(
                parameter.name,
                "no verified override mapping for this configuration_path",
            )
            unsupported.append(
                UnsupportedParameter(
                    name=parameter.name,
                    configuration_path=parameter.configuration_path,
                    reason=reason,
                )
            )
            continue
        supported.append(
            ParameterOverrideSpec(
                name=parameter.name,
                kind=kind,
                configuration_path=parameter.configuration_path,
                category=parameter.category,
                low_value=parameter.low_value,
                central_value=parameter.central_value,
                high_value=parameter.high_value,
                unit=parameter.unit,
                status=parameter.status,
                confidence=parameter.confidence,
            )
        )
    return tuple(supported), tuple(unsupported)


def _override_kind(name: str) -> OverrideKind | None:
    if name in _ECONOMICS_OVERRIDES:
        return "economics"
    if name in _CONFIG_OVERRIDES:
        return "config"
    return None


def apply_config_override(
    config: SolarCleanConfig, spec: ParameterOverrideSpec, value: float
) -> SolarCleanConfig:
    if spec.kind != "config":
        raise ValueError(f"{spec.name} is not a config-kind override (kind={spec.kind})")
    return _CONFIG_OVERRIDES[spec.name](config, value)


def apply_economics_override(
    registry: ParameterRegistry, spec: ParameterOverrideSpec, value: float
) -> ParameterRegistry:
    if spec.kind != "economics":
        raise ValueError(f"{spec.name} is not an economics-kind override (kind={spec.kind})")
    return registry.with_central_value(spec.name, value)


def get_registry_parameter(registry: ParameterRegistry, name: str) -> CalibrationParameter:
    return registry.get(name)
