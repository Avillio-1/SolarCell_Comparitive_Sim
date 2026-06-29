from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from solarclean.config.models import PVSystemConfig
from solarclean.domain.environment.weather import WeatherDataset


@dataclass
class CleanEnergyProfile:
    hourly: pd.DataFrame
    daily: pd.DataFrame
    annual_clean_energy_kwh: float
    metadata: dict[str, object]


class PVPowerModel(Protocol):
    def calculate_hourly(
        self,
        weather: WeatherDataset,
        system: PVSystemConfig | None = None,
    ) -> CleanEnergyProfile:
        """Calculate clean hourly and daily PV energy from canonical weather."""
