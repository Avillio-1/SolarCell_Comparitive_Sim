from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from solarclean.domain.environment.weather import (
    CANONICAL_WEATHER_COLUMNS,
    WeatherDataset,
    WeatherRequest,
)
from solarclean.infrastructure.weather.cache import WeatherCache
from solarclean.infrastructure.weather.csv_provider import CsvWeatherProvider
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider
from solarclean.infrastructure.weather.nasa_power import (
    NasaPowerWeatherProvider,
    WeatherProviderError,
)


def _request() -> WeatherRequest:
    return WeatherRequest(
        latitude=24.7136,
        longitude=46.6753,
        start=datetime(2025, 1, 1, tzinfo=ZoneInfo("Asia/Riyadh")),
        end=datetime(2025, 1, 2, 23, tzinfo=ZoneInfo("Asia/Riyadh")),
        target_timezone="Asia/Riyadh",
        variables=frozenset(CANONICAL_WEATHER_COLUMNS),
    )


def _request_for_hours(hours: int) -> WeatherRequest:
    return WeatherRequest(
        latitude=24.7136,
        longitude=46.6753,
        start=datetime(2025, 1, 1, tzinfo=ZoneInfo("Asia/Riyadh")),
        end=datetime(2025, 1, 1, hours - 1, tzinfo=ZoneInfo("Asia/Riyadh")),
        target_timezone="Asia/Riyadh",
        variables=frozenset(CANONICAL_WEATHER_COLUMNS),
    )


def _canonical_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ghi_w_m2": [0.0] * len(index),
            "dni_w_m2": [0.0] * len(index),
            "dhi_w_m2": [0.0] * len(index),
            "temp_air_c": [25.0] * len(index),
            "wind_speed_m_s": [2.0] * len(index),
            "relative_humidity_pct": [30.0] * len(index),
            "precipitation_mm": [0.0] * len(index),
        },
        index=index,
    )


def test_weather_dataset_rejects_missing_canonical_columns() -> None:
    index = pd.date_range("2025-01-01", periods=2, freq="h", tz="Asia/Riyadh")
    frame = _canonical_frame(index).drop(columns=["dni_w_m2"])

    with pytest.raises(ValueError, match="missing canonical"):
        WeatherDataset(hourly=frame, metadata={"provider": "test"})


def test_weather_dataset_rejects_duplicate_timestamps() -> None:
    index = pd.DatetimeIndex(
        [
            pd.Timestamp("2025-01-01T00:00:00+03:00"),
            pd.Timestamp("2025-01-01T00:00:00+03:00"),
        ],
        tz="Asia/Riyadh",
    )

    with pytest.raises(ValueError, match="duplicate"):
        WeatherDataset(hourly=_canonical_frame(index), metadata={"provider": "test"})


def test_fixture_provider_returns_requested_timezone_and_columns() -> None:
    dataset = FixtureWeatherProvider().load(_request())

    assert list(dataset.hourly.columns)[:7] == list(CANONICAL_WEATHER_COLUMNS)
    assert str(dataset.hourly.index.tz) == "Asia/Riyadh"
    assert dataset.hourly.index.min() == pd.Timestamp("2025-01-01T00:00:00+03:00")
    assert dataset.hourly.index.max() == pd.Timestamp("2025-01-02T23:00:00+03:00")
    assert dataset.metadata["provider"] == "fixture"


def test_csv_provider_maps_columns_and_units(tmp_path: Path) -> None:
    csv_path = tmp_path / "weather.csv"
    csv_path.write_text(
        "timestamp,ghi,dni,dhi,temp,wind,humidity,rain_cm\n"
        "2025-01-01T00:00:00+03:00,0,0,0,20,10,50,0\n"
        "2025-01-01T01:00:00+03:00,0,0,0,20,3.6,51,0.2\n",
        encoding="utf-8",
    )
    provider = CsvWeatherProvider(
        csv_path=csv_path,
        timestamp_column="timestamp",
        column_mapping={
            "ghi": "ghi_w_m2",
            "dni": "dni_w_m2",
            "dhi": "dhi_w_m2",
            "temp": "temp_air_c",
            "wind": "wind_speed_m_s",
            "humidity": "relative_humidity_pct",
            "rain_cm": "precipitation_mm",
        },
        unit_mapping={"wind_speed_m_s": "km/h", "precipitation_mm": "cm"},
    )

    dataset = provider.load(_request_for_hours(2))

    assert dataset.hourly.loc[
        pd.Timestamp("2025-01-01T01:00:00+03:00"), "wind_speed_m_s"
    ] == pytest.approx(1.0)
    assert dataset.hourly.loc[
        pd.Timestamp("2025-01-01T01:00:00+03:00"), "precipitation_mm"
    ] == pytest.approx(2.0)
    assert dataset.metadata["provider"] == "csv"


def test_csv_provider_rejects_missing_hourly_timestamps(tmp_path: Path) -> None:
    csv_path = tmp_path / "weather.csv"
    csv_path.write_text(
        "timestamp,ghi,dni,dhi,temp,wind,humidity,rain\n"
        "2025-01-01T00:00:00+03:00,0,0,0,20,2,50,0\n"
        "2025-01-01T02:00:00+03:00,0,0,0,20,2,50,0\n",
        encoding="utf-8",
    )
    provider = CsvWeatherProvider(
        csv_path=csv_path,
        timestamp_column="timestamp",
        column_mapping={
            "ghi": "ghi_w_m2",
            "dni": "dni_w_m2",
            "dhi": "dhi_w_m2",
            "temp": "temp_air_c",
            "wind": "wind_speed_m_s",
            "humidity": "relative_humidity_pct",
            "rain": "precipitation_mm",
        },
    )

    with pytest.raises(ValueError, match="missing hourly timestamps"):
        provider.load(_request_for_hours(3))


def test_weather_cache_round_trips_dataset(tmp_path: Path) -> None:
    dataset = FixtureWeatherProvider().load(_request())
    cache = WeatherCache(tmp_path)
    key = cache.key_for(_request(), "fixture")

    cache.write_normalized(key, dataset)
    cached = cache.read_normalized(key)

    assert cached is not None
    pd.testing.assert_frame_equal(cached.hourly, dataset.hourly)
    assert cached.metadata["provider"] == "fixture"


class _MalformedClient:
    def get(self, *_args: object, **_kwargs: object) -> object:
        class Response:
            status_code = 200
            text = "{}"

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {"properties": {"parameter": {"T2M": {"bad-date": 1}}}}

        return Response()


def test_nasa_provider_rejects_malformed_response(tmp_path: Path) -> None:
    provider = NasaPowerWeatherProvider(cache_directory=tmp_path, http_client=_MalformedClient())

    with pytest.raises(WeatherProviderError, match="missing NASA parameter"):
        provider.load(_request())
