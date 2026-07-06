# T6 Output Plausibility Audit

Audit target:
`outputs/offline-fixture-full-year-compare-all-scenarios-20260706T074932Z-1c5c6fc5`.

This audit is read-only with respect to T6 behavior. It traces the latest
full-year comparison output back to exported daily/event/cost files, resolved
config, the T5 parameter registry, and T2/T3/T4/T6 code.

## Executive Verdict

The latest T6 output is internally reconciled, but several headline values are
only plausible under very provisional fixture/config assumptions. The major
numbers are not CSV aggregation bugs:

- `reconciliation_report.json` passed all checks, including same weather/event
  tape checks and ranking checks.
- `scenario_daily_summary.csv` has 1,095 rows, equal to 365 days times 3
  scenarios.
- Clean and actual annual energy reconcile from daily outputs for all scenarios
  to floating point tolerance.
- Ranking uses T4 `net_annual_benefit_sar` and is produced after reconciliation
  passes.

Main diagnosis:

- Baseline loss is high because dust soiling compounds to the configured
  soiling floor and receives only one full rain cleaning event; bird droppings
  add a smaller incremental loss.
- Reactive looks very strong because it repeatedly cleans one 100-panel cohort
  at a time, with 2,056 cohort cleaning actions over the year, while only crew
  labor, water, and one drone CAPEX component are priced.
- Coating is weaker than reactive because the fixture weather never reaches the
  configured dew humidity threshold, optical multiplier is 1.0, daytime cooling
  is disabled, and passive cleaning/bird removal therefore never activates.
- Economics are optimistic for all mitigation comparisons because only
  mitigation costs are included, not whole-farm PV CAPEX. Coating annualized
  CAPEX also uses the common 15-year T4 economics life, not the coating
  config/cost-basis 5-year life.

## Evidence Summary

Latest output annual summary:

| scenario | clean kWh | actual kWh | loss % | gain vs baseline kWh | net benefit SAR |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | 6,000,310 | 3,794,787 | 36.7568 | 0 | 758,957 |
| reactive | 6,000,310 | 5,679,819 | 5.3412 | 1,885,032 | 1,082,482 |
| coating | 6,000,310 | 4,862,309 | 18.9657 | 1,067,523 | 957,826 |

Daily reconciliation from `scenario_daily_summary.csv`:

| scenario | clean annual minus daily sum | actual annual minus daily sum | max actual-clean |
| --- | ---: | ---: | ---: |
| baseline | 0.0 | 0.0000000009 | -115.854 kWh |
| reactive | 0.0 | 0.0000000019 | -117.972 kWh |
| coating | 0.0 | 0.0 | -4.214 kWh |

The negative `max actual-clean` values show all scenarios were bounded below
clean energy in this run.

Key source evidence:

- Shared checksums and ranking reconciliation passed in
  `reconciliation_report.json`.
- Weather is synthetic fixture weather, not measured Riyadh weather:
  `comparison_metadata.json` lines 77 and recommendation warning
  `fixture_weather_test_only`.
- T6 ranks on T4 net annual benefit after a preliminary reconciliation pass:
  `src/solarclean/application/comparison.py:305`,
  `src/solarclean/application/comparison.py:319`,
  `src/solarclean/application/comparison.py:1124`,
  `src/solarclean/application/comparison.py:1158`.

## Baseline Diagnosis

Baseline annual loss is 36.76% because the modeled dust ratio compounds down
to the floor, and rain cleaning is too rare in the fixture to reset it.

Mechanism split from baseline cohort records in `scenario_daily_summary.csv`:

| component | kWh | percent of clean |
| --- | ---: | ---: |
| dust-only loss | 2,149,083 | 35.816% |
| incremental bird-dropping loss after dust | 56,441 | 0.941% |
| total loss | 2,205,523 | 36.757% |

