# T3/T6 KAUST Coating Correction Audit

Date: 2026-07-07

## Objective

Correct the T3/T6 coating model so a KAUST-paper-style favorable coating case is not represented only as a weak dust accumulation reducer. The central Riyadh coating case remains conservative, while the KAUST favorable case explicitly models dew-assisted passive self-cleaning and keeps retained dust very low under paper-like weather.

## Old Behavior

The previous central T6 coating assumptions were intentionally conservative:

- `configs/coating_central.yaml` and `configs/offline_fixture_full_year.yaml` used `dust_accumulation_multiplier: 0.70`.
- Passive cleaning was disabled with `passive_cleaning_base_efficiency: 0.0`.
- Coating water/condensation was disabled with `condensation_liters_per_m2_per_c_hour: 0.0`.
- Coating cooling was disabled with `max_surface_cooling_c: 0.0`.

The previous paper endpoint calibration reproduced the 1.5% six-month endpoint mainly by setting `dust_accumulation_multiplier: 0.05357142857142857` in `configs/coating_endpoint_calibration.yaml`, while passive cleaning remained disabled. That made the coating act mostly as a very small dust accumulation multiplier, not as a favorable self-cleaning surface.

## Code Changes

This correction required both configuration and physics-code changes.

- Added a named `kaust_paper_strong` coating preset in `configs/coating_kaust_paper_strong.yaml`.
- Added explicit fixture weather profiles: `riyadh_synthetic`, `riyadh_dry`, and `kaust_paper_favorable`.
- Added optional coating wind/rain shedding parameters to `CoatingPhysicsConfig`.
- Extended passive dust cleaning so dew, wind, and rain mechanisms combine without over-cleaning beyond physically clean.
- Kept bird-dropping removal separately bounded through `bird_removal_efficiency` and `max_bird_removal_fraction_per_day`.
- Added daily diagnostic extensions for dew eligibility, passive cleaning days, retained dust, bird removal days, wind, precipitation, and water diagnostics.
- Added normalized performance, daily loss percent, cumulative loss, soiling/cleanliness, and coating contamination diagnostic plots for coating and T6 comparison runs.

## KAUST Favorable Preset

Key preset values:

- `weather.fixture_profile: kaust_paper_favorable`
- `coating.preset: kaust_paper_strong`
- `dust_accumulation_multiplier: 0.90`
- `passive_cleaning_base_efficiency: 0.110`
- `max_surface_cooling_c: 7.0`
- `condensation_liters_per_m2_per_c_hour: 0.0036`
- `optical_transmittance_multiplier: 1.0`
- `daytime_cooling_fraction: 0.0`
- `annual_degradation_fraction: 0.0` for the six-month validation fixture
- `bird_removal_efficiency: 0.05`
- `max_bird_removal_fraction_per_day: 0.01`

The important distinction is that the KAUST favorable case uses a non-tiny dust multiplier and reaches the paper-style endpoint through daily dew-assisted passive cleaning.

## Fresh Validation Run

Command:

```powershell
.\.venv-x64\Scripts\python.exe -m solarclean.cli.main run-coating --config configs/coating_kaust_paper_strong.yaml
```

Output:

`outputs/coating-kaust-paper-strong-run-coating-20260706T182728Z-5deffc63`

Results:

- Period: 180 days, 2025-01-01 to 2025-06-29.
- Six-month coated endpoint loss: 1.5133776983615066%.
- Six-month baseline endpoint loss: 27.99999999999955%.
- Final coated normalized performance: 0.9848662230163849.
- Final baseline normalized performance: 0.7200000000000045.
- Final average coating dust soiling ratio: 0.9848662230163838.
- Dew eligible days: 180.
- Passive cleaning days: 180.
- Bird removal days: 0, because the validation event tape disables bird-dropping events.
- Period coated energy loss: 1.4228668969566898%.
- Period condensed water: 354711.85004220804 L over the modeled coated farm.
- Actual collected water remains 0.0 L because collection/revenue is not enabled in this validation preset.

Plots produced:

- `coating_daily_energy.png`
- `coating_normalized_performance.png`
- `coating_daily_loss_percent.png`
- `coating_cumulative_loss.png`
- `coating_contamination_diagnostics.png`

## Fresh T6 Comparison Run

Command:

```powershell
.\.venv-x64\Scripts\python.exe -m solarclean.cli.main compare-all-scenarios --config configs/offline_fixture_full_year.yaml
```

Output:

`outputs/t6-central-v2-offline-fixture-full-year-compare-all-scenarios-20260707T051915Z-fe4834d5`

Annual T6 results:

- Baseline annual loss: 25.0111788215%.
- Coating annual loss: 17.5928329143%.
- Reactive annual loss: 6.6814894711%.
- Coating annual actual energy: 4944685.4878633572 kWh.
- Baseline annual actual energy: 4499561.7365096863 kWh.
- Coating gain versus baseline: 445123.7513536708 kWh.

Plots produced:

- `comparison_daily_energy.png`
- `comparison_normalized_performance.png`
- `comparison_daily_loss_percent.png`
- `comparison_cumulative_energy.png`
- `comparison_cumulative_loss.png`
- `comparison_soiling_cleanliness.png`
- `comparison_coating_diagnostics.png`
- `comparison_annual_kpi_breakdown.png`

## Interpretation

The old orange-line weakness was caused by both configuration and physics coverage:

- Conservative Riyadh central configuration disables dew/water/cooling and should not be expected to reproduce KAUST favorable paper behavior.
- The previous paper endpoint calibration hit the target mostly by making dust accumulation tiny, with passive self-cleaning disabled.
- The physics path now supports dew-assisted passive dust shedding plus optional wind/rain shedding, with bird removal still separately limited.

The KAUST favorable normalized performance graph should now behave as expected: coating stays close to 1.0 while baseline declines strongly toward 0.72 over six months. The central T6 graph remains conservative by design.

## Remaining Limitations

- The KAUST favorable weather is a deterministic validation fixture, not measured KAUST or Riyadh weather.
- The central Riyadh preset does not assume guaranteed nightly dew.
- Under `riyadh_dry`, the KAUST strong preset produced zero dew-assisted cleaning in tests and does not get free self-cleaning behavior.
- The paper source values are prompt-quoted calibration anchors, not a fully ingested primary-source dataset.
- Coating costs, water collection, and water revenue remain provisional and outside the coating physics validation.

## 2026-07-17 Water Accounting Update

The dashboard R&D configurations now treat the paper's 128 g/m2/night result as
measured collected yield, not gross condensation. The effective coefficient was
tightened from `0.0036` to `0.0046767 L/m2/C/hour`, which makes the controlled
paper-night fixture reproduce `0.128 L/m2` directly. Collection multipliers are
1.0 in `kaust_paper_strong`; site runs remain weather-gated by humidity, dew
point, and coated-surface temperature. This does not assume a favorable yield on
all 365 nights, assign water revenue, or estimate collection-infrastructure cost.
