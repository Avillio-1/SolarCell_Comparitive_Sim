from __future__ import annotations

from pathlib import Path

import pytest
from tests.config_factory import config_from_default

from solarclean.domain.calibration.parameter_overrides import (
    apply_config_override,
    apply_economics_override,
    build_parameter_catalog,
)
from solarclean.domain.calibration.registry import ParameterRegistry
from solarclean.domain.economics import build_economics_from_parameter_registry

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "data" / "calibration" / "parameter_registry.yaml"


@pytest.fixture(scope="module")
def registry() -> ParameterRegistry:
    return ParameterRegistry.from_yaml(REGISTRY_PATH)


@pytest.fixture(scope="module")
def base_config():
    return config_from_default()


def test_catalog_accounts_for_every_registry_parameter_exactly_once(registry) -> None:
    supported, unsupported = build_parameter_catalog(registry)
    supported_names = {spec.name for spec in supported}
    unsupported_names = {entry.name for entry in unsupported}

    assert not supported_names & unsupported_names, "a parameter cannot be both supported and not"
    assert len(supported_names) == len(supported), "duplicate supported parameter name"
    assert len(unsupported_names) == len(unsupported), "duplicate unsupported parameter name"
    all_registry_names = {parameter.name for parameter in registry.parameters}
    assert supported_names | unsupported_names == all_registry_names


def test_supported_ranges_are_read_live_from_the_registry(registry) -> None:
    supported, _ = build_parameter_catalog(registry)
    by_name = {spec.name: spec for spec in supported}
    reference = registry.get("soiling.base_daily_loss_fraction")
    spec = by_name["soiling.base_daily_loss_fraction"]
    assert spec.low_value == reference.low_value
    assert spec.central_value == reference.central_value
    assert spec.high_value == reference.high_value


def test_every_supported_config_override_applies_without_validation_error(
    registry, base_config
) -> None:
    supported, _ = build_parameter_catalog(registry)
    for spec in supported:
        for value in (spec.low_value, spec.central_value, spec.high_value):
            if spec.kind == "config":
                apply_config_override(base_config, spec, value)
            else:
                new_registry = apply_economics_override(registry, spec, value)
                build_economics_from_parameter_registry(new_registry)


def test_config_override_does_not_mutate_the_base_config(registry, base_config) -> None:
    supported, _ = build_parameter_catalog(registry)
    spec = next(s for s in supported if s.name == "coating.useful_life_years")
    original = base_config.coating.costs.useful_life_years
    apply_config_override(base_config, spec, spec.high_value)
    assert base_config.coating.costs.useful_life_years == original


def test_coating_useful_life_years_override_stays_synchronized(registry, base_config) -> None:
    # CoatingConfig.validate_lifecycle_basis requires deployment.useful_life_years to equal
    # costs.useful_life_years; the override must update both together or model construction
    # raises a ValidationError (this is exactly what apply_config_override is being smoke
    # tested against in test_every_supported_config_override_applies_without_validation_error,
    # but this test pins the actual reason it would otherwise fail).
    supported, _ = build_parameter_catalog(registry)
    spec = next(s for s in supported if s.name == "coating.useful_life_years")
    new_config = apply_config_override(base_config, spec, 5.5)
    assert new_config.coating.costs.useful_life_years == 5.5
    assert new_config.coating.deployment.useful_life_years == 5.5


def test_optical_penalty_fraction_uses_inverse_transform(registry, base_config) -> None:
    supported, _ = build_parameter_catalog(registry)
    spec = next(s for s in supported if s.name == "coating.optical_penalty_fraction")
    new_config = apply_config_override(base_config, spec, 0.02)
    assert new_config.coating.physics.optical_transmittance_multiplier == pytest.approx(0.98)


def test_economics_override_does_not_mutate_base_registry(registry) -> None:
    supported, _ = build_parameter_catalog(registry)
    spec = next(s for s in supported if s.name == "economics.electricity_tariff_sar_per_kwh")
    original = registry.get(spec.name).central_value
    apply_economics_override(registry, spec, spec.high_value)
    assert registry.get(spec.name).central_value == original


def test_apply_config_override_rejects_economics_kind_spec(registry, base_config) -> None:
    supported, _ = build_parameter_catalog(registry)
    spec = next(s for s in supported if s.kind == "economics")
    with pytest.raises(ValueError, match="not a config-kind"):
        apply_config_override(base_config, spec, spec.central_value)


def test_apply_economics_override_rejects_config_kind_spec(registry) -> None:
    supported, _ = build_parameter_catalog(registry)
    spec = next(s for s in supported if s.kind == "config")
    with pytest.raises(ValueError, match="not an economics-kind"):
        apply_economics_override(registry, spec, spec.central_value)


def test_registry_with_central_value_out_of_bounds_raises(registry) -> None:
    spec_name = "soiling.base_daily_loss_fraction"
    parameter = registry.get(spec_name)
    with pytest.raises(ValueError):
        registry.with_central_value(spec_name, parameter.high_value + 1.0)