So baseline loss is mainly dust, not bird droppings. Event evidence from
`scenario_events.csv`: baseline has 365 `dust_accumulation` events, 8
`heavy_dust_event` events, 745 `bird_dropping_event` events, only 1
`full_rain_cleaning` event, and no partial rain cleaning events.

Config evidence:

- `base_daily_soiling_loss_fraction: 0.0025` in
  `config_resolved.yaml:40`.
- `dust_event_probability: 0.03` in `config_resolved.yaml:45`.
- `minimum_soiling_ratio: 0.55` in `config_resolved.yaml:48`.
- `full_rain_cleaning_threshold_mm: 5.0` and efficiency `0.95` in
  `config_resolved.yaml:53` and `config_resolved.yaml:55`.
- `event_probability_per_cohort_day: 0.01` for birds in
  `config_resolved.yaml:57`.

Code evidence:

- `KimberStyleSoilingModel` subtracts daily dust loss from
  `base_daily_soiling_loss_fraction` and event tape multipliers, then clips to
  `minimum_soiling_ratio`: `src/solarclean/domain/contamination/soiling.py:50`,
  `src/solarclean/domain/contamination/soiling.py:76`,
  `src/solarclean/domain/contamination/soiling.py:109`.
- Rain cleaning only occurs when thresholds are met:
  `src/solarclean/domain/contamination/soiling.py:111` and
  `src/solarclean/domain/contamination/soiling.py:123`.
- Baseline applies event-tape bird additions and cohort dust variation:
  `src/solarclean/domain/simulation/baseline_strategy.py:88` and
  `src/solarclean/domain/simulation/baseline_strategy.py:96`.
- Farm energy multiplies clean energy by dust and `(1 - bird_drop_loss)`:
  `src/solarclean/domain/farm/representation.py:170`.

Monthly baseline clean, actual, and loss:

| month | clean kWh | actual kWh | loss % |
| --- | ---: | ---: | ---: |
| 2025-01 | 445,490 | 421,842 | 5.308 |
| 2025-02 | 433,452 | 372,941 | 13.960 |
| 2025-03 | 518,842 | 405,079 | 21.926 |
| 2025-04 | 528,106 | 366,255 | 30.647 |
| 2025-05 | 554,549 | 336,269 | 39.362 |
| 2025-06 | 537,217 | 292,139 | 45.620 |
| 2025-07 | 555,582 | 300,076 | 45.989 |
| 2025-08 | 550,766 | 296,675 | 46.134 |
| 2025-09 | 512,619 | 275,183 | 46.318 |
| 2025-10 | 491,821 | 263,213 | 46.482 |
| 2025-11 | 438,232 | 234,084 | 46.584 |
| 2025-12 | 433,633 | 231,030 | 46.722 |

Dust evidence: parsed cohort records show the average baseline dust ratio
starts near 0.991, ends near 0.550, and reaches a minimum near 0.547. This is
the floor-dominated plateau visible from June onward.

## Reactive Diagnosis

Reactive reduces annual loss to 5.34% because it repeatedly targets dirty
cohorts for cleaning before the system reaches the deep dust floor. Its annual
actual energy is 5,679,819 kWh, a gain of 1,885,032 kWh against baseline.

Inspection count explanation:

- Config splits 100 cohorts into 7 rotating inspection groups:
  `interval_days: 7` in `config_resolved.yaml:114`.
- Scheduler code creates groups by `range(offset, total_cohorts, interval_days)`
  and returns one group per day:
  `src/solarclean/domain/reactive_cv/scheduler.py:13`,
  `src/solarclean/domain/reactive_cv/scheduler.py:27`,
  `src/solarclean/domain/reactive_cv/scheduler.py:31`.
- With 365 days, offset 0 appears 53 times and offsets 1-6 appear 52 times.
  Group sizes are 15, 15, 14, 14, 14, 14, 14, yielding
  `53*15 + 52*15 + 5*52*14 = 5,215` inspections.
