# Field-validation dataset contract

The field-validation harness compares the no-intervention baseline's daily AC energy with measured plant production. Weather and production are separate inputs because they have different measurement semantics.

## Measured-production CSV

The CSV must contain:

| Column | Required | Contract |
|---|---|---|
| `timestamp` | Yes | ISO 8601 timestamp with a timezone offset, such as `2025-01-01T13:00:00+03:00`. |
| `measured_ac_energy_kwh` | Yes | Finite, non-negative AC energy delivered during that row's interval, in kWh. |
| `cleaning_event` | No | `0` or `1`; `1` marks a day on which the plant was manually cleaned. |

Hourly and daily rows are accepted. The harness converts timestamps to the configured `site.timezone` and sums interval energy into site-local calendar days. If multiple rows occur on a day, `cleaning_event` is aggregated with a maximum, so any flagged interval marks that day as cleaned. At least 30 calendar days must overlap the simulation.

Example daily data:

```csv
timestamp,measured_ac_energy_kwh,cleaning_event
2025-01-01T00:00:00+03:00,18342.7,0
2025-01-02T00:00:00+03:00,18110.2,1
```

## Weather input

Weather is provided separately through the existing CSV weather provider. Configure `weather.provider: csv` and its column mapping as described in README.md under [Local Riyadh CSV Replacement](../../README.md#local-riyadh-csv-replacement). Do not place irradiance or meteorological columns in the measured-production CSV for this harness.

## Site and simulation configuration

Use a normal SolarClean-DT project YAML. Site coordinates and timezone come from `site`; capacity, tilt, azimuth, and electrical parameters come from `pv_system`; and the `weather` section points to the measured-weather CSV. The harness restricts the baseline run to the first and last local dates found in the measured-production file, so the weather input must cover every hour in that period.

Invoke the harness with a holdout date that was excluded from calibration or tuning:

```powershell
solarclean validate-field `
  --config configs/field-site.yaml `
  --measured-csv data/local_weather/measured_production.csv `
  --holdout-start 2025-10-01
```

The generated `field_validation_report.json` and `field_validation_report.md` separate holdout results from tuning-period diagnostics. Metrics from a period used to tune assumptions are not evidence of predictive accuracy; only untouched holdout results assess predictive performance.

## Data quality: outage days are missing, not zero

Days on which the plant irradiance sensor saw real sun but the meter recorded no positive
AC energy are instrument or inverter outages. They are availability losses, which the
soiling model deliberately does not simulate, and they must be **omitted from the
measured-production CSV** (the harness treats absent days as missing). Leaving them in as
zeros corrupts every metric stage — this exact mistake produced the failed 2026-07-13
PVDAQ-34 demo run. `scripts/convert_field_dataset.py --irradiance-column <poa_column>`
applies this exclusion mechanically and prints the excluded dates. Days whose logger
recorded no electrical channels at all are likewise treated as missing.

## Reference example

A complete worked example against a real site — public-metadata site model, mechanical
outage QC, leakage-safe tuning split, and a passing holdout — is documented in
`docs/audits/pvdaq34_field_validation_2026-07-18.md` with config
`configs/pvdaq34_field_validation.yaml` and datasets under `data/external/`.
