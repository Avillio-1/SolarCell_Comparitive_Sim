# Humid-Desert Dew Cementation and Coating Humidity Response

Scope: the dry-vs-humid desert experiment (`configs/riyadh_dry_desert.yaml` vs
`configs/dammam_humid_desert.yaml`, runner `scripts/compare_dry_vs_humid.py`).
All mechanisms below are **disabled by default** (`soiling.dew_cementation.enabled: false`,
`humidity_cooling_mode: threshold`, condensation rate `0.0`), so the frozen
`riyadh_central_v2` runs and every existing config reproduce their historical
results exactly.

## Motivation

Coastal Gulf deserts (Dammam, Doha, Abu Dhabi) share Riyadh's dust loading but
add frequent high-humidity nights. Field studies in Qatar/UAE report that
overnight dew wets deposited dust which then dries into a cemented crust:
soiling accumulates faster, adheres harder, and natural (rain) cleaning becomes
less effective. A superhydrophobic coating (contact angle ~167°) prevents the
cementing water film, so the coating's value proposition is expected to differ
between dry and humid desert sites. The previous model read humidity only for
coating cooling; baseline soiling ignored it entirely, which would understate
the coating's advantage at humid sites.

## Mechanism 1: dew-cementation adhesion (uncoated surfaces)

Daily dew risk is interpolated from the day's **peak** relative humidity
(nighttime maximum from the hourly weather; the daily mean is a fallback for
legacy callers):

- risk 0 at `onset_relative_humidity_pct` (default 75%),
- risk 1 at `saturation_relative_humidity_pct` (default 95%).

On dew days the daily deposition retained rises by up to
`max_soiling_rate_multiplier` (default 1.5× at full risk). The extra retention
is emitted as a distinct `dew_cementation_adhesion` event so scenarios can
treat it separately from ordinary `dust_accumulation`.

A crust state (`cementation_index`, 0..1) relaxes toward the day's dew risk
over `memory_days` (default 10). Rain cleaning efficiency (partial and full)
is multiplied by `1 - max_rain_efficiency_penalty * index` (default penalty
0.5 at full crust). A full-cleaning rain (≥ 5 mm) washes the crust away and
resets the index.

## Mechanism 2: coating suppression

Coated cohorts suppress `cementation_suppression_fraction` (default 0.9) of
both the extra adhesion deposition and the rain-efficiency penalty, scaled by
current coating effectiveness (so the protection degrades as the coating
degrades). The ordinary `dust_accumulation_multiplier` (0.60) continues to
apply only to non-cementation deposition.

## Mechanism 3: dew condensation and humidity-cooling curve

The experiment configs enable the pre-existing condensation model with values
anchored to the KAUST coating paper (Dang et al., *Energy Environ. Mater.*
2026, 10.1002/eem2.70350) and the project's T3 calibration audit
(`docs/audits/t3_t6_kaust_coating_correction.md`):

- `condensation_liters_per_m2_per_c_hour: 0.0036` — the audit's value
  calibrated to the paper's measured dew yield of 128 g/m² per night
  (paper Fig 5h; also the source of the 0.128 L/m² water-factor
  normalization in the passive-cleaning code).
- `minimum_relative_humidity_pct: 65` — the paper's condensation onset
  (Fig 3c: condensation occurs from ~65% RH at 20 °C ambient); the
  surface-below-dew-point check supplies the finer thermodynamics.
- `humidity_cooling_mode: smooth` with `humidity_cooling_floor_fraction: 0.70`
  — the paper predicts cooling declines only modestly with humidity
  (8.0 °C at 50% RH → 6.1 °C at 90% RH, Fig 3a) and field data show
  condensation-enabling cooling on 90%+ RH nights, so the humidity factor
  floors at 0.70 instead of decaying to zero at saturation.
- `max_surface_cooling_c: 7.0`, `daytime_cooling_fraction: 0.0` — audit
  values; the paper attributes the coated panel's field gain to cleanliness,
  not daytime sub-ambient cooling.
- `optical_transmittance_multiplier: 1.014` — the coated glass measures 1.4%
  *higher* solar transmittance than uncoated glass (anti-reflective
  nanostructure, paper Fig 2e).
- `dust_accumulation_multiplier: 0.90` with
  `passive_cleaning_base_efficiency: 0.11` — per the audit, the coating's
  anti-soiling benefit is dew-shedding-driven, not a large flat deposition
  discount; this pairing reproduces the paper's 6-month field endpoints
  (~1.5% coated vs ~28% uncoated loss) under paper-like weather.

## Experiment design

The two configs are identical (farm, calibration set, seeds, coating,
economics, humidity physics) except `site.name`, `site.latitude`,
`site.longitude`, and `run_id_prefix`. Weather comes live from NASA POWER per
coordinate, so every outcome difference is attributable to location weather:
Riyadh rarely crosses the 75% nighttime-RH onset; Dammam does routinely.

## Known limitations

- Reactive CV uses the configured statistical observer in the site comparison;
  perfect-information mode remains available only as an explicit benchmark.
- Crew manual-cleaning efficiency is reduced by the same accumulated-crust
  multiplier used for rain cleaning. Crew calendar, heat, storm, and water-
  availability gates remain outside this experiment.
- Heavy dust-event probability remains the flat Riyadh-calibrated 3%/day at
  both sites (acceptable within the Gulf; not valid elsewhere).
- Cementation parameters (1.5× retention, 0.5 rain penalty, 10-day memory,
  0.9 suppression) are provisional engineering estimates, not yet
  literature-calibrated; see `docs/assumptions/calibration_todo.md` workflow.
- Bird-dropping behaviour is humidity-independent.