- Drone capacity is 10 cohorts per flight times 4 flights/day, so capacity is
  40 cohorts/day and does not bind this schedule:
  `config_resolved.yaml:118` and `config_resolved.yaml:119`.

Cleaning count explanation:

- `scenario_events.csv` contains 2,056 `reactive_cleaning_action` events and
  2,056 matching `reactive_cleaning_dispatch` events.
- A cleaning action affects exactly one cohort. The farm has 100 cohorts and
  100 panels per cohort, so each cleaning action affects 100 panels:
  `config_resolved.yaml` farm section and
  `src/solarclean/domain/reactive_cv/crew.py:16`.
- The year includes repeated cleaning: 2,056 actions are 205,600 cohort-panel
  cleanings over 100 unique cohort ids.
- Crew config is 8 setup minutes + 25 cleaning minutes = 0.55 crew-hours per
  action and 180 L/action:
  `config_resolved.yaml:138`,
  `config_resolved.yaml:139`,
  `config_resolved.yaml:140`,
  `src/solarclean/domain/reactive_cv/crew.py:36`,
  `src/solarclean/domain/reactive_cv/crew.py:42`.
- Exported totals reconcile: 2,056 actions * 0.55 h = 1,130.8 h, and
  2,056 actions * 180 L = 370,080 L.

Controller-visible logic:

- `CVObservation` carries `_ground_truth_dirty` only for offline metrics and
  says dispatch must never read it:
  `src/solarclean/domain/reactive_cv/observer.py:13`,
  `src/solarclean/domain/reactive_cv/observer.py:21`.
- `StatisticalCVObserver` synthesizes noisy `estimated_loss_fraction` from
  true state, which is acceptable for simulation of an imperfect sensor:
  `src/solarclean/domain/reactive_cv/observer.py:30`,
  `src/solarclean/domain/reactive_cv/observer.py:60`.
- `to_dispatch_signal()` drops ground truth and dispatch uses only estimated
  loss and confidence:
  `src/solarclean/domain/reactive_cv/dispatch.py:24`,
  `src/solarclean/domain/reactive_cv/dispatch.py:41`,
  `src/solarclean/domain/reactive_cv/dispatch.py:60`.

Reactive remains bounded by clean energy. The exported max
`actual_energy_kwh - clean_energy_kwh` is -117.972 kWh, and code also clips
actual energy to clean energy:
`src/solarclean/domain/reactive_cv/strategy.py:288`.

Reactive event diagnostics:

- 5,215 inspections.
- 3,886 detected-dirty inspection results.
- 2,099 inspection results passed dispatch thresholds.
- 2,632 audit-true-actionable inspections.
- 163 missed images.
- 653 cleaning actions were false-positive cleanings by audit metadata. This
  is suspicious but expected from the current noisy CV assumptions:
  false-positive rate, severity noise, and dispatch thresholding.

Reactive cost reconciliation:

| component | basis | amount SAR |
| --- | --- | ---: |
| crew labor | 1,130.8 h * 35 SAR/h | 39,578.00 |
| water | 370,080 L * 0.006 SAR/L | 2,220.48 |
| drone equipment CAPEX | registry value | 100,000.00 |
| annualized CAPEX | T4 CRF over 15 years at 8% | 11,682.95 |
| annual OPEX | crew + water | 41,798.48 |
| total annual cost | annualized CAPEX + OPEX | 53,481.43 |

Notably, exported `drone_flight_hours = 218.7` and
`energy_used_kwh = 307.3` are not priced in this run because the T5 economics
mapping currently supplies only crew-hour and water-liter rates plus drone
equipment CAPEX:
`src/solarclean/domain/economics/calibration.py:79`,
`src/solarclean/domain/economics/calibration.py:85`,
`src/solarclean/domain/economics/calibration.py:87`.
The adapter can price drone flight hours and energy if rates exist, but skips
missing rates:
`src/solarclean/domain/economics/adapters.py:110`,
`src/solarclean/domain/economics/adapters.py:128`,
`src/solarclean/domain/economics/adapters.py:274`.
So the reconciled reactive annual OPEX is 41,798.48 SAR from crew and water
only; drone flight hours and operational energy reconcile as physical
quantities but have zero economic rate in this run.

