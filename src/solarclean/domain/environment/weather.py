from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CANONICAL_WEATHER_COLUMNS: tuple[str, ...] = (
    "ghi_w_m2",
    "dni_w_m2",
    "dhi_w_m2",
    "temp_air_c",
    "wind_speed_m_s",
    "relative_humidity_pct",
    "precipitation_mm",
)


@dataclass(frozen=True)
class WeatherRequest:
    latitude: float
    longitude: float
    start: datetime
    end: datetime
    target_timezone: str
    variables: frozenset[str] = field(default_factory=lambda: frozenset(CANONICAL_WEATHER_COLUMNS))
    elevation_m: float | None = None

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.start.utcoffset() is None:
            raise ValueError("WeatherRequest.start must be timezone-aware")
        if self.end.tzinfo is None or self.end.utcoffset() is None:
            raise ValueError("WeatherRequest.end must be timezone-aware")
        if self.end < self.start:
            raise ValueError("WeatherRequest.end must be after start")
        ZoneInfo(self.target_timezone)

    def cache_identity(self) -> dict[str, object]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation_m": self.elevation_m,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "target_timezone": self.target_timezone,
            "variables": sorted(self.variables),
        }

    def checksum(self) -> str:
        payload = json.dumps(self.cache_identity(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class WeatherDataset:
    hourly: pd.DataFrame
    metadata: dict[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.hourly.index, pd.DatetimeIndex):
            raise ValueError("weather hourly table must use a DatetimeIndex")
        if self.hourly.index.tz is None:
            raise ValueError("weather timestamps must be timezone-aware")
        if self.hourly.index.has_duplicates:
            raise ValueError("weather timestamps contain duplicate values")
        missing = [
            column for column in CANONICAL_WEATHER_COLUMNS if column not in self.hourly.columns
        ]
        if missing:
            raise ValueError(f"missing canonical weather columns: {missing}")
        if not self.hourly.index.is_monotonic_increasing:
            self.hourly = self.hourly.sort_index()
        numeric = self.hourly.loc[:, list(CANONICAL_WEATHER_COLUMNS)].apply(
            pd.to_numeric, errors="coerce"
        )
        if numeric.isna().any().any():
            raise ValueError("weather contains missing or non-numeric canonical values")
        values = numeric.to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("weather contains non-finite canonical values")
        if (
            (
                numeric[["ghi_w_m2", "dni_w_m2", "dhi_w_m2", "wind_speed_m_s", "precipitation_mm"]]
                < 0
            )
            .any()
            .any()
        ):
            raise ValueError(
                "weather irradiance, wind speed, and precipitation must be non-negative"
            )
        if (
            (numeric["relative_humidity_pct"] < 0) | (numeric["relative_humidity_pct"] > 100)
        ).any():
            raise ValueError("relative humidity must be within 0..100 percent")
        if ((numeric["temp_air_c"] < -90.0) | (numeric["temp_air_c"] > 70.0)).any():
            raise ValueError(
                "air temperature must be within -90..70 deg C; "
                "check for provider fill values such as -999"
            )
        self.hourly = numeric

    def to_timezone(self, timezone: str) -> WeatherDataset:
        converted = self.hourly.tz_convert(timezone)
        metadata = dict(self.metadata)
        metadata["target_timezone"] = timezone
        return WeatherDataset(hourly=converted, metadata=metadata)


class WeatherProvider(Protocol):
    def load(self, request: WeatherRequest) -> WeatherDataset:
        """Load canonical hourly weather for the request."""
