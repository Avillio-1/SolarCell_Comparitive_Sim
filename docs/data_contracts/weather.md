# Weather Data Contract

Weather data is represented by `WeatherDataset`.

## Index

- Type: `pandas.DatetimeIndex`
- Frequency: hourly input expected
- Timezone: required
- Default target timezone: `Asia/Riyadh`
- Duplicate timestamps: rejected

## Required Columns

| Column | Unit | Description |
| --- | --- | --- |
| `ghi_w_m2` | W/m2 | Global horizontal irradiance |
| `dni_w_m2` | W/m2 | Direct normal irradiance |
| `dhi_w_m2` | W/m2 | Diffuse horizontal irradiance |
| `temp_air_c` | deg C | Ambient air temperature |
| `wind_speed_m_s` | m/s | Wind speed |
| `relative_humidity_pct` | percent | Relative humidity from 0 to 100 |
| `precipitation_mm` | mm/hour | Hourly precipitation depth |

All canonical values must be numeric and finite. Irradiance, wind speed, and precipitation must be non-negative.

## Metadata

Weather metadata records provider name, retrieval timestamp, coordinates, date range, variables, source units, normalized units, and checksum where available.