## Coating Diagnosis

Coating is much weaker than reactive in the daily energy graph because only
the dust accumulation reduction is active. Dew-driven water, passive cleaning,
bird-removal, optical gain, and daytime cooling are all zero in this fixture
run.

Annual coating mechanism totals from `scenario_daily_summary.csv`:

| field | annual total |
| --- | ---: |
| clean reference energy kWh | 6,000,310 |
| final coated energy kWh | 4,862,309 |
| cleanliness effect kWh | -1,138,001 |
| optical effect kWh | 0 |
| temperature effect kWh | 0 |
| condensed water L | 0 |
| potentially collectable water L | 0 |
| actually collected water L | 0 |

Field reconciliation:

- `clean_reference + cleanliness_effect + optical_effect + temperature_effect`
  reconciles to `final_coated_energy_kwh` with max absolute error
  `1.02e-10`.
- `actual_energy_kwh` equals `extension_final_coated_energy_kwh` exactly.
- This directly verifies the requested coating field reconciliation.

Why each mechanism behaved this way:

- Dew/water: fixture max relative humidity is 49.92%, while coating requires
  at least 60% RH. There are 0 hours at or above the threshold. Condensation
  code returns zero when RH is below `minimum_relative_humidity_pct`:
  `config_resolved.yaml:84`,
  `src/solarclean/domain/coating/physics.py:82`.
- Passive dust cleaning: requires positive condensed liters per m2, so it was
  inactive on all days:
  `src/solarclean/domain/coating/physics.py:104`,
  `src/solarclean/domain/coating/physics.py:113`.
- Bird-dropping removal: also requires positive condensed liters per m2:
  `src/solarclean/domain/coating/physics.py:133`.
- Optical effect: `optical_transmittance_multiplier` is 1.0, so optical effect
  is zero:
  `config_resolved.yaml:66`,
  `src/solarclean/domain/coating/physics.py:166`.
- Temperature effect: `daytime_cooling_fraction` is 0.0. The strategy only
  computes cooling benefit during energy-producing hours, so annual
  temperature effect is zero:
  `config_resolved.yaml:77`,
  `src/solarclean/domain/coating/strategy.py:238`,
  `src/solarclean/domain/coating/physics.py:168`.
- Dust reduction: coating applies `dust_accumulation_multiplier: 0.35` to new
  dust accumulation, which slows soiling but does not clean accumulated dust
  without water:
  `config_resolved.yaml:71`,
  `src/solarclean/domain/coating/strategy.py:126`.
- Bird-dropping behavior: bird additions still occur through the shared event
  tape, but coating-assisted bird removal requires condensed water. With no
  condensed water, average coating bird loss remains nonzero: mean 0.0081,
  max 0.0158, ending 0.0158.
- Degradation: effectiveness decays from about 0.9998 to 0.92 over the year,
  from `annual_degradation_fraction / 365`, but this matters only for passive
  cleaning and bird removal in this run:
  `src/solarclean/domain/coating/strategy.py:382`.

Counts:

| coating diagnostic | count |
| --- | ---: |
| dew eligible days / condensed water days | 0 |
| potentially collectable water days | 0 |
| actually collected water days | 0 |
| passive cleaning events | 0 |
| passive cleaning days | 0 |
| meaningful temperature benefit days > 1 kWh | 0 |
| meaningful optical effect days > 1 kWh | 0 |
| meaningful cleanliness effect days > 1 kWh | 365 |
| days where coating did almost nothing, abs(actual-clean) < 1 kWh | 0 |

Monthly baseline versus coating:

