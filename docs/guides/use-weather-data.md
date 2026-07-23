# Use weather data

SolarClean-DT accepts deterministic fixture weather, NASA POWER data, or a local CSV through the
same canonical weather contract.

## Start from the canonical configuration

Keep `configs/offline_fixture_full_year.yaml` unchanged as the reproducible reference. Copy it for
an experiment:

```powershell
Copy-Item configs/offline_fixture_full_year.yaml configs/my-study.yaml
```

On macOS or Linux:

```bash
cp configs/offline_fixture_full_year.yaml configs/my-study.yaml
```

## Use deterministic fixture weather

```yaml
weather:
  provider: fixture
  fixture_profile: riyadh_synthetic
```

Available profiles are:

| Profile | Purpose |
| --- | --- |
| `riyadh_synthetic` | Smooth full-period software fixture with a small rain event |
| `riyadh_dry` | Dry synthetic variant |
| `kaust_paper_favorable` | Favorable coating-mechanism test conditions |

All fixture profiles are synthetic and marked `test_only` in weather metadata.

## Use NASA POWER

```yaml
weather:
  provider: nasa_power
  cache_enabled: true
  cache_directory: data/cache/weather
  missing_data_policy: error
  timeout_seconds: 60
```

Set `site.latitude`, `site.longitude`, `site.timezone`, and
`simulation.target_timezone` consistently. NASA data arrive in UTC and are converted to the site
timezone before daily aggregation. The first uncached request requires network access.

`configs/default.yaml` is the maintained live-weather example.

## Use a measured CSV

```yaml
weather:
  provider: csv
  local_csv_path: data/local_weather/site_weather.csv
  timestamp_column: timestamp
  column_mapping:
    ghi: ghi_w_m2
    dni: dni_w_m2
    dhi: dhi_w_m2
    temperature: temp_air_c
    wind: wind_speed_m_s
    humidity: relative_humidity_pct
    rain: precipitation_mm
  unit_mapping:
    ghi_w_m2: W/m2
    dni_w_m2: W/m2
    dhi_w_m2: W/m2
    temp_air_c: degC
    wind_speed_m_s: m/s
    relative_humidity_pct: percent
    precipitation_mm: mm
```

`column_mapping` maps source columns to canonical fields. `unit_mapping` uses the canonical names
after that rename. Timestamps must contain UTC offsets. Unsupported units, duplicate timestamps,
missing hours, and missing canonical fields are rejected.

Validate the input before a study:

```powershell
python -m solarclean.cli.main validate-weather --config configs/my-study.yaml
```

See the [weather data contract](../reference/weather.md) for required columns and units.
