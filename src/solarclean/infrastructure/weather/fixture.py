from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from solarclean.domain.environment.weather import (
    CANONICAL_WEATHER_COLUMNS,
    WeatherDataset,
    WeatherRequest,
)


class FixtureWeatherProvider:
    """Deterministic test-only weather provider.

    The generated data is intentionally small and smooth. It is not calibrated Riyadh weather.
    """

    provider_name = "fixture"

    def __init__(self, profile: str = "riyadh_synthetic") -> None:
        self.profile = profile

    def load(self, request: WeatherRequest) -> WeatherDataset:
        start = pd.Timestamp(request.start).tz_convert(request.target_timezone)
        end = pd.Timestamp(request.end).tz_convert(request.target_timezone)
        index = pd.date_range(start, end, freq="h")
        frame = _fixture_frame(index, self.profile)
        metadata: dict[str, object] = {
            "provider": self.provider_name,
            "fixture_profile": self.profile,
            "retrieval_timestamp": datetime.now(UTC).isoformat(),
            "coordinates": {"latitude": request.latitude, "longitude": request.longitude},
            "date_range": {"start": request.start.isoformat(), "end": request.end.isoformat()},
            "variables": list(CANONICAL_WEATHER_COLUMNS),
            "source_units": {
                "irradiance": f"synthetic {self.profile} W/m2",
                "temperature": f"synthetic {self.profile} deg C",
                "precipitation": f"synthetic {self.profile} mm/hour",
            },
            "normalized_units": {
                "ghi_w_m2": "W/m2",
                "dni_w_m2": "W/m2",
                "dhi_w_m2": "W/m2",
                "temp_air_c": "deg C",
                "wind_speed_m_s": "m/s",
                "relative_humidity_pct": "%",
                "precipitation_mm": "mm/hour",
            },
            "test_only": True,
            "checksum": _fixture_checksum(request, self.profile),
        }
        return WeatherDataset(hourly=frame, metadata=metadata)


def _fixture_frame(index: pd.DatetimeIndex, profile: str) -> pd.DataFrame:
    if profile == "riyadh_synthetic":
        return _riyadh_synthetic_frame(index, include_jan_2_rain=True)
    if profile == "riyadh_dry":
        return _riyadh_synthetic_frame(index, include_jan_2_rain=False, dry=True)
    if profile == "kaust_paper_favorable":
        return _kaust_paper_favorable_frame(index)
    raise ValueError(f"unknown fixture weather profile: {profile}")


def _riyadh_synthetic_frame(
    index: pd.DatetimeIndex,
    *,
    include_jan_2_rain: bool,
    dry: bool = False,
) -> pd.DataFrame:
    hours = index.hour.to_numpy(dtype=float)
    day_of_year = index.dayofyear.to_numpy(dtype=float)
    daylight_shape = np.sin(np.pi * np.clip((hours - 6.0) / 12.0, 0.0, 1.0))
    seasonal = 0.88 + 0.12 * np.cos(2 * np.pi * (day_of_year - 172) / 365.0)
    ghi = 880.0 * daylight_shape * seasonal
    dni = 720.0 * daylight_shape * seasonal
    dhi = 160.0 * daylight_shape * seasonal
    temp = 20.0 + 14.0 * daylight_shape + 5.0 * seasonal
    wind = 2.0 + 1.2 * np.sin(2 * np.pi * hours / 24.0) ** 2
    if dry:
        humidity = np.clip(34.0 - 16.0 * daylight_shape + 4.0 * (1.0 - seasonal), 10.0, 50.0)
    else:
        humidity = np.clip(
            48.0 - 18.0 * daylight_shape + 8.0 * (1.0 - seasonal),
            15.0,
            85.0,
        )
    precipitation = np.zeros(len(index), dtype=float)
    if include_jan_2_rain:
        for position, timestamp in enumerate(index):
            if timestamp.month == 1 and timestamp.day == 2 and timestamp.hour in {4, 5}:
                precipitation[position] = 3.0
    return pd.DataFrame(
        {
            "ghi_w_m2": ghi,
            "dni_w_m2": dni,
            "dhi_w_m2": dhi,
            "temp_air_c": temp,
            "wind_speed_m_s": wind,
            "relative_humidity_pct": humidity,
            "precipitation_mm": precipitation,
        },
        index=index,
    )


def _kaust_paper_favorable_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    hourly = index.hour.to_numpy(dtype=int)
    ghi_by_hour = np.array(
        [
            0,
            0,
            0,
            0,
            0,
            0,
            80,
            250,
            480,
            680,
            820,
            900,
            920,
            880,
            760,
            560,
            330,
            120,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        dtype=float,
    )
    dni_by_hour = np.array(
        [
            0,
            0,
            0,
            0,
            0,
            0,
            60,
            210,
            410,
            580,
            700,
            760,
            780,
            740,
            640,
            470,
            270,
            90,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        dtype=float,
    )
    dhi_by_hour = np.array(
        [0, 0, 0, 0, 0, 0, 20, 40, 70, 90, 110, 120, 125, 120, 105, 80, 55, 25, 0, 0, 0, 0, 0, 0],
        dtype=float,
    )
    temp_by_hour = np.array(
        [
            20,
            20,
            20,
            20,
            20,
            20,
            24,
            26,
            28,
            30,
            32,
            34,
            35,
            35,
            34,
            32,
            29,
            26,
            20,
            20,
            20,
            20,
            20,
            20,
        ],
        dtype=float,
    )
    wind_by_hour = np.array(
        [
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            1.5,
            2.0,
            2.2,
            2.4,
            2.6,
            2.7,
            2.8,
            2.8,
            2.7,
            2.5,
            2.2,
            1.7,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
            0.5,
        ],
        dtype=float,
    )
    humidity_by_hour = np.array(
        [
            82,
            82,
            82,
            82,
            82,
            82,
            55,
            48,
            45,
            42,
            40,
            38,
            37,
            37,
            38,
            41,
            46,
            55,
            82,
            82,
            82,
            82,
            82,
            82,
        ],
        dtype=float,
    )
    return pd.DataFrame(
        {
            "ghi_w_m2": ghi_by_hour[hourly],
            "dni_w_m2": dni_by_hour[hourly],
            "dhi_w_m2": dhi_by_hour[hourly],
            "temp_air_c": temp_by_hour[hourly],
            "wind_speed_m_s": wind_by_hour[hourly],
            "relative_humidity_pct": humidity_by_hour[hourly],
            "precipitation_mm": np.zeros(len(index), dtype=float),
        },
        index=index,
    )


def _fixture_checksum(request: WeatherRequest, profile: str) -> str:
    payload = request.cache_identity()
    payload["fixture_profile"] = profile
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