| month | baseline actual kWh | baseline loss % | coating actual kWh | coating loss % |
| --- | ---: | ---: | ---: | ---: |
| 2025-01 | 421,842 | 5.308 | 437,252 | 1.849 |
| 2025-02 | 372,941 | 13.960 | 411,792 | 4.997 |
| 2025-03 | 405,079 | 21.926 | 478,176 | 7.838 |
| 2025-04 | 366,255 | 30.647 | 470,458 | 10.916 |
| 2025-05 | 336,269 | 39.362 | 476,820 | 14.017 |
| 2025-06 | 292,139 | 45.620 | 443,562 | 17.433 |
| 2025-07 | 300,076 | 45.989 | 441,187 | 20.590 |
| 2025-08 | 296,675 | 46.134 | 418,593 | 23.998 |
| 2025-09 | 275,183 | 46.318 | 375,206 | 26.806 |
| 2025-10 | 263,213 | 46.482 | 346,379 | 29.572 |
| 2025-11 | 234,084 | 46.584 | 290,240 | 33.770 |
| 2025-12 | 231,030 | 46.722 | 272,645 | 37.125 |

Coating weakness verdict: expected under current fixture weather and
assumptions, not a proven physics-code bug. It is still a major assumption
problem because the synthetic fixture never allows the coating's water-assisted
mechanisms to operate.

## Coating Water

`annual_operational_water_liters` is zero because T3 writes operational water
as `day_water.actually_collected_liters`, not condensed or potentially
collectable water:
`src/solarclean/domain/coating/strategy.py:257`,
`src/solarclean/domain/coating/strategy.py:274`.

Annual totals computed from daily coating extensions:

| water field | annual liters |
| --- | ---: |
| condensed | 0 |
| potentially collectable | 0 |
| actually collected | 0 |

Water revenue is excluded. The T3 single-scenario summary explicitly has
`water_revenue_included: False` and a `water_revenue_not_included` warning in
`src/solarclean/application/use_cases.py:391`,
`src/solarclean/application/use_cases.py:446`,
`src/solarclean/application/use_cases.py:530`. The T6 recommendation warning
set does not currently include a specific water-revenue-excluded warning. In
this fixture run that omission does not change money because actual collected
water is zero, but it should be made explicit before T7.

## Economics Diagnosis

Tariff:

- T4 uses `tariff_sar_per_kwh = 0.2` from the T5 registry:
  `data/calibration/parameter_registry.yaml:592`,
  `data/calibration/parameter_registry.yaml:595`,
  `data/calibration/parameter_registry.yaml:598`.
- The registry source says the tariff must be refreshed before decision use,
  and status is `blocked`:
  `data/calibration/parameter_registry.yaml:599`,
  `data/calibration/parameter_registry.yaml:604`.

Revenue formula is confirmed: `annual_revenue_sar =
actual_energy_kwh * tariff_sar_per_kwh` in
`src/solarclean/domain/economics/engine.py:21`.

Revenue checks:

| scenario | actual kWh | tariff SAR/kWh | revenue SAR |
| --- | ---: | ---: | ---: |
| baseline | 3,794,786.662 | 0.2 | 758,957.332 |
| reactive | 5,679,818.622 | 0.2 | 1,135,963.724 |
| coating | 4,862,309.187 | 0.2 | 972,461.837 |

Why operational capex/opex are zero while economic capex/opex are nonzero:

- `annual_operational_opex_cost` and `annual_operational_capex_cost` are daily
  `OperationalQuantities` fields emitted by strategies. The current strategies
  record physical operations there, not T4 financial components.
- T4 economic costs come from separate `CostComponent` rows in
  `scenario_cost_summary.csv` and the common economic engine:
  `src/solarclean/domain/economics/engine.py:21`,
  `src/solarclean/domain/economics/engine.py:22`,
  `src/solarclean/domain/economics/engine.py:24`,
  `src/solarclean/domain/economics/engine.py:25`.
