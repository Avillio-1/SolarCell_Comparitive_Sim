# T6 Corrected Parameter Run

Date: 2026-07-06

Previous audited run:
`outputs/offline-fixture-full-year-compare-all-scenarios-20260706T074932Z-1c5c6fc5`

Corrected central-v2 run:
`outputs/t6-central-v2-offline-fixture-full-year-compare-all-scenarios-20260706T165840Z-444cad30`

The corrected run passed reconciliation: `reconciliation_report.json` reports
`passed=true` with 27 checks and no failed checks.

## Verdict

The corrected T6 package is ready to feed T7 analytics/dashboard work as a
reconciled engineering baseline. It is not a final investment case because it
still uses fixture weather and provisional/unvalidated economics.

## Old Vs New Results

| scenario | old loss % | new loss % | old actual kWh | new actual kWh | old net benefit SAR | new net benefit SAR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 36.7568 | 25.0112 | 3,794,787 | 4,499,562 | 758,957 | 809,921 |
| reactive | 5.3412 | 6.6815 | 5,679,819 | 5,599,400 | 1,082,482 | 829,767 |
| coating | 18.9657 | 17.5928 | 4,862,309 | 4,944,685 | 957,826 | 734,232 |

Old ranking: `reactive`, `coating`, `baseline`.

New ranking: `reactive`, `baseline`, `coating`.

## Economics Delta

| scenario | old OPEX SAR/y | new OPEX SAR/y | old CAPEX SAR | new CAPEX SAR | old annualized CAPEX SAR/y | new annualized CAPEX SAR/y |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 0 | 0 | 0 | 0 | 0 | 0 |
| reactive | 41,798 | 160,600 | 100,000 | 150,000 | 11,683 | 17,524 |
| coating | 1,200 | 20,000 | 115,000 | 350,000 | 13,435 | 135,812 |

New incremental mitigation economics versus baseline:

| scenario | incremental revenue SAR/y | incremental annual cost SAR/y | incremental net SAR/y | incremental ROI | incremental payback years |
| --- | ---: | ---: | ---: | ---: | ---: |
| reactive | 197,971 | 178,125 | 19,846 | 0.111 | 4.014 |
| coating | 80,122 | 155,812 | -75,689 | -0.486 | 5.821 |

ROI and payback are now explicitly exported as incremental mitigation metrics
through `incremental_roi_vs_baseline`,
`incremental_payback_years_vs_baseline`, and `roi_payback_basis`.

## Reactive Unit Fix

The old output showed `5,215` inspections, which were cohort-level checks and
could be misread as full-farm inspections. The corrected output splits the
units:

| metric | old | new |
| --- | ---: | ---: |
| cohort/block inspection count | 5,215 | 2,435 |
| whole-farm survey equivalents | not exported | 24.35 |
| drone flight hours | 218.7 | 218.4 |
| water liters | 370,080 | 158,100 |

The corrected annual summary exports:

- `annual_operational_whole_farm_survey_count`
- `annual_operational_block_or_cohort_inspection_count`
- `annual_operational_cleaning_dispatch_count`
- `annual_operational_panels_cleaned`
- `annual_operational_drone_flight_hours`
- `annual_operational_water_liters`

## Changed Parameters

| area | old value | corrected value | source/rationale | files changed |
| --- | --- | --- | --- | --- |
| baseline no-clean loss target | implicit severe case, 36.76% output | 25% central, 12-40% range | Audit central target, tuned through soiling config not output hardcoding | `data/calibration/parameter_registry.yaml`, `configs/calibration/central.yaml`, `configs/offline_fixture_full_year.yaml`, `src/solarclean/domain/calibration/registry.py` |
| daily soiling accumulation | `0.0025` | `0.001` | Lands full-year central run near 25% no-clean loss while preserving sparse rain | same as above |
| reactive whole-farm surveys | weekly cohort cycle, exported as 5,215 inspections | 24/year target, 24.35 simulated equivalents | Separates full-farm survey equivalents from cohort checks | `data/calibration/parameter_registry.yaml`, `configs/offline_fixture_full_year.yaml`, `src/solarclean/domain/reactive_cv/strategy.py`, `src/solarclean/application/comparison.py` |
| CV recall | `0.85` old config, registry 0.90 | `0.80` central, 0.60-0.90 range | Audit central CV assumption | registry/config/model defaults |
| cleaning trigger | `0.05` | `0.04`, 0.02-0.07 range | Audit central trigger | registry/config/model defaults |
| water use | `180 L/cohort` or 1.8 L/panel | `150 L/cohort` or 1.5 L/panel | Audit central wet-cleaning use | registry/config/model defaults |
| reactive CAPEX | 100,000 SAR | 150,000 SAR | Audit central equipment allowance | registry/economics bridge |
| reactive overhead | not explicitly priced | 100,000 SAR/y | Covers supervision, software, QA, batteries, logistics, spares, and operational burden | registry/economics bridge |
| drone/energy variable cost | not priced | drone flight hours and energy priced when registry rates exist | Prevents nonzero operations from being economically silent | registry/economics bridge |
| tariff | 0.20 SAR/kWh | 0.18 SAR/kWh, 0.18-0.30 range | Audit industrial/export-like central value | registry/economics bridge |
| central coating mechanism | mixed anti-soiling, dew cleaning, water/cooling | front-surface anti-soiling coating | Central case should not be KAUST/humidity R&D behavior | registry/config/model defaults |
| coating dust reduction | runtime multiplier 0.35 | runtime multiplier 0.70, 30% deposition reduction | Audit translation: 30% reduction means multiplier about 0.70 | registry/config/model defaults |
| coating residual loss target | not recorded | 18% central, 10-28% range | Audit central target, not hardcoded output | registry |
| optical effect | implicit neutral | near neutral, -1% to +2% sensitivity recorded | Conservative central optical assumption | registry/config |
| coating CAPEX | 115,000 SAR | 350,000 SAR | Audit installed coating CAPEX | registry/config |
| coating OPEX reserve | 1,200 SAR/y | 20,000 SAR/y, 5,000-80,000 range | Audit maintenance/reapplication reserve | registry/config |
| coating useful life | annualized through generic 15-year life | 3-year coating life | CAPEX annualization now uses coating useful life | economics contracts/engine/integration |

## Source-Of-Truth Wiring

Corrected central values are stored in:

- `data/calibration/parameter_registry.yaml`
- `configs/calibration/central.yaml`
- `configs/offline_fixture_full_year.yaml`
- `configs/riyadh_2025.yaml`
- model defaults in `src/solarclean/config/models.py`

T6 output traceability now includes:

- `calibration.assumption_set: riyadh_central_v2` in `config_resolved.yaml`
- `calibration_assumption_set` in `comparison_metadata.json`
- key registry assumption records in `recommendation.json`
- configured central-v2 runtime values in `recommendation.json`

## Remaining Warnings

The corrected run still warns for:

- fixture/non-live weather
- provisional/non-validated economics
- unvalidated coating costs
- coating field application not demonstrated

These are expected and should remain visible to T7. The corrected run is
usable as a reconciled T7 input, but decision use still requires measured or
refreshed weather, validated economic quotes, selected coating product data,
and CV validation on representative imagery.
