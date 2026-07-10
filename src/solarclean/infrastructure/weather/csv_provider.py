from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from solarclean.domain.environment.weather import (
    CANONICAL_WEATHER_COLUMNS,
    WeatherDataset,
    WeatherRequest,
)


class CsvWeatherProvider:
    provider_name = "csv"

    def __init__(
        self,
        csv_path: Path,
        timestamp_column: str = "timestamp",
        column_mapping: dict[str, str] | None = None,
        unit_mapping: dict[str, str] | None = None,
        missing_data_policy: str = "error",
    ) -> None:
        self.csv_path = csv_path
        self.timestamp_column = timestamp_column
        self.column_mapping = column_mapping or {}
        self.unit_mapping = unit_mapping or {}
        if missing_data_policy not in {"error", "drop", "interpolate"}:
            raise ValueError(f"unknown missing_data_policy: {missing_data_policy}")
        self.missing_data_policy = missing_data_policy

    def load(self, request: WeatherRequest) -> WeatherDataset:
        if not self.csv_path.exists():
            raise FileNotFoundError(f"weather CSV does not exist: {self.csv_path}")
        raw = pd.read_csv(self.csv_path)
        if self.timestamp_column not in raw.columns:
            raise ValueError(f"CSV missing timestamp column: {self.timestamp_column}")
        timestamps = pd.to_datetime(raw[self.timestamp_column], utc=False)
        if not isinstance(timestamps, pd.Series):
            raise ValueError("timestamp parsing failed")
        if timestamps.dt.tz is None:
            raise ValueError("CSV timestamps must include timezone information")
        frame = raw.drop(columns=[self.timestamp_column]).rename(columns=self.column_mapping)
        missing = [column for column in CANONICAL_WEATHER_COLUMNS if column not in frame.columns]
        if missing:
            raise ValueError(f"CSV mapping missing canonical columns: {missing}")
        canonical = frame.loc[:, list(CANONICAL_WEATHER_COLUMNS)].copy()
        for column in canonical.columns:
            canonical[column] = pd.to_numeric(canonical[column], errors="coerce")
        canonical = self._convert_units(canonical)
        canonical.index = pd.DatetimeIndex(timestamps).tz_convert(request.target_timezone)
        start = pd.Timestamp(request.start).tz_convert(request.target_timezone)
        end = pd.Timestamp(request.end).tz_convert(request.target_timezone)
        canonical = canonical.loc[(canonical.index >= start) & (canonical.index <= end)]
        canonical = _apply_missing_data_policy(
            canonical,
            start=start,
            end=end,
            policy=self.missing_data_policy,
        )
        metadata: dict[str, object] = {
            "provider": self.provider_name,
            "retrieval_timestamp": datetime.now(UTC).isoformat(),
            "source_path": str(self.csv_path),
            "coordinates": {"latitude": request.latitude, "longitude": request.longitude},
            "date_range": {"start": request.start.isoformat(), "end": request.end.isoformat()},
            "variables": list(CANONICAL_WEATHER_COLUMNS),
            "source_units": self.unit_mapping,
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
            "missing_data_policy": self.missing_data_policy,
        }
        return WeatherDataset(hourly=canonical, metadata=metadata)

    def _convert_units(self, frame: pd.DataFrame) -> pd.DataFrame:
        converted = frame.copy()
        for column, unit in self.unit_mapping.items():
            if column not in converted.columns:
                continue
            normalized = unit.strip().lower()
            if normalized in {"m/s", "mps"}:
                continue
            if column == "wind_speed_m_s" and normalized in {"km/h", "kph"}:
                converted[column] = converted[column] / 3.6
            elif column == "precipitation_mm" and normalized == "cm":
                converted[column] = converted[column] * 10.0
            elif column == "temp_air_c" and normalized in {"f", "degf", "fahrenheit"}:
                converted[column] = (converted[column] - 32.0) * 5.0 / 9.0
            elif normalized not in {"w/m2", "w/m^2", "deg c", "degc", "c", "%", "mm", "mm/hour"}:
                raise ValueError(f"unsupported unit conversion for {column}: {unit}")
        return converted


def _validate_hourly_coverage(
    index: pd.DatetimeIndex,
    start: pd.Timestamp,
    end: pd.Timestamp,
    label: str,
) -> None:
    expected = pd.date_range(start, end, freq="h")
    missing = expected.difference(index)
    if len(missing) > 0:
        sample = ", ".join(timestamp.isoformat() for timestamp in missing[:3])
        raise ValueError(f"{label} missing hourly timestamps: {sample}")


def _apply_missing_data_policy(
    frame: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    policy: str,
) -> pd.DataFrame:
    if policy == "error":
        _validate_hourly_coverage(pd.DatetimeIndex(frame.index), start, end, "CSV weather")
        if frame.isna().any().any():
            raise ValueError("CSV weather contains missing or non-numeric values")
        return frame
    if policy == "drop":
        dropped = frame.dropna()
        if dropped.empty:
            raise ValueError("CSV weather has no complete rows after dropping missing data")
        return dropped
    expected = pd.date_range(start, end, freq="h")
    interpolated = frame.reindex(expected).interpolate(
        method="time",
        limit_direction="both",
    )
    if interpolated.isna().any().any():
        raise ValueError("CSV weather missing data could not be interpolated")
    return interpolated
