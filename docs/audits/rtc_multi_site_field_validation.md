# RTC Multi-Site Field Validation: Two More Passing Holdouts (2026-07-18)

## Summary

After the first passing holdout at NREL PVDAQ system 34 (Las Vegas, hot desert — see
`pvdaq34_field_validation_2026-07-18.md`), the same leakage-safe protocol was applied to
two more NREL PVDAQ systems chosen to span new climates: the nominally identical
Regional Test Center (RTC) "Baseline 6 kW" research systems at Sandia (Albuquerque, NM,
Köppen BSk cold semi-arid) and FSEC (Cocoa, FL, Köppen Cfa humid subtropical). Both
holdouts passed every pre-registered acceptance gate, so the simulation framework
(clean PV + Kimber-style soiling + rainfall recovery) is now validated at three
independent sites across three climates:

| Site | Climate | Window | Holdout days | MAE % | MBE % | R² | Fitted params |
|---|---|---|---:|---:|---:|---:|---:|
| PVDAQ 34, Las Vegas NV | BWh hot desert | 2019 H1 | 61 | 8.42 | −5.41 | 0.388 | 1 |
| PVDAQ 1429, Albuquerque NM | BSk semi-arid | 2017 H1 | 58 | 9.03 | −6.63 | 0.383 | 0 |
| PVDAQ 1403, Cocoa FL | Cfa humid subtropical | 2016 H1 | 59 | 9.43 | +2.80 | 0.766 | 1 |

Acceptance gates (set before any holdout was examined, identical to the PVDAQ-34
protocol): holdout MAE% < 15, |MBE%| < 10, R² > 0.

Authoritative evidence:

- Site models: `configs/pvdaq1403_field_validation.yaml` and
  `configs/pvdaq1429_field_validation.yaml`.
- Compact processed measured and tuning CSVs under `data/external/`, with checksums
  and source attribution in `data/external/README.md`.
- Holdout metrics and protocol decisions recorded in this audit.

Raw PVDAQ day files, NASA POWER caches, and generated validation packages are
reproducible local artifacts and are intentionally excluded from Git.

## Site selection

The OEDI data lake's low-ID (research-instrumented) systems were surveyed via the
public parquet metadata tables (`pvdaq/parquet/{system,site,mount,modules}/`). The RTC
baseline family was chosen because the systems are deliberately near-identical
(22 × Suniva OPT270-60 mono-Si, 5.94 kW DC, fixed tilt 35°, azimuth 180°, two string
inverters, 1-minute logging with plane-of-array irradiance), so cross-site differences
isolate climate rather than hardware. RTC-NV (1423, Henderson) was rejected for
pervasive data gaps; 2016 H1 (1403) and 2017 H1 (1429) are the systems' complete
half-years, deliberately mirroring the PVDAQ-34 January–June window with tuning
January–April and holdout May–June.

## Data QC (extending the PVDAQ-34 rules)

1. **Summed inverter channels.** The RTC day files expose per-inverter AC power
   (`inv1_ac_power`, `inv2_ac_power`) rather than one site channel;
   `scripts/convert_field_dataset.py` now accepts repeated `--power-column` flags and
   sums the channels, dropping any timestamp where a requested channel is missing
   rather than undercounting the site total. Where 1403 also logged a site-level AC
   channel (85 of 182 days), the inverter sum matches it exactly, validating the method.
2. **Partial-logging (short-coverage) exclusion.** Each site had days whose logger ran
   only ~90 minutes, at night (POA never above 0, power at standby tare), which the
   dead-meter rule cannot catch because the POA sensor never saw sun. A new opt-in
   converter rule (`--minimum-coverage-hours 18`) excludes days whose recorded
   electrical samples span under 18 hours, as partial-logging outages. Excluded:
   1403 → 2016-06-17, 2016-06-23; 1429 → 2017-01-17, 2017-05-04, 2017-05-06.
3. After QC: 1403 has 180 usable days (121 tuning), 1429 has 177 (119 tuning); zero
   remaining zero-energy days at either site.

## Tuning protocol (leakage-safe, with a pre-registered spell rule)

As at PVDAQ-34, tuning data are physically separate CSVs
(`pvdaq_system_1403_2016_tuning_janapr.csv`, `pvdaq_system_1429_2017_tuning_janapr.csv`),
at most one parameter (the dry soiling rate) is fitted, and each holdout ran exactly
once after its configuration was frozen.

The PVDAQ-34 estimator — match the simulated to the measured performance-index (PI)
decline slope over dry spells — met non-soiling contamination at both new sites, so one
symmetric rule was set before fitting: **a dry spell qualifies for fitting only if its
measured PI slope is negative and shallower than 1%/day in magnitude**; positive slopes
are physically impossible for soiling and steeper-than-1%/day slopes exceed credible
soiling for these climates by an order of magnitude, so both mark non-soiling processes.

- **1403 (FSEC).** Qualifying spell: 2016-02-25..2016-03-23 (28 d, measured slope
  −0.00050/day). Fitted dry soiling rate **0.0015/day** (simulated/measured slope ratio
  0.964; the simulated spell slope correctly saw-tooths through partial-rain cleanings,
  which is why the fitted rate exceeds the raw slope). The April 2016 crash/recovery
  transient (spells at −2.9%/day then +1.2%/day, PI dipping to 0.70 and recovering
  without a full rain) was excluded by the rule; its cause is unrecorded (candidates:
  local aerosol episode invisible to satellite weather, partial equipment derate).
  0.0015/day sits above typical humid-site annual averages, consistent with the window
  covering Florida's spring pollen season; frequent rain resets keep the absolute
  soiling level small regardless.
