from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from solarclean.config.models import (
    CoatingPhysicsConfig,
    DewCementationConfig,
    RainfallCleaningConfig,
    SoilingConfig,
)
from solarclean.domain.coating.physics import calculate_surface_temperature_c
from solarclean.domain.contamination.soiling import (
    ContaminationState,
    DailyEnvironment,
    KimberStyleSoilingModel,
)
from solarclean.domain.farm.representation import (
    advance_dust_ratio,
    restore_dust_ratio_after_rain,
)


def _model(**cementation_overrides: object) -> KimberStyleSoilingModel:
    cementation = DewCementationConfig(
        enabled=True,
        onset_relative_humidity_pct=75.0,
        saturation_relative_humidity_pct=95.0,
        max_soiling_rate_multiplier=1.5,
        max_rain_efficiency_penalty=0.5,
        memory_days=10.0,
        **cementation_overrides,  # type: ignore[arg-type]
    )
    return KimberStyleSoilingModel(
        SoilingConfig(
            base_daily_soiling_loss_fraction=0.01,
            dust_event_probability=0.0,
            stochastic_std_fraction=0.0,
            dew_cementation=cementation,
        ),
        RainfallCleaningConfig(),
    )


def _environment(
    *,
    max_rh: float,
    precipitation_mm: float = 0.0,
    day: date = date(2025, 6, 1),
) -> DailyEnvironment:
    return DailyEnvironment(
        date=day,
        precipitation_mm=precipitation_mm,
        mean_relative_humidity_pct=min(max_rh, 50.0),
        max_relative_humidity_pct=max_rh,
    )


def test_disabled_cementation_preserves_existing_behavior() -> None:
    disabled = KimberStyleSoilingModel(
        SoilingConfig(
            base_daily_soiling_loss_fraction=0.01,
            dust_event_probability=0.0,
            stochastic_std_fraction=0.0,
        ),
        RainfallCleaningConfig(),
    )

    update = disabled.update(
        ContaminationState(),
        _environment(max_rh=95.0),
        np.random.default_rng(1),
    )

    assert update.dew_risk == 0.0
    assert update.rain_efficiency_multiplier == 1.0
    assert update.state.cementation_index == 0.0
    assert not [e for e in update.events if e.event_type == "dew_cementation_adhesion"]
    assert update.state.dust_soiling_ratio == pytest.approx(0.99)


def test_humid_night_deposits_more_than_dry_night() -> None:
    model = _model()

    dry = model.update(ContaminationState(), _environment(max_rh=40.0), np.random.default_rng(1))
    humid = model.update(ContaminationState(), _environment(max_rh=95.0), np.random.default_rng(1))

    assert dry.dew_risk == 0.0
    assert humid.dew_risk == pytest.approx(1.0)
    assert dry.state.dust_soiling_ratio == pytest.approx(0.99)
    # Full dew risk applies the 1.5x retention multiplier to the daily loss.
    assert humid.state.dust_soiling_ratio == pytest.approx(0.985)
    events = [e for e in humid.events if e.event_type == "dew_cementation_adhesion"]
    assert len(events) == 1
    assert events[0].magnitude == pytest.approx(0.005)


def test_dew_risk_interpolates_between_onset_and_saturation() -> None:
    model = _model()

    assert model.dew_risk(_environment(max_rh=75.0)) == 0.0
    assert model.dew_risk(_environment(max_rh=85.0)) == pytest.approx(0.5)
    assert model.dew_risk(_environment(max_rh=95.0)) == 1.0
    assert model.dew_risk(_environment(max_rh=100.0)) == 1.0


def test_cementation_index_builds_up_and_penalizes_rain() -> None:
    model = _model()

    state = ContaminationState(dust_soiling_ratio=0.8)
    for offset in range(10):
        update = model.update(
            state,
            _environment(max_rh=95.0, day=date(2025, 6, 1 + offset)),
            np.random.default_rng(1),
        )
        state = update.state
    assert state.cementation_index > 0.6

    crusted_rain = model.update(
        state,
        _environment(max_rh=50.0, precipitation_mm=6.0),
        np.random.default_rng(1),
    )
    fresh_rain = model.update(
        ContaminationState(dust_soiling_ratio=state.dust_soiling_ratio),
        _environment(max_rh=50.0, precipitation_mm=6.0),
        np.random.default_rng(1),
    )

    assert crusted_rain.rain_efficiency_multiplier < 1.0
    assert fresh_rain.rain_efficiency_multiplier == 1.0
    assert crusted_rain.state.dust_soiling_ratio < fresh_rain.state.dust_soiling_ratio


def test_full_rain_washes_the_crust_away() -> None:
    model = _model()

    state = ContaminationState(dust_soiling_ratio=0.8, cementation_index=0.9)
    update = model.update(
        state,
        _environment(max_rh=95.0, precipitation_mm=6.0),
        np.random.default_rng(1),
    )

    assert update.state.cementation_index == 0.0


