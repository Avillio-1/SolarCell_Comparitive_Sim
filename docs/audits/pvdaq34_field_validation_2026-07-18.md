# PVDAQ-34 Field Validation: Diagnosis And First Passing Holdout (2026-07-18)

## Summary

The 2026-07-13 demo field-validation run against NREL PVDAQ system 34 reported
catastrophic metrics (overall R² −1.19, holdout MBE +626 kWh/day). This audit found the
failure was dominated by data quality and site-model configuration, not by the soiling
physics. After mechanical data QC, a metadata-correct site model, and a leakage-safe
tuning protocol, the simulator passed its first real-data holdout:

| Holdout (61 untouched days, 2019-05-01 to 2019-06-30) | Value |
|---|---:|
| MAE | 67.2 kWh/day (8.42%) |
| RMSE | 82.0 kWh/day (10.27%) |
| MBE | −43.2 kWh/day (−5.41%) |
| R² | 0.388 |
| Dry-spell PI decline slope, simulated / measured (full period) | 1.0002 |

Authoritative evidence is the frozen site configuration, the processed measured and
tuning CSVs, and the metrics recorded in this audit. Their checksums and source
attribution are listed in `data/external/README.md`. Generated validation packages
under `data/external/pvdaq_34_validation_outputs/` and NASA POWER cache responses are
reproducible local artifacts and are intentionally excluded from Git.

## Why the demo run failed

1. **Dead meter in the holdout.** From 2019-02-13 through 2019-03-14 the site's
   plane-of-array sensor recorded full sun (peaks ~990–1076 W/m²) while AC power sat at
   the −200 W standby tare. Every day of the demo's holdout (starting 2019-02-15) was in
   this outage, so the "+626 kWh/day holdout bias" was the simulator being compared
   against a dead logger. The equal MAE and MBE and the null MAE% in the demo holdout
   row are the fingerprint of an all-zero measured window.
2. **Zero days polluting all stages.** 16 of the demo's 59 days were outage zeros,
   dragging overall R² to −1.19 and inflating the measured decline slope (the "27×
   too-slow soiling" finding was mostly the measured series crashing to zero, not
   soiling).
3. **Unarchived site model.** The demo's config was not committed, so capacity, tilt,
   and loss assumptions could not be audited.

## Fixes

1. **Mechanical outage exclusion in the converter** (`scripts/convert_field_dataset.py`):
   a day with zero positive AC energy while the POA sensor peaked above 200 W/m² is an
   instrument/inverter outage (an availability loss the soiling model deliberately does
   not simulate) and is excluded, with excluded dates printed for the record. Days whose
   logger recorded no electrical channels at all are treated as missing, not zero.
   Applied to Jan–Jun 2019, this excluded the 29-day outage plus 4 no-logger days,
   leaving 148 live days.
2. **Extended dataset.** March–June 2019 day files were downloaded from the public OEDI
   data lake (`s3://oedi-data-lake/pvdaq/csv/pvdata/system_id=34/year=2019/`), extending
   the series so a holdout could be placed on live data:
   `data/external/pvdaq_system_34_2019_h1_measured.csv`.
3. **Metadata-correct site model** (`configs/pvdaq34_field_validation.yaml`), built from
   the public PVDAQ system metadata: 611 × Sharp NU-U240F1 240 W (146.64 kW DC), Satcon
   135 kW central inverter (dc_ac_ratio 1.0862), fixed tilt 11.2°, azimuth 180°,
   Las Vegas (36.1952, −115.1582, BWh hot desert). Documented assumptions: Satcon-class
   inverter efficiency 0.955, mono-Si gamma −0.45%/°C, and +4% aging in the nameplate
   loss (~0.5%/yr over 8.6 years, Jordan & Kurtz median). Dust-storm events, stochastic
   daily noise, and bird events are disabled: only the deterministic soiling/rain physics
   are being validated.
4. **CLI repair.** `solarclean validate-field` could not run at all under the pinned
   typer version (`RuntimeError: Type not yet supported: datetime.date`); the
   `--holdout-start` option now parses an ISO date string.

## Tuning protocol (leakage-safe)

- Tuning window: 2019-01-01 to 2019-04-30 (87 live days), supplied to the harness as a
  physically separate CSV (`pvdaq_system_34_2019_tuning_janapr.csv`) so May–June could
  not influence any tuning metric.
- One parameter was fitted on the tuning window: the dry soiling rate, raised from the
  initial literature guess 0.0005/day to **0.0033/day** to match the measured dry-spell
  decline slope (final tuning-window slope ratio 0.954, MBE +0.71%, R² 0.875). All other
  parameters stayed at metadata-derived or literature-default values.
- The fitted 0.0033/day lies inside the parameter registry's literature band for arid
  sites (0.0005–0.006/day), independently corroborating that band.
- The holdout (2019-05-01 onward) was run exactly once, after the configuration was
  frozen.

## Reading the holdout honestly

- Daily MAE 8.4% and |MBE| 5.4% are within the typical daily-error range for PV models
  driven by satellite weather (NASA POWER) rather than on-site irradiance.
- The soiling *dynamics* — the quantity this project actually models — reproduce the
  measured dry-spell performance-index decline at ratio 1.0002 across the full period
  (4 dry spells, 119 days).
- Holdout R² (0.39) is much lower than tuning R² (0.88) **because May–June Las Vegas is
  a clear-sky season**: measured daily energy varies little, so variance-normalized R²
  is dominated by day-scale weather-model noise even though MAE% *improved* relative to
  the tuning window. MAE/MBE are the informative holdout metrics here.
- The −5.4% holdout bias indicates the model soils slightly too aggressively into the
  dry summer (or NASA POWER slightly underestimates summer irradiance at this site).

## Scope and limitations

- One site, one half-year, one climate (Mojave hot desert). This validates the model
  *framework* (clean PV + Kimber-style soiling + rain recovery) at an arid reference
  site; it does not measure Riyadh's soiling rate.
- The Riyadh production configuration remains literature-calibrated (`provisional`).
  Moving it to `validated` still requires target-farm measurements, as recorded in
  `docs/calibration/open_issues.md`.
- Possible unrecorded manual cleanings at the school site would appear as model
  underprediction after the event; none were visible as step anomalies in the residuals,
  but maintenance logs were not available.

## Acceptance criteria used

Set during protocol design, before the holdout was examined: holdout MAE% below 15%,
holdout |MBE%| below 10%, and holdout R² above 0 — all in line with common daily
PV-validation practice for satellite-weather-driven models. All three were met (8.42%,
5.41%, 0.388). The decline-slope ratio (1.0002) and the tuning/holdout R² contrast are
reported transparently rather than gated.
