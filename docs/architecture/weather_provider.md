# Weather Provider Architecture

The domain accepts weather through `WeatherProvider.load(request) -> WeatherDataset`.

`WeatherRequest` contains:

- latitude and longitude;
- optional elevation;
- timezone-aware start and end datetimes;
- target timezone;
- requested canonical variables.

`WeatherDataset` contains a normalized hourly `pandas.DataFrame` with a timezone-aware `DatetimeIndex`.

Required canonical columns:

- `ghi_w_m2`
- `dni_w_m2`
- `dhi_w_m2`
- `temp_air_c`
- `wind_speed_m_s`
- `relative_humidity_pct`
- `precipitation_mm`

## Providers

`FixtureWeatherProvider` generates small deterministic test-only data and never calls the network.

`CsvWeatherProvider` reads measured station data with configurable source-column and unit mappings. It rejects missing canonical fields, duplicate timestamps, timezone-free timestamps, and unsupported unit conversions.

`NasaPowerWeatherProvider` isolates NASA-specific parameters and response structures. It requests hourly UTC data, maps NASA fields into canonical columns, converts to the requested timezone, validates the result, and caches raw plus normalized data.

The simulation and PV code depend only on the canonical contract, so switching `weather.provider` from `nasa_power` to `csv` or `fixture` does not require domain changes.
