"""Regression: the coating scenario must carry the dew-cementation crust state
across days, exactly like baseline/reactive, so its rain-efficiency penalty
channel (partially suppressed by the coating) can actually activate.

Bug history: CoatingStrategy previously rebuilt ContaminationState with
cementation_index=0.0 every day, so base_update.rain_efficiency_multiplier was
always 1.0 and the suppression formula in the rain-cleaning path was dead code.
That silently removed the crust rain penalty from the coating scenario only,
biasing humid-site comparisons in the coating's favour.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from solarclean.config.models import (
    BirdDroppingConfig,
    CoatingConfig,
    CoatingPhysicsConfig,
    CoatingWaterConfig,
    DewCementationConfig,
    FarmConfig,
    PVSystemConfig,
    RainfallCleaningConfig,
    SoilingConfig,
)
from solarclean.domain.coating.strategy import CoatingStrategy
from solarclean.domain.contamination.soiling import DailyEnvironment
from solarclean.domain.environment.weather import WeatherDataset
from solarclean.domain.pv.model import CleanEnergyProfile
from solarclean.domain.scenario.contracts import DailyScenarioInput, ScenarioContext

_DAY_ONE = date(2025, 6, 1)
_MEMORY_DAYS = 10.0
_MAX_RAIN_PENALTY = 0.5


def _weather(days: int) -> WeatherDataset:
    index = pd.date_range(
        start=f"{_DAY_ONE.isoformat()} 00:00:00",
        periods=days * 24,
        freq="h",
        tz="Asia/Riyadh",
    )
    frame = pd.DataFrame(
        {
            "ghi_w_m2": 0.0,
            "dni_w_m2": 0.0,
            "dhi_w_m2": 0.0,
            "temp_air_c": 25.0,
            "wind_speed_m_s": 0.0,
            "relative_humidity_pct": 50.0,
            "precipitation_mm": 0.0,
        },
        index=index,
    )
    return WeatherDataset(hourly=frame, metadata={"provider": "test"})


def _context(days: int, farm: FarmConfig) -> ScenarioContext:
    daily = pd.DataFrame(
        {"clean_ac_energy_kwh": [100.0] * days},
        index=[_DAY_ONE + timedelta(days=i) for i in range(days)],
    )
    clean = CleanEnergyProfile(
        hourly=pd.DataFrame(),
        daily=daily,
        annual_clean_energy_kwh=float(daily["clean_ac_energy_kwh"].sum()),
        metadata={},
    )
    return ScenarioContext.from_inputs(
        weather=_weather(days),
        clean_energy=clean,
        event_tape=None,
        farm_config=farm,
    )


def _strategy(farm: FarmConfig, *, suppression_fraction: float = 0.0) -> CoatingStrategy:
    soiling = SoilingConfig(
        base_daily_soiling_loss_fraction=0.01,
        dust_event_probability=0.0,
        stochastic_std_fraction=0.0,
        dew_cementation=DewCementationConfig(
            enabled=True,
            onset_relative_humidity_pct=75.0,
            saturation_relative_humidity_pct=95.0,
            max_soiling_rate_multiplier=1.5,
            max_rain_efficiency_penalty=_MAX_RAIN_PENALTY,
            memory_days=_MEMORY_DAYS,
        ),
    )
    coating = CoatingConfig(
        enabled=True,
        physics=CoatingPhysicsConfig(
            dust_accumulation_multiplier=1.0,
            initial_effectiveness_fraction=1.0,
            annual_degradation_fraction=0.0,
            cementation_suppression_fraction=suppression_fraction,
            max_surface_cooling_c=0.0,
            optical_transmittance_multiplier=1.0,
            passive_cleaning_base_efficiency=0.0,
        ),
        water=CoatingWaterConfig(
            condensation_liters_per_m2_per_c_hour=0.0,
            minimum_relative_humidity_pct=100.0,
        ),
    )
    return CoatingStrategy(
        coating=coating,
        soiling=soiling,
        rainfall=RainfallCleaningConfig(),
        birds=BirdDroppingConfig(event_probability_per_cohort_day=0.0),
        farm=farm,
        pv_system=PVSystemConfig(panel_count=10, panel_capacity_w=400.0),
    )


def _day_input(day_index: int, *, max_rh: float, precipitation_mm: float) -> DailyScenarioInput:
    day = _DAY_ONE + timedelta(days=day_index)
    return DailyScenarioInput(
        date=day,
        clean_energy_kwh=100.0,
        clean_energy_per_panel_kwh=10.0,
        environment=DailyEnvironment(
            date=day,
            precipitation_mm=precipitation_mm,
            mean_relative_humidity_pct=50.0,
            max_relative_humidity_pct=max_rh,
        ),
        event_inputs=None,
        day_index=day_index,
    )


def test_coating_carries_cementation_index_and_pays_rain_penalty() -> None:
    farm = FarmConfig(
        representation="cohort",
        total_panels=10,
        panel_capacity_w=400.0,
        cohort_count=2,
        panels_per_cohort=5,
        cohort_soiling_variation_fraction=0.0,
    )
    strategy = _strategy(farm)
    context = _context(3, farm)
    rng = np.random.default_rng(0)

    state = strategy.initial_state(context, rng)
    assert state.cementation_index == 0.0

    # Two humid nights at RH saturation: dew risk 1.0, so the crust index
    # relaxes toward 1.0 with memory_days=10 exactly as in the shared model.
    step1 = strategy.simulate_day(
        _day_input(0, max_rh=95.0, precipitation_mm=0.0), state, context, rng
    )
    assert step1.state.cementation_index == pytest.approx(1.0 / _MEMORY_DAYS)

    step2 = strategy.simulate_day(
        _day_input(1, max_rh=95.0, precipitation_mm=0.0), step1.state, context, rng
    )
    expected_index = 0.1 + (1.0 - 0.1) / _MEMORY_DAYS
    assert step2.state.cementation_index == pytest.approx(expected_index)

    # Dry day with strong rain: the carried crust must reduce rain cleaning.
    step3 = strategy.simulate_day(
        _day_input(2, max_rh=40.0, precipitation_mm=6.0), step2.state, context, rng
    )
    expected_multiplier = 1.0 - _MAX_RAIN_PENALTY * expected_index
    assert step3.result.extensions["uncoated_rain_efficiency_multiplier"] == pytest.approx(
        expected_multiplier
    )
    assert step3.result.extensions["cementation_index"] == 0.0  # full rain washes the crust
    assert step3.state.cementation_index == 0.0

    # Dust trace: 1.0 -> 0.985 -> 0.970 (0.01 base + 0.005 dew adhesion per humid
    # day), then a dry 0.01 loss to 0.960 before rain restores with the
    # penalized multiplier: 0.96 + (1 - 0.96) * 0.95 * expected_multiplier.
    expected_dust = 0.96 + 0.04 * 0.95 * expected_multiplier
    for cohort in step3.state.cohorts:
        assert cohort.dust_soiling_ratio == pytest.approx(expected_dust)


def test_full_suppression_neutralizes_the_carried_rain_penalty() -> None:
    farm = FarmConfig(
        representation="cohort",
        total_panels=10,
        panel_capacity_w=400.0,
        cohort_count=2,
        panels_per_cohort=5,
        cohort_soiling_variation_fraction=0.0,
    )
    strategy = _strategy(farm, suppression_fraction=1.0)
    context = _context(3, farm)
    rng = np.random.default_rng(0)

    state = strategy.initial_state(context, rng)
    step1 = strategy.simulate_day(
        _day_input(0, max_rh=95.0, precipitation_mm=0.0), state, context, rng
    )
    step2 = strategy.simulate_day(
        _day_input(1, max_rh=95.0, precipitation_mm=0.0), step1.state, context, rng
    )
    step3 = strategy.simulate_day(
        _day_input(2, max_rh=40.0, precipitation_mm=6.0), step2.state, context, rng
    )

    # The crust still exists on the shared environmental state...
    assert step3.result.extensions["uncoated_rain_efficiency_multiplier"] < 1.0
    # ...but a fully suppressing coating cleans at full rain efficiency, and it
    # also blocks the dew-adhesion deposition (0.01/day base only): 1.0 -> 0.99
    # -> 0.98 -> 0.97 before rain restores with multiplier 1.0.
    expected_dust = 0.97 + (1.0 - 0.97) * 0.95
    for cohort in step3.state.cohorts:
        assert cohort.dust_soiling_ratio == pytest.approx(expected_dust)
