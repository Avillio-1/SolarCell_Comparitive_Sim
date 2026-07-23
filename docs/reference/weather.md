# Weather data contract

Every provider returns a `WeatherDataset` with a timezone-aware hourly index and these numeric
columns:

| Column | Normalized unit | Constraint |
| --- | --- | --- |
| `ghi_w_m2` | W/m² | Non-negative |
| `dni_w_m2` | W/m² | Non-negative |
| `dhi_w_m2` | W/m² | Non-negative |
| `temp_air_c` | °C | −90 through 70 |
| `wind_speed_m_s` | m/s | Non-negative |
| `relative_humidity_pct` | % | 0 through 100 |
| `precipitation_mm` | mm/hour | Non-negative |

Timestamps must be unique and monotonic. The standard validation path requires every hour from the
inclusive configured start through end.

## Provider behavior

| Provider | Behavior |
| --- | --- |
| `fixture` | Generates deterministic synthetic data and marks it `test_only` |
| `nasa_power` | Retrieves UTC hourly data, normalizes fields, converts timezone, and optionally caches |
| `csv` | Renames configured columns, converts supported units, and applies the missing-data policy |

NASA-specific names and HTTP behavior do not cross the infrastructure boundary.

## CSV mappings

`column_mapping` maps source names to canonical names. `unit_mapping` uses canonical names after
that rename:

```yaml
weather:
  provider: csv
  local_csv_path: data/local_weather/site_weather.csv
  timestamp_column: timestamp
  column_mapping:
    air_temp_f: temp_air_c
    wind_kph: wind_speed_m_s
  unit_mapping:
    temp_air_c: fahrenheit
    wind_speed_m_s: km/h
```

All seven canonical columns must exist after renaming. Supported conversions include Fahrenheit to
Celsius, km/h to m/s, and cm to mm.

## Metadata

Weather metadata records provider, coordinates, requested date range, normalized units, provenance,
and a checksum. NASA caches also record retrieval details; fixture metadata records its profile and
`test_only: true`.

Daily rainfall and humidity are aggregated after conversion to the configured site timezone.