def test_restore_dust_ratio_honors_rain_efficiency_multiplier() -> None:
    soiling = SoilingConfig()
    rainfall = RainfallCleaningConfig(full_rain_cleaning_efficiency=1.0)

    full = restore_dust_ratio_after_rain(
        0.8, precipitation_mm=6.0, soiling=soiling, rainfall=rainfall
    )
    penalized = restore_dust_ratio_after_rain(
        0.8,
        precipitation_mm=6.0,
        soiling=soiling,
        rainfall=rainfall,
        rain_efficiency_multiplier=0.5,
    )

    assert full == pytest.approx(1.0)
    assert penalized == pytest.approx(0.9)


def test_coating_suppression_bypasses_accumulation_multiplier() -> None:
    """The cementation term enters unscaled: the coating suppresses it via the
    caller-computed fraction, not via the generic dust accumulation multiplier."""
    soiling = SoilingConfig()
    rainfall = RainfallCleaningConfig()

    uncoated = advance_dust_ratio(
        1.0,
        daily_loss_fraction=0.01,
        dust_event_loss_fraction=0.0,
        precipitation_mm=0.0,
        soiling=soiling,
        rainfall=rainfall,
        unscaled_deposition_fraction=0.005,
    )
    coated_suppressed = advance_dust_ratio(
        1.0,
        daily_loss_fraction=0.01,
        dust_event_loss_fraction=0.0,
        precipitation_mm=0.0,
        soiling=soiling,
        rainfall=rainfall,
        accumulation_multiplier=0.6,
        unscaled_deposition_fraction=0.005 * (1.0 - 0.9),
    )

    assert uncoated == pytest.approx(1.0 - 0.015)
    assert coated_suppressed == pytest.approx(1.0 - (0.01 * 0.6 + 0.0005))


def test_smooth_humidity_cooling_declines_continuously() -> None:
    physics = CoatingPhysicsConfig(
        max_surface_cooling_c=6.0,
        humidity_cooling_mode="smooth",
        humidity_cooling_dry_reference_pct=40.0,
        emissivity_atmospheric_window=1.0,
        wind_cooling_decay_per_m_s=0.0,
    )

    def cooling(rh: float) -> float:
        return 25.0 - calculate_surface_temperature_c(
            air_temperature_c=25.0,
            relative_humidity_pct=rh,
            wind_speed_m_s=0.0,
            irradiance_w_m2=0.0,
            physics=physics,
        )

    assert cooling(20.0) == pytest.approx(6.0)
    assert cooling(40.0) == pytest.approx(6.0)
    assert cooling(70.0) == pytest.approx(6.0 * 0.5**0.5)
    assert cooling(100.0) == pytest.approx(0.0)
    assert cooling(55.0) > cooling(85.0) > cooling(95.0)
    # Humid-night regime keeps enough cooling to cross the dew point
    # (dew-point depression at 92% RH is ~1.3 C).
    assert cooling(92.0) > 1.3


def test_humidity_cooling_floor_preserves_high_rh_cooling() -> None:
    """KAUST paper (Fig 3a): cooling only drops from 8.0 C at 50% RH to 6.1 C
    at 90% RH, so a floor keeps residual cooling instead of decaying to zero."""
    physics = CoatingPhysicsConfig(
        max_surface_cooling_c=7.0,
        humidity_cooling_mode="smooth",
        humidity_cooling_dry_reference_pct=40.0,
        humidity_cooling_floor_fraction=0.70,
        emissivity_atmospheric_window=1.0,
        wind_cooling_decay_per_m_s=0.0,
    )

    def cooling(rh: float) -> float:
        return 25.0 - calculate_surface_temperature_c(
            air_temperature_c=25.0,
            relative_humidity_pct=rh,
            wind_speed_m_s=0.0,
            irradiance_w_m2=0.0,
            physics=physics,
        )

    assert cooling(40.0) == pytest.approx(7.0)
    assert cooling(100.0) == pytest.approx(7.0 * 0.70)
    # Ratio between humid and dry regimes tracks the paper's 6.1/8.0 = 0.76
    # (loose tolerance: the two-parameter curve also has to preserve the
    # paper's near-saturation cooling that sets the ~65% RH condensation onset).
    assert cooling(90.0) / cooling(50.0) == pytest.approx(0.76, abs=0.1)
    # Cooling exceeds the dew-point depression (~1.9 C at 90% RH), so
    # condensation stays thermodynamically possible on humid nights.
    assert cooling(90.0) > 1.9


def test_threshold_humidity_cooling_unchanged_by_default() -> None:
    physics = CoatingPhysicsConfig(
        max_surface_cooling_c=6.0,
        humidity_cooling_reference_pct=80.0,
        emissivity_atmospheric_window=1.0,
        wind_cooling_decay_per_m_s=0.0,
    )

    def cooling(rh: float) -> float:
        return 25.0 - calculate_surface_temperature_c(
            air_temperature_c=25.0,
            relative_humidity_pct=rh,
            wind_speed_m_s=0.0,
            irradiance_w_m2=0.0,
            physics=physics,
        )

    assert cooling(50.0) == pytest.approx(6.0)
    assert cooling(80.0) == pytest.approx(6.0)
    assert cooling(90.0) == pytest.approx(3.0)