- This is reconciled but potentially confusing output schema.

CAPEX sources:

- Reactive CAPEX is 100,000 SAR from
  `economics.drone_equipment_cost_sar` in the registry:
  `data/calibration/parameter_registry.yaml:640`,
  `data/calibration/parameter_registry.yaml:643`,
  `src/solarclean/domain/economics/calibration.py:87`.
- Coating CAPEX is 115,000 SAR from the resolved coating config/cost basis, not
  the registry's `coating.capex_sar_per_m2`. It is:
  `20,000 m2 * 4 SAR/m2 material + 20,000 m2 * 1.5 SAR/m2 surface prep + 5,000 SAR fixed equipment + 0 SAR water infrastructure`.
  Evidence:
  `config_resolved.yaml:89`,
  `config_resolved.yaml:98`,
  `config_resolved.yaml:99`,
  `config_resolved.yaml:102`,
  `config_resolved.yaml:107`,
  and `src/solarclean/domain/coating/costs.py:50`,
  `src/solarclean/domain/coating/costs.py:58`,
  `src/solarclean/domain/coating/costs.py:59`,
  `src/solarclean/domain/coating/costs.py:62`.
- The T5 registry has `coating.capex_sar_per_m2 = 20 SAR/m2`, status
  `blocked`, at `data/calibration/parameter_registry.yaml:480` through
  `data/calibration/parameter_registry.yaml:486`, but this value is not what
  produced the 115,000 SAR coating CAPEX. If it were applied directly to
  20,000 m2, it would imply 400,000 SAR before other components.

Coating CAPEX conversions from the actual run:

- 115,000 SAR / 10,000 panels = 11.5 SAR/panel.
- 115,000 SAR / 20,000 m2 = 5.75 SAR/m2.

Annualized CAPEX, ROI, and payback formulas:

- Annualized CAPEX uses capital recovery factor:
  `src/solarclean/domain/economics/engine.py:69`.
- ROI is `net_annual_benefit_sar / total_annual_cost_sar`:
  `src/solarclean/domain/economics/engine.py:27`.
- Payback uses `total_capex_sar / (annual_revenue_sar - annual_opex_sar)` only
  when net benefit is positive:
  `src/solarclean/domain/economics/engine.py:29`,
  `src/solarclean/domain/economics/engine.py:88`.

These ROI/payback values are optimistic because only mitigation CAPEX is
counted. Whole PV farm CAPEX, inverter replacement, fixed O&M, land, spares,
insurance, and financing/tax structure are absent. Baseline has zero annual
cost, so baseline net benefit equals gross revenue and ROI is null.

Additional economic caveats:

- The common T4 economics config uses 15 years and 8% discount rate from the
  registry:
  `comparison_metadata.json:8`,
  `comparison_metadata.json:10`,
  `data/calibration/parameter_registry.yaml:656`,
  `data/calibration/parameter_registry.yaml:672`.
- Coating config/cost basis says coating useful life is 5 years. T4 still
  annualizes coating CAPEX over the common 15-year economic life, lowering
  annualized coating CAPEX. At 8% and 5 years, 115,000 SAR would annualize to
  about 28,803 SAR/year, not 13,435 SAR/year.
- Coating application labor and process energy quantities are in the cost
  basis, but T4 only adds them if optional rates are provided:
  `src/solarclean/domain/economics/adapters.py:222`,
  `src/solarclean/domain/economics/adapters.py:274`.

## Ranking And Recommendation

Ranking is confirmed to use `net_annual_benefit_sar`:

1. reactive: 1,082,482 SAR
2. coating: 957,826 SAR
3. baseline: 758,957 SAR

The decisive margin between reactive and coating is 124,656 SAR. T6 produces
ranking only after reconciliation passes:
`src/solarclean/application/comparison.py:305`,
`src/solarclean/application/comparison.py:319`,
`src/solarclean/application/comparison.py:1124`,
`src/solarclean/application/comparison.py:1158`.

