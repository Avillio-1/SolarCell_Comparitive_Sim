from __future__ import annotations

from pathlib import Path

import pytest

from solarclean.application.dew_simulator import simulate_nighttime_dew
from solarclean.config.loader import load_config


def _paper_config():
    return load_config(Path("configs/default.yaml"))


def test_paper_calibrated_simulator_harvests_on_a_favorable_night() -> None:
    result = simulate_nighttime_dew(
        _paper_config(),
        air_temperature_c=25.0,
        relative_humidity_pct=80.0,
        wind_speed_m_s=2.0,
    )

    assert result.status_code == "harvesting"
    assert result.dew_eligible
    assert result.harvest_active
    assert result.dew_margin_c > 0.0
    assert result.coated_surface_temperature_c < result.dew_point_c
    assert result.harvested_liters_per_m2_hour > 0.0
    assert result.coated_area_m2 == pytest.approx(20_000.0)
    assert result.whole_farm_harvested_liters_per_hour == pytest.approx(
        result.harvested_liters_per_m2_hour * result.coated_area_m2
    )


def test_simulator_explains_humidity_and_wind_failures() -> None:
    config = _paper_config()
    low_humidity = simulate_nighttime_dew(
        config,
        air_temperature_c=25.0,
        relative_humidity_pct=45.0,
        wind_speed_m_s=2.0,
    )
    windy = simulate_nighttime_dew(
        config,
        air_temperature_c=25.0,
        relative_humidity_pct=80.0,
        wind_speed_m_s=15.0,
    )

    assert low_humidity.status_code == "below_humidity_gate"
    assert low_humidity.humidity_gate_margin_pct_points == pytest.approx(-20.0)
    assert low_humidity.harvested_liters_per_m2_hour == 0.0
    assert windy.status_code == "surface_above_dew_point"
    assert windy.dew_margin_c < 0.0
    assert windy.harvested_liters_per_m2_hour == 0.0


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("relative_humidity_pct", 101.0),
        ("air_temperature_c", float("nan")),
        ("wind_speed_m_s", -0.1),
    ),
)
def test_simulator_rejects_invalid_inputs(field: str, value: float) -> None:
    inputs = {
        "air_temperature_c": 25.0,
        "relative_humidity_pct": 80.0,
        "wind_speed_m_s": 2.0,
    }
    inputs[field] = value

    with pytest.raises(ValueError, match=field):
        simulate_nighttime_dew(_paper_config(), **inputs)
