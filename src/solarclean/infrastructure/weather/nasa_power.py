from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
import pandas as pd

from solarclean.domain.environment.weather import (
    CANONICAL_WEATHER_COLUMNS,
    WeatherDataset,
    WeatherRequest,
)
from solarclean.infrastructure.weather.cache import WeatherCache


class WeatherProviderError(RuntimeError):
    """Raised when a weather provider cannot return a valid canonical dataset."""


class _HttpClient(Protocol):
    def get(
        self,
        url: str,
        *,
        params: dict[str, str | float | int | bool | None],
        timeout: float,
    ) -> object: ...


NASA_PARAMETER_MAP: dict[str, str] = {
    "ghi_w_m2": "ALLSKY_SFC_SW_DWN",
    "dni_w_m2": "ALLSKY_SFC_SW_DNI",
    "dhi_w_m2": "ALLSKY_SFC_SW_DIFF",
    "temp_air_c": "T2M",
    "wind_speed_m_s": "WS2M",
    "relative_humidity_pct": "RH2M",
    "precipitation_mm": "PRECTOTCORR",
}


class NasaPowerWeatherProvider:
    provider_name = "nasa_power"
    endpoint = "https://power.larc.nasa.gov/api/temporal/hourly/point"

    def __init__(
        self,
        cache_directory: Path,
        *,
        cache_enabled: bool = True,
        timeout_seconds: float = 30.0,
        http_client: _HttpClient | None = None,
    ) -> None:
        self.cache = WeatherCache(cache_directory)
        self.cache_enabled = cache_enabled
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client or httpx.Client()

    def load(self, request: WeatherRequest) -> WeatherDataset:
        key = self.cache.key_for(request, self.provider_name)
        if self.cache_enabled:
            cached = self.cache.read_normalized(key)
            if cached is not None:
                return cached
        payload = self._fetch(request)
        if self.cache_enabled:
            self.cache.write_raw(key, payload)
        dataset = self._normalize(payload, request)
        if self.cache_enabled:
            self.cache.write_normalized(key, dataset)
        return dataset

    def _fetch(self, request: WeatherRequest) -> dict[str, Any]:
        start_utc = pd.Timestamp(request.start).tz_convert("UTC")
        end_utc = pd.Timestamp(request.end).tz_convert("UTC")
        params: dict[str, str | float | int | bool | None] = {
            "community": "RE",
            "longitude": request.longitude,
            "latitude": request.latitude,
            "start": start_utc.strftime("%Y%m%d"),
            "end": end_utc.strftime("%Y%m%d"),
            "parameters": ",".join(NASA_PARAMETER_MAP.values()),
            "format": "JSON",
            "time-standard": "UTC",
        }
        if request.elevation_m is not None:
            params["site-elevation"] = request.elevation_m
        try:
            response = self.http_client.get(
                self.endpoint, params=params, timeout=self.timeout_seconds
            )
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            payload = response.json() if hasattr(response, "json") else None
        except httpx.TimeoutException as exc:
            raise WeatherProviderError("NASA POWER request timed out") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise WeatherProviderError("NASA POWER rate limit exceeded") from exc
            raise WeatherProviderError(f"NASA POWER HTTP error: {status}") from exc
        except httpx.HTTPError as exc:
            raise WeatherProviderError(f"NASA POWER request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise WeatherProviderError("NASA POWER response was not a JSON object")
        return payload

    def _normalize(self, payload: dict[str, Any], request: WeatherRequest) -> WeatherDataset:
        try:
            parameters = payload["properties"]["parameter"]
        except KeyError as exc:
            raise WeatherProviderError("NASA POWER response missing properties.parameter") from exc
        if not isinstance(parameters, dict):
            raise WeatherProviderError("NASA POWER parameter payload is malformed")
        source_columns: dict[str, pd.Series] = {}
        for canonical, nasa_name in NASA_PARAMETER_MAP.items():
            raw_values = parameters.get(nasa_name)
            if not isinstance(raw_values, dict):
                raise WeatherProviderError(f"missing NASA parameter: {nasa_name}")
            parsed: dict[pd.Timestamp, float] = {}
            for timestamp_text, value in raw_values.items():
                try:
                    timestamp = pd.to_datetime(str(timestamp_text), format="%Y%m%d%H", utc=True)
                    parsed[timestamp] = float(value)
                except (TypeError, ValueError) as exc:
                    raise WeatherProviderError(
                        f"malformed NASA timestamp or value for {nasa_name}: {timestamp_text}"
                    ) from exc
            source_columns[canonical] = pd.Series(parsed, dtype=float)
        frame = pd.DataFrame(source_columns).sort_index()
        frame.index = pd.DatetimeIndex(frame.index).tz_convert(request.target_timezone)
        start = pd.Timestamp(request.start).tz_convert(request.target_timezone)
        end = pd.Timestamp(request.end).tz_convert(request.target_timezone)
        frame = frame.loc[(frame.index >= start) & (frame.index <= end)]
        if frame.empty:
            raise WeatherProviderError("NASA POWER returned no rows in requested range")
        _validate_hourly_coverage(pd.DatetimeIndex(frame.index), start, end)
        metadata: dict[str, object] = {
            "provider": self.provider_name,
            "retrieval_timestamp": datetime.now(UTC).isoformat(),
            "coordinates": {"latitude": request.latitude, "longitude": request.longitude},
            "date_range": {"start": request.start.isoformat(), "end": request.end.isoformat()},
            "variables": list(CANONICAL_WEATHER_COLUMNS),
            "nasa_parameters": NASA_PARAMETER_MAP,
            "source_units": {
                "ALLSKY_SFC_SW_DWN": "W/m2",
                "ALLSKY_SFC_SW_DNI": "W/m2",
                "ALLSKY_SFC_SW_DIFF": "W/m2",
                "T2M": "deg C",
                "WS2M": "m/s",
                "RH2M": "%",
                "PRECTOTCORR": "mm/hour",
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
            "checksum": request.checksum(),
        }
        return WeatherDataset(hourly=frame, metadata=metadata)


def _validate_hourly_coverage(
    index: pd.DatetimeIndex,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> None:
    expected = pd.date_range(start, end, freq="h")
    missing = expected.difference(index)
    if len(missing) > 0:
        sample = ", ".join(timestamp.isoformat() for timestamp in missing[:3])
        raise WeatherProviderError(f"NASA POWER missing hourly timestamps: {sample}")
