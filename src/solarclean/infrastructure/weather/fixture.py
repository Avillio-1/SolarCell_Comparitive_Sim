from __future__ import annotations

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

    def load(self, request: WeatherRequest) -> WeatherDataset:
        start = pd.Timestamp(request.start).tz_convert(request.target_timezone)
        end = pd.Timestamp(request.end).tz_convert(request.target_timezone)
        index = pd.date_range(start, end, freq="h")
        hours = index.hour.to_numpy(dtype=float)
        day_of_year = index.dayofyear.to_numpy(dtype=float)
        daylight_shape = np.sin(np.pi * np.clip((hours - 6.0) / 12.0, 0.0, 1.0))
        seasonal = 0.88 + 0.12 * np.cos(2 * np.pi * (day_of_year - 172) / 365.0)
        ghi = 880.0 * daylight_shape * seasonal
        dni = 720.0 * daylight_shape * seasonal
        dhi = 160.0 * daylight_shape * seasonal
        temp = 20.0 + 14.0 * daylight_shape + 5.0 * seasonal
        wind = 2.0 + 1.2 * np.sin(2 * np.pi * hours / 24.0) ** 2
        humidity = np.clip(48.0 - 18.0 * daylight_shape + 8.0 * (1.0 - seasonal), 15.0, 85.0)
        precipitation = np.zeros(len(index), dtype=float)
        for position, timestamp in enumerate(index):
            if timestamp.month == 1 and timestamp.day == 2 and timestamp.hour in {4, 5}:
                precipitation[position] = 3.0
        frame = pd.DataFrame(
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
        metadata: dict[str, object] = {
            "provider": self.provider_name,
            "retrieval_timestamp": datetime.now(UTC).isoformat(),
            "coordinates": {"latitude": request.latitude, "longitude": request.longitude},
            "date_range": {"start": request.start.isoformat(), "end": request.end.isoformat()},
            "variables": list(CANONICAL_WEATHER_COLUMNS),
            "source_units": {
                "irradiance": "synthetic W/m2",
                "temperature": "synthetic deg C",
                "precipitation": "synthetic mm/hour",
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
            "checksum": request.checksum(),
        }
        return WeatherDataset(hourly=frame, metadata=metadata)
