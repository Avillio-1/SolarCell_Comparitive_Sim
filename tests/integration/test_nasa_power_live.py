from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from solarclean.domain.environment.weather import CANONICAL_WEATHER_COLUMNS, WeatherRequest
from solarclean.infrastructure.weather.nasa_power import NasaPowerWeatherProvider


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("SOLARCLEAN_RUN_NETWORK_TESTS") != "1",
    reason="set SOLARCLEAN_RUN_NETWORK_TESTS=1 to call NASA POWER",
)
def test_live_nasa_power_retrieval(tmp_path):
    request = WeatherRequest(
        latitude=24.7136,
        longitude=46.6753,
        start=datetime(2025, 1, 1, tzinfo=ZoneInfo("Asia/Riyadh")),
        end=datetime(2025, 1, 1, 23, tzinfo=ZoneInfo("Asia/Riyadh")),
        target_timezone="Asia/Riyadh",
        variables=frozenset(CANONICAL_WEATHER_COLUMNS),
    )

    dataset = NasaPowerWeatherProvider(cache_directory=tmp_path).load(request)

    assert len(dataset.hourly) == 24
    assert dataset.metadata["provider"] == "nasa_power"