- **1429 (SNL).** No spell qualified: every tuning dry spell has a *positive* measured
  PI slope (January snow cover and albedo shocks — the model deliberately has no snow
  physics — plus a winter clean-model underprediction at this 1,658 m site; monthly
  mean measured PI runs 1.16 in January shrinking to 1.08 by April, so the soiling
  signal of ~0.05%/day is buried). The rate therefore **stayed at the literature
  central 0.0005/day** (Mejia & Kleissl 2013 arid-southwest dry-period soiling), making
  this holdout a zero-fitted-parameter test.

Tuning-window metrics at the frozen configurations: 1403 — MAE 8.88%, MBE −4.03%,
R² 0.904 (121 d); 1429 — MAE 13.36%, MBE −10.58%, R² 0.780 (119 d, the winter bias
visible in the MBE).

## Reading the holdouts honestly

- **1403 holdout (2016-05-01..2016-06-30, 59 d): MAE 9.43%, MBE +2.80%, R² 0.766.**
  The high R² is real signal: Florida's convective season produces large genuine
  day-to-day variance that the NASA-POWER-driven model tracks. The small positive bias
  says the model slightly *under*-soils or the weather source slightly over-predicts
  irradiance into the wet season; either way it is well inside the gate.
- **1429 holdout (2017-05-01..2017-06-30, 58 d): MAE 9.03%, MBE −6.63%, R² 0.383.**
  The negative bias continues the winter pattern (clean model underpredicting at
  altitude) but shrinks from −10.6% (tuning, winter-dominated) to −6.6% as the snowless
  clear season arrives. R² 0.38 replicates the PVDAQ-34 finding at almost the same
  value (0.388): in a clear-sky season, measured daily energy varies little, so
  variance-normalized R² is dominated by day-scale satellite-weather noise while MAE%
  stays strong. MAE/MBE are the informative holdout metrics for such seasons.
- **Decline-slope diagnostics over the full half-years are reported, not gated**
  (same stance as the PVDAQ-34 audit took for R²): the full-period slope ratios are
  contaminated by the same non-soiling transients identified during tuning (April
  transient at 1403; snow/winter bias at 1429, where the ratio is negative). The
  soiling-interpretable evidence is the fitting-spell ratio at 1403 (0.964) and the
  three-site MAE/MBE/gate table above.

## Scope and limitations

- Half-year windows; one site per new climate; small (6 kW) research systems. This
  validates the model *framework* across arid, semi-arid, and humid conditions; it
  still does not measure Riyadh's soiling rate, and the Riyadh production
  configuration remains literature-calibrated (`provisional`) until target-farm
  measurements exist (`docs/calibration/open_issues.md`).
- NASA POWER satellite weather is the dominant daily-scale error source everywhere;
  the −5 to −7% dry-season biases at the two high-desert sites (34, 1429) suggest a
  systematic component worth a dedicated weather-source study (ERA5 cross-check).
- The RTC inverter model is not recorded in the public metadata; inverter efficiency
  0.96 (PVWatts default) is a documented assumption, and maintenance/cleaning logs
  were not available (no step anomalies attributable to manual cleaning were visible
  in the residuals at either site).
- The model has no snow physics; January snow days at 1429 remain in the tuning
  overall metrics (they are real days, honestly counted) but could not and did not
  inform the soiling fit.

## Reproduction

The raw 1-minute day files (~60 MB per site-half-year) are not committed; re-fetch them
deterministically from the public OEDI bucket, then convert:

```powershell
# Raw day files
python scripts/download_pvdaq_days.py --system-id 1403 --year 2016 --months 1-6 `
  --output data/external/pvdaq_system_1403_2016_h1_raw
python scripts/download_pvdaq_days.py --system-id 1429 --year 2017 --months 1-6 `
  --output data/external/pvdaq_system_1429_2017_h1_raw

# Convert (QC rules included); month=01..month=06 directories listed explicitly
python scripts/convert_field_dataset.py data/external/pvdaq_system_1403_2016_h1_raw/month=01 `
  data/external/pvdaq_system_1403_2016_h1_raw/month=02 data/external/pvdaq_system_1403_2016_h1_raw/month=03 `
  data/external/pvdaq_system_1403_2016_h1_raw/month=04 data/external/pvdaq_system_1403_2016_h1_raw/month=05 `
  data/external/pvdaq_system_1403_2016_h1_raw/month=06 `
  --output data/external/pvdaq_system_1403_2016_h1_measured.csv --timezone America/New_York `
  --power-column inv1_ac_power__4207 --power-column inv2_ac_power__4213 `
  --irradiance-column poa_irradiance__4214 --minimum-coverage-hours 18
# (tuning CSVs: same commands over month=01..month=04 only; 1429 analogous with
#  inv1_ac_power__4917 / inv2_ac_power__4923 / poa_irradiance__4924, tz America/Denver)

# Holdouts (already run once; re-running reproduces the archived reports)
python -m solarclean.cli.main validate-field --config configs/pvdaq1403_field_validation.yaml `
  --measured-csv data/external/pvdaq_system_1403_2016_h1_measured.csv --holdout-start 2016-05-01
python -m solarclean.cli.main validate-field --config configs/pvdaq1429_field_validation.yaml `
  --measured-csv data/external/pvdaq_system_1429_2017_h1_measured.csv --holdout-start 2017-05-01
```
