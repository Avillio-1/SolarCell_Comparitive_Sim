from __future__ import annotations

import pandas as pd
import pvlib
import pytest
from tests.unit.test_weather import _request

from solarclean.config.models import PVSystemConfig
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider

LOSS_FIELD_NAMES = (
    "loss_wiring_fraction",
    "loss_mismatch_fraction",
    "loss_connections_fraction",
    "loss_nameplate_fraction",
    "loss_lid_fraction",
    "loss_availability_fraction",
)


def _zero_loss_system(**overrides: object) -> PVSystemConfig:
    values: dict[str, object] = {name: 0.0 for name in LOSS_FIELD_NAMES}
    values.update(overrides)
    return PVSystemConfig.model_validate(values)


def test_default_combined_system_loss_multiplier_is_product_of_components() -> None:
    system = PVSystemConfig()

    expected = 0.98 * 0.98 * 0.995 * 0.99 * 0.985 * 0.97

    assert system.combined_system_loss_multiplier == pytest.approx(expected)


def test_zero_losses_reproduce_raw_pvwatts_dc_power_exactly() -> None:
    weather = FixtureWeatherProvider().load(_request())
    system = _zero_loss_system()

    profile = PVWattsPowerModel().calculate_hourly(weather, system)
    raw_dc = pvlib.pvsystem.pvwatts_dc(
        effective_irradiance=profile.hourly["poa_global_w_m2"],
        temp_cell=profile.hourly["cell_temperature_c"],
        pdc0=system.total_dc_capacity_w,
        gamma_pdc=system.gamma_pdc_per_c,
    )
    expected = pd.Series(raw_dc, index=profile.hourly.index).clip(lower=0.0).fillna(0.0)

    pd.testing.assert_series_equal(profile.hourly["clean_dc_power_w"], expected, check_names=False)


def test_system_losses_reduce_dc_before_inverter_clipping() -> None:
    weather = FixtureWeatherProvider().load(_request())
    zero_loss = _zero_loss_system(dc_ac_ratio=1.5)
    lossy = PVSystemConfig(dc_ac_ratio=1.5)

    previous = PVWattsPowerModel().calculate_hourly(weather, zero_loss)
    with_losses = PVWattsPowerModel().calculate_hourly(weather, lossy)
    expected_lossy_dc = previous.hourly["clean_dc_power_w"] * lossy.combined_system_loss_multiplier

    pd.testing.assert_series_equal(
        with_losses.hourly["clean_dc_power_w"], expected_lossy_dc, check_names=False
    )
    assert (
        with_losses.hourly["clean_ac_power_w"] <= previous.hourly["clean_ac_power_w"] + 1e-9
    ).all()
    assert (with_losses.hourly["clean_ac_power_w"] < previous.hourly["clean_ac_power_w"]).any()
