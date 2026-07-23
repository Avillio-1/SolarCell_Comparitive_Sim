# Validation method

Validation is layered so software correctness, numerical consistency, model behavior, and external
evidence are not confused.

| Layer | Check | Establishes |
| --- | --- | --- |
| Configuration | Strict schema and cross-field validation | Inputs are coherent |
| Weather | Coverage, timezone, units, ranges, gaps, duplicates | Provider output meets the contract |
| Numerical | Finite/non-negative energy and state bounds | Calculations respect invariants |
| Equivalence | Representative and homogeneous cohort agreement | Farm aggregation is consistent |
| Reconciliation | Shared checksums and daily/annual/economic totals | Scenario comparison is fair and arithmetically consistent |
| Regression | Offline unit and golden tests | Known behavior has not drifted unexpectedly |
| Field holdout | Predicted versus measured daily AC energy | Framework performance at external sites |
| Robustness | Monte Carlo, sensitivity, break-even, multi-year runs | Dependence on modeled uncertainty |

No single layer validates the entire decision model.

## Internal validation

Run the deterministic internal checks with:

```powershell
python -m solarclean.cli.main validate-phase-3-5 `
  --config configs/offline_fixture_full_year.yaml
```

The reports cover weather, clean and actual energy, farm equivalence, event-tape identity, runtime,
memory, and output size. Because the weather is synthetic, passing these checks is software
evidence rather than field validation.

## Field-validation protocol

The external studies use:

1. Public measured production and independently sourced weather.
2. Mechanical exclusion of logger or inverter outage days.
3. A physically separate January–April tuning set.
4. At most one fitted soiling parameter.
5. An untouched May–June holdout run after configuration freeze.
6. Pre-registered gates: MAE below 15%, absolute MBE below 10%, and R² above zero.

MAE and MBE are primary daily-energy metrics. R² is retained but interpreted cautiously during
clear-sky periods with little measured variance.

## Claim boundary

The holdouts support the clean-PV plus soiling/rain framework at three external sites. They do not
validate Riyadh weather, target-farm soiling, CV operations, coating lifetime, or mitigation
economics.
