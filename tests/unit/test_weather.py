from __future__ import annotations

import hashlib
import json
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
    NASA_PARAMETER_MAP,
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


@pytest.mark.parametrize("temperature_c", [-999.0, -90.1, 70.1])
def test_weather_dataset_rejects_implausible_air_temperatures(temperature_c: float) -> None:
    index = pd.date_range("2025-01-01", periods=2, freq="h", tz="Asia/Riyadh")
    frame = _canonical_frame(index)
    frame.loc[index[1], "temp_air_c"] = temperature_c

    with pytest.raises(ValueError, match="air temperature.*provider fill values"):
        WeatherDataset(hourly=frame, metadata={"provider": "test"})


def test_fixture_provider_returns_requested_timezone_and_columns() -> None:
    dataset = FixtureWeatherProvider().load(_request())

    assert list(dataset.hourly.columns)[:7] == list(CANONICAL_WEATHER_COLUMNS)
    assert str(dataset.hourly.index.tz) == "Asia/Riyadh"
    assert dataset.hourly.index.min() == pd.Timestamp("2025-01-01T00:00:00+03:00")
    assert dataset.hourly.index.max() == pd.Timestamp("2025-01-02T23:00:00+03:00")
    assert dataset.metadata["provider"] == "fixture"
    assert dataset.metadata["fixture_profile"] == "riyadh_synthetic"


def test_fixture_provider_preserves_local_day_across_dst_transition() -> None:
    timezone = ZoneInfo("Europe/Berlin")
    request = WeatherRequest(
        latitude=52.52,
        longitude=13.405,
        start=datetime(2025, 3, 30, tzinfo=timezone),
        end=datetime(2025, 3, 30, 23, tzinfo=timezone),
        target_timezone="Europe/Berlin",
        variables=frozenset(CANONICAL_WEATHER_COLUMNS),
    )

    dataset = FixtureWeatherProvider().load(request)

    assert len(dataset.hourly) == 23
    assert set(dataset.hourly.index.date) == {datetime(2025, 3, 30).date()}
    assert dataset.hourly.index[0].isoformat() == "2025-03-30T00:00:00+01:00"
    assert dataset.hourly.index[-1].isoformat() == "2025-03-30T23:00:00+02:00"


def test_fixture_profiles_expose_favorable_and_dry_weather() -> None:
    favorable = FixtureWeatherProvider(profile="kaust_paper_favorable").load(_request())
    dry = FixtureWeatherProvider(profile="riyadh_dry").load(_request())

    night = pd.Timestamp("2025-01-01T00:00:00+03:00")
    noon = pd.Timestamp("2025-01-01T12:00:00+03:00")
    assert (
        favorable.hourly.loc[night, "relative_humidity_pct"]
        > dry.hourly.loc[night, "relative_humidity_pct"]
    )
    assert favorable.hourly.loc[noon, "ghi_w_m2"] > 0.0
    assert (
        dry.hourly["relative_humidity_pct"].max() < favorable.hourly["relative_humidity_pct"].max()
    )
    assert favorable.metadata["checksum"] != dry.metadata["checksum"]


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


def test_csv_provider_interpolates_missing_rows_when_configured(tmp_path: Path) -> None:
    csv_path = tmp_path / "weather.csv"
    csv_path.write_text(
        "timestamp,ghi_w_m2,dni_w_m2,dhi_w_m2,temp_air_c,wind_speed_m_s,"
        "relative_humidity_pct,precipitation_mm\n"
        "2025-01-01T00:00:00+03:00,0,0,0,20,2,50,0\n"
        "2025-01-01T02:00:00+03:00,0,0,0,22,2,52,0\n",
        encoding="utf-8",
    )
    provider = CsvWeatherProvider(
        csv_path=csv_path,
        missing_data_policy="interpolate",
    )

    dataset = provider.load(_request_for_hours(3))

    assert len(dataset.hourly) == 3
    assert dataset.hourly.iloc[1]["temp_air_c"] == pytest.approx(21.0)


def test_weather_cache_round_trips_dataset(tmp_path: Path) -> None:
    dataset = FixtureWeatherProvider().load(_request())
    cache = WeatherCache(tmp_path)
    key = cache.key_for(_request(), "fixture")

    cache.write_normalized(key, dataset)
    cached = cache.read_normalized(key)

    assert cached is not None
    pd.testing.assert_frame_equal(cached.hourly, dataset.hourly)
    assert cached.metadata["provider"] == "fixture"


def test_weather_cache_round_trips_across_dst_transition(tmp_path: Path) -> None:
    index = pd.date_range(
        "2025-03-29T00:00:00",
        "2025-03-31T23:00:00",
        freq="h",
        tz="Europe/Berlin",
    )
    dataset = WeatherDataset(
        hourly=_canonical_frame(index),
        metadata={"provider": "test"},
    )
    cache = WeatherCache(tmp_path)

    cache.write_normalized("berlin-dst", dataset)
    cached = cache.read_normalized("berlin-dst")

    assert cached is not None
    pd.testing.assert_frame_equal(cached.hourly, dataset.hourly)
    assert cached.hourly.index.tz == dataset.hourly.index.tz


def test_weather_cache_returns_none_for_unparseable_timestamp(tmp_path: Path) -> None:
    cache = WeatherCache(tmp_path)
    (tmp_path / "corrupt.normalized.csv").write_text(
        "timestamp,ghi_w_m2\nnot-a-timestamp,0\n",
        encoding="utf-8",
    )
    (tmp_path / "corrupt.metadata.json").write_text(
        json.dumps({"index_timezone": "Europe/Berlin"}),
        encoding="utf-8",
    )

    assert cache.read_normalized("corrupt") is None


def test_weather_cache_schema_invalidates_legacy_normalized_files(tmp_path: Path) -> None:
    request = _request()
    cache = WeatherCache(tmp_path)
    legacy_payload = {"provider": "nasa_power", "request": request.cache_identity()}
    legacy_key = hashlib.sha256(
        json.dumps(legacy_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    assert cache.key_for(request, "nasa_power") != legacy_key


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


def test_nasa_provider_converts_declared_daily_precipitation_rate_to_hourly_mm(
    tmp_path: Path,
) -> None:
    request = _request_for_hours(3)
    timestamps = ("2024123121", "2024123122", "2024123123")
    parameters = {
        nasa_name: {timestamp: 0.0 for timestamp in timestamps}
        for nasa_name in NASA_PARAMETER_MAP.values()
    }
    parameters["PRECTOTCORR"] = {timestamp: 24.0 for timestamp in timestamps}
    payload = {
        "parameters": {"PRECTOTCORR": {"units": "mm/day"}},
        "properties": {"parameter": parameters},
    }
    provider = NasaPowerWeatherProvider(cache_directory=tmp_path, cache_enabled=False)

    dataset = provider._normalize(payload, request)

    assert dataset.hourly["precipitation_mm"].tolist() == pytest.approx([1.0, 1.0, 1.0])
    assert dataset.metadata["source_units"]["PRECTOTCORR"] == "mm/day"
    assert dataset.metadata["normalized_units"]["precipitation_mm"] == "mm/hour"
