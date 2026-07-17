from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from solarclean.domain.environment.weather import WeatherDataset, WeatherRequest

NORMALIZED_WEATHER_CACHE_SCHEMA_VERSION = 2


class WeatherCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def key_for(self, request: WeatherRequest, provider_name: str) -> str:
        payload = {
            "schema_version": NORMALIZED_WEATHER_CACHE_SCHEMA_VERSION,
            "provider": provider_name,
            "request": request.cache_identity(),
        }
        text = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def write_raw(self, key: str, payload: object) -> None:
        path = self.directory / f"{key}.raw.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def write_normalized(self, key: str, dataset: WeatherDataset) -> None:
        csv_path = self.directory / f"{key}.normalized.csv"
        metadata_path = self.directory / f"{key}.metadata.json"
        index = pd.DatetimeIndex(dataset.hourly.index)
        dataset.hourly.to_csv(csv_path, index_label="timestamp")
        metadata = dict(dataset.metadata)
        metadata["index_timezone"] = str(index.tz)
        metadata["index_name"] = index.name
        metadata["index_freq"] = index.freqstr
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    def read_normalized(self, key: str) -> WeatherDataset | None:
        csv_path = self.directory / f"{key}.normalized.csv"
        metadata_path = self.directory / f"{key}.metadata.json"
        try:
            if not csv_path.exists() or not metadata_path.exists():
                return None
            frame = pd.read_csv(csv_path)
            if "timestamp" not in frame.columns:
                raise ValueError("cached normalized weather did not contain timestamps")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            index = pd.DatetimeIndex(
                pd.to_datetime(frame.pop("timestamp"), utc=True, format="ISO8601")
            )
            timezone = metadata.get("index_timezone")
            if isinstance(timezone, str):
                index = index.tz_convert(timezone)
            frequency = metadata.get("index_freq")
            if isinstance(frequency, str):
                index = pd.DatetimeIndex(
                    index,
                    freq=pd.tseries.frequencies.to_offset(frequency),
                )
            index.name = metadata.get("index_name")
            frame.index = index
            return WeatherDataset(hourly=frame, metadata=metadata)
        except (OSError, ValueError):
            return None
