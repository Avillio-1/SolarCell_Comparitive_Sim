from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib

from solarclean.config.models import PVSystemConfig
from solarclean.domain.environment.weather import WeatherDataset
from solarclean.domain.pv.model import CleanEnergyProfile


class PVWattsPowerModel:
    """Transparent pvlib PVWatts-based clean-energy model."""

    def calculate_hourly(
        self,
        weather: WeatherDataset,
        system: PVSystemConfig | None = None,
    ) -> CleanEnergyProfile:
        system_config = system or PVSystemConfig()
        coordinates = weather.metadata.get("coordinates")
        if isinstance(coordinates, dict):
            latitude = float(coordinates.get("latitude", 24.7136))
            longitude = float(coordinates.get("longitude", 46.6753))
            altitude = float(coordinates.get("elevation_m", 0.0) or 0.0)
        else:
            latitude = 24.7136
            longitude = 46.6753
            altitude = 0.0
        index = pd.DatetimeIndex(weather.hourly.index)
        solar_position = pvlib.solarposition.get_solarposition(
            time=index,
            latitude=latitude,
            longitude=longitude,
            altitude=altitude,
        )
        poa = pvlib.irradiance.get_total_irradiance(
            surface_tilt=system_config.tilt_degrees,
            surface_azimuth=system_config.azimuth_degrees,
            solar_zenith=solar_position["apparent_zenith"],
            solar_azimuth=solar_position["azimuth"],
            dni=weather.hourly["dni_w_m2"],
            ghi=weather.hourly["ghi_w_m2"],
            dhi=weather.hourly["dhi_w_m2"],
        )
        poa_global = poa["poa_global"].clip(lower=0.0).fillna(0.0)
        if system_config.module_temperature_model == "pvsyst_cell":
            temp_cell = pvlib.temperature.pvsyst_cell(
                poa_global=poa_global,
                temp_air=weather.hourly["temp_air_c"],
                wind_speed=weather.hourly["wind_speed_m_s"],
            )
        else:
            temperature_parameters = pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS["sapm"][
                "open_rack_glass_glass"
            ]
            temp_cell = pvlib.temperature.sapm_cell(
                poa_global=poa_global,
                temp_air=weather.hourly["temp_air_c"],
                wind_speed=weather.hourly["wind_speed_m_s"],
                **temperature_parameters,
            )
        dc_power = pvlib.pvsystem.pvwatts_dc(
            effective_irradiance=poa_global,
            temp_cell=temp_cell,
            pdc0=system_config.total_dc_capacity_w,
            gamma_pdc=system_config.gamma_pdc_per_c,
        )
        dc_power = (
            (pd.Series(dc_power, index=index) * system_config.combined_system_loss_multiplier)
            .clip(lower=0.0)
            .fillna(0.0)
        )
        inverter_pdc0 = system_config.total_dc_capacity_w / system_config.dc_ac_ratio
        ac_power = pvlib.inverter.pvwatts(
            pdc=dc_power,
            pdc0=inverter_pdc0,
            eta_inv_nom=system_config.inverter_efficiency,
        )
        ac_power = pd.Series(ac_power, index=index).clip(lower=0.0).fillna(0.0)
        energy_kwh = ac_power / 1000.0
        hourly = pd.DataFrame(
            {
                "poa_global_w_m2": poa_global,
                "cell_temperature_c": temp_cell,
                "clean_dc_power_w": dc_power,
                "clean_ac_power_w": ac_power,
                "clean_ac_energy_kwh": energy_kwh,
                "clean_ac_energy_per_panel_kwh": energy_kwh / system_config.panel_count,
            },
            index=index,
        )
        hourly[["clean_dc_power_w", "clean_ac_power_w", "clean_ac_energy_kwh"]] = hourly[
            ["clean_dc_power_w", "clean_ac_power_w", "clean_ac_energy_kwh"]
        ].where(lambda values: values >= 0.0, 0.0)
        if not np.isfinite(hourly.select_dtypes(include=["number"]).to_numpy()).all():
            raise ValueError("PVWatts calculation produced non-finite values")
        daily = (
            hourly.groupby(pd.DatetimeIndex(hourly.index).date)["clean_ac_energy_kwh"]
            .sum()
            .to_frame()
        )
        daily.index.name = "date"
        annual_energy = float(daily["clean_ac_energy_kwh"].sum())
        metadata: dict[str, object] = {
            "model": "pvlib_pvwatts",
            "pvlib_version": pvlib.__version__,
            "panel_count": system_config.panel_count,
            "panel_capacity_w": system_config.panel_capacity_w,
            "total_dc_capacity_w": system_config.total_dc_capacity_w,
            "tilt_degrees": system_config.tilt_degrees,
            "azimuth_degrees": system_config.azimuth_degrees,
            "inverter_efficiency": system_config.inverter_efficiency,
            "dc_ac_ratio": system_config.dc_ac_ratio,
            "gamma_pdc_per_c": system_config.gamma_pdc_per_c,
            "module_temperature_model": system_config.module_temperature_model,
            "loss_wiring_fraction": system_config.loss_wiring_fraction,
            "loss_mismatch_fraction": system_config.loss_mismatch_fraction,
            "loss_connections_fraction": system_config.loss_connections_fraction,
            "loss_nameplate_fraction": system_config.loss_nameplate_fraction,
            "loss_lid_fraction": system_config.loss_lid_fraction,
            "loss_availability_fraction": system_config.loss_availability_fraction,
            "combined_system_loss_multiplier": system_config.combined_system_loss_multiplier,
            "weather_metadata": weather.metadata,
        }
        return CleanEnergyProfile(
            hourly=hourly,
            daily=daily,
            annual_clean_energy_kwh=annual_energy,
            metadata=metadata,
        )
