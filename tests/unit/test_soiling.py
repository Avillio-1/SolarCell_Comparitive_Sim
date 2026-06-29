from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from tests.unit.test_weather import _request

from solarclean.config.models import RainfallCleaningConfig, SoilingConfig
from solarclean.domain.contamination.soiling import (
    ContaminationState,
    DailyEnvironment,
    KimberStyleSoilingModel,
)
from solarclean.domain.simulation.baseline import BaselineSimulationEngine
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider


def test_zero_accumulation_preserves_clean_panel() -> None:
    model = KimberStyleSoilingModel(
        SoilingConfig(base_daily_soiling_loss_fraction=0.0, dust_event_probability=0.0),
        RainfallCleaningConfig(),
    )

    update = model.update(
        ContaminationState(),
        DailyEnvironment(date=date(2025, 1, 1), precipitation_mm=0, mean_relative_humidity_pct=25),
        np.random.default_rng(1),
    )

    assert update.state.dust_soiling_ratio == pytest.approx(1.0)


def test_dry_day_reduces_soiling_ratio() -> None:
    model = KimberStyleSoilingModel(
        SoilingConfig(base_daily_soiling_loss_fraction=0.01, dust_event_probability=0.0),
        RainfallCleaningConfig(),
    )

    update = model.update(
        ContaminationState(),
        DailyEnvironment(date=date(2025, 1, 1), precipitation_mm=0, mean_relative_humidity_pct=25),
        np.random.default_rng(1),
    )

    assert update.state.dust_soiling_ratio < 1.0


def test_partial_and_strong_rain_restore_ratio_within_bounds() -> None:
    model = KimberStyleSoilingModel(
        SoilingConfig(base_daily_soiling_loss_fraction=0.02, dust_event_probability=0.0),
        RainfallCleaningConfig(
            partial_rain_threshold_mm=1.0,
            full_rain_cleaning_threshold_mm=5.0,
            partial_rain_cleaning_efficiency=0.5,
            full_rain_cleaning_efficiency=1.0,
        ),
    )
    dirty = ContaminationState(dust_soiling_ratio=0.8)

    partial = model.update(
        dirty,
        DailyEnvironment(date=date(2025, 1, 1), precipitation_mm=2, mean_relative_humidity_pct=25),
        np.random.default_rng(1),
    )
    full = model.update(
        dirty,
        DailyEnvironment(date=date(2025, 1, 2), precipitation_mm=6, mean_relative_humidity_pct=25),
        np.random.default_rng(1),
    )

    assert 0.8 < partial.state.dust_soiling_ratio < 1.0
    assert full.state.dust_soiling_ratio == pytest.approx(1.0)


def test_baseline_actual_energy_never_exceeds_clean_energy() -> None:
    weather = FixtureWeatherProvider().load(_request())
    clean = PVWattsPowerModel().calculate_hourly(weather, system=None)
    engine = BaselineSimulationEngine(
        soiling_model=KimberStyleSoilingModel(
            SoilingConfig(base_daily_soiling_loss_fraction=0.005, random_seed=42),
            RainfallCleaningConfig(),
        )
    )

    result = engine.run(clean, weather, random_seed=42)

    assert (result.daily["actual_energy_kwh"] <= result.daily["clean_energy_kwh"] + 1e-9).all()
    assert result.annual_actual_energy_kwh <= result.annual_clean_energy_kwh


def test_same_seed_reproduces_events_and_results() -> None:
    weather = FixtureWeatherProvider().load(_request())
    clean = PVWattsPowerModel().calculate_hourly(weather, system=None)
    model = KimberStyleSoilingModel(
        SoilingConfig(
            base_daily_soiling_loss_fraction=0.005,
            dust_event_probability=0.8,
            dust_event_loss_min_fraction=0.01,
            dust_event_loss_max_fraction=0.03,
            random_seed=7,
        ),
        RainfallCleaningConfig(),
    )
    engine = BaselineSimulationEngine(model)

    first = engine.run(clean, weather, random_seed=7)
    second = engine.run(clean, weather, random_seed=7)

    pd.testing.assert_frame_equal(first.daily, second.daily)
    assert [event.to_record() for event in first.events] == [
        event.to_record() for event in second.events
    ]