Warning strength is partial:

- Present warnings: fixture/non-live weather, provisional coating costs,
  coating field application not demonstrated, and blocked economics parameters.
- Missing or weak warnings: no specific warning for zero dew eligibility, no
  water-revenue-excluded warning in T6, no warning that whole-farm CAPEX is
  excluded, no warning that drone flight hours/energy are unpriced, and no
  warning that coating CAPEX is annualized over 15 years despite a 5-year
  coating life in the resolved config.

## Schema And Output Issues

1. `scenario_annual_summary.csv` does not include aggregate coating water
   totals or aggregate coating mechanism totals. They are recoverable from
   daily extensions, but T7/T8 consumers should not have to resummarize
   `scenario_daily_summary.csv` to see annual condensed water, optical effect,
   temperature effect, or cleanliness effect.

2. `annual_operational_opex_cost` and `annual_operational_capex_cost` are zero
   while `annual_opex_sar` and `annualized_capex_sar` are nonzero. This is
   technically correct because they come from different contracts, but it is
   confusing in the annual summary.

3. Coating CAPEX provenance is split: the registry has a blocked
   `coating.capex_sar_per_m2` value, but this run uses resolved config
   component costs. The output should say which source governs the run.

4. The recommendation object warns about broad provisional costs but not about
   the specific no-dew/no-water and no-water-revenue behavior observed in this
   run.

## Bugs Found

No arithmetic reconciliation bug was found in the exported T6 package.

Potential integration bug to resolve before relying on economics:

- Coating annualized CAPEX uses the common T4 15-year economics life even
  though the coating config/cost basis says 5 years. This may be intentional
  common-horizon accounting, but if so the output should state it clearly and
  include replacement/reapplication assumptions. If not intentional, it is an
  economics integration bug.

## Suspicious Assumptions, Not Bugs

- Fixture weather is deterministic and never reaches 60% RH, making coating
  water mechanisms impossible.
- Baseline reaches the 0.55 soiling floor and stays near it for half the year
  because the fixture has almost no rain cleaning.
- Reactive dispatch has many false-positive cleanings, but they follow from
  current noisy CV assumptions and still produce a strong result because
  cleaning is cheap and repeated.
- Reactive drone flight hours and energy are recorded but unpriced.
- Coating optical and temperature effects are zero by config.
- Mitigation ROI/payback exclude whole-farm PV CAPEX and fixed O&M.
- The T5 registry economics values are all blocked/non-validated for decision
  use.

## Recommended Fixes Before T7

1. Add annual coating mechanism aggregates to T6 annual output:
   cleanliness, optical, temperature, condensed water, potentially collectable
   water, actually collected water, passive cleaning event count, and dew days.

2. Add explicit T6 warnings for:
   zero dew eligibility, water revenue excluded, whole-farm CAPEX excluded,
   drone flight/energy unpriced, coating config useful life versus T4 economic
   useful life mismatch, and coating registry CAPEX not used.

3. Decide whether coating CAPEX should come from T5 registry
   `coating.capex_sar_per_m2`, resolved config component costs, or a merged
   calibrated cost model. Make the selected source traceable in annual output.

4. Decide how T4 should annualize scenario-specific assets. At minimum,
   reactive drone life and coating useful life should not silently inherit a
   generic 15-year horizon unless that is the stated comparison convention.

5. Add cost rates or explicit zero-cost warnings for reactive drone flight
   hours, compute/energy use, inspection overhead, cleaning equipment, and
   coating application labor/process energy.

6. Add a measured or more Riyadh-like weather run before presenting coating
   conclusions. This fixture is useful for software testing but not for judging
   dew-assisted coating performance.

7. Consider adding sensitivity outputs around CV false positives and cleaning
   cost because reactive wins partly through frequent low-cost repeated
   cleaning.
