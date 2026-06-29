from __future__ import annotations

import pandas as pd
import pytest
from tests.unit.test_weather import _canonical_frame, _request

from solarclean.config.models import PVSystemConfig
from solarclean.domain.environment.weather import WeatherDataset
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider


def test_night_power_is_zero() -> None:
    index = pd.date_range("2025-01-01", periods=3, freq="h", tz="Asia/Riyadh")
    dataset = WeatherDataset(hourly=_canonical_frame(index), metadata={"provider": "test"})
    system = PVSystemConfig(panel_count=1, panel_capacity_w=400)

    profile = PVWattsPowerModel().calculate_hourly(dataset, system)

    assert (profile.hourly["clean_ac_power_w"] == 0).all()
    assert (profile.hourly["clean_dc_power_w"] == 0).all()


def test_clean_energy_is_non_negative_and_positive_for_fixture() -> None:
    dataset = FixtureWeatherProvider().load(_request())
    system = PVSystemConfig(panel_count=10000, panel_capacity_w=400)

    profile = PVWattsPowerModel().calculate_hourly(dataset, system)

    assert (
        (profile.hourly[["clean_dc_power_w", "clean_ac_power_w", "clean_ac_energy_kwh"]] >= 0)
        .all()
        .all()
    )
    assert profile.annual_clean_energy_kwh > 0


def test_panel_scaling_is_applied_once() -> None:
    dataset = FixtureWeatherProvider().load(_request())
    one_panel = PVWattsPowerModel().calculate_hourly(
        dataset, PVSystemConfig(panel_count=1, panel_capacity_w=400)
    )
    farm = PVWattsPowerModel().calculate_hourly(
        dataset, PVSystemConfig(panel_count=10000, panel_capacity_w=400)
    )

    assert farm.annual_clean_energy_kwh == pytest.approx(one_panel.annual_clean_energy_kwh * 10000)


def test_daily_aggregation_respects_riyadh_calendar_days() -> None:
    dataset = FixtureWeatherProvider().load(_request())
    profile = PVWattsPowerModel().calculate_hourly(
        dataset, PVSystemConfig(panel_count=10, panel_capacity_w=400)
    )

    assert list(profile.daily.index.astype(str)) == ["2025-01-01", "2025-01-02"]
    assert profile.daily["clean_ac_energy_kwh"].sum() == pytest.approx(
        profile.annual_clean_energy_kwh
    )


def test_configurable_sapm_temperature_model_runs() -> None:
    dataset = FixtureWeatherProvider().load(_request())
    system = PVSystemConfig(
        panel_count=100,
        panel_capacity_w=400,
        module_temperature_model="sapm_open_rack_glass_glass",
    )

    profile = PVWattsPowerModel().calculate_hourly(dataset, system)

    assert profile.annual_clean_energy_kwh > 0
    assert profile.metadata["module_temperature_model"] == "sapm_open_rack_glass_glass"
