# Run and interpret a comparison

Use this guide to compare the baseline, reactive cleaning, and coating scenarios with shared
inputs.

## Run the canonical study

```powershell
python -m solarclean.cli.main compare-all-scenarios `
  --config configs/offline_fixture_full_year.yaml
```

The canonical configuration is deterministic and network-free. Its synthetic weather makes it
appropriate for software checks and method demonstrations, not site forecasts.

## Read the package in order

1. Open `config_resolved.yaml` and confirm the site, period, weather provider, and assumption set.
2. Open `reconciliation_report.json`. Stop if `passed` is false.
3. Read `recommendation.json` for `calculation_valid`, `valid`, the evidence tier, warnings,
   exploratory winner, and ties.
4. Use `scenario_annual_summary.csv` for comparable totals and
   `scenario_daily_summary.csv` for timing.
5. Review `scenario_cost_summary.csv` before interpreting the financial ranking.

The ranking is withheld when reconciliation fails. A reconciled exploratory run may still report
an assumption-dependent winner while `valid` remains false. Provisional parameters do not make the
arithmetic invalid, but they limit the claim that can be made from it.

## Test stochastic uncertainty

```powershell
python -m solarclean.cli.main monte-carlo `
  --config configs/offline_fixture_full_year.yaml `
  --trials 100 `
  --base-seed 42
```

Use `--uncertainty-mode parameters_and_seed` to sample supported calibration ranges as well as
event seeds. Monte Carlo reports variation under the modeled uncertainties; it does not correct
missing physics or weak evidence.

## Test parameter sensitivity

```powershell
python -m solarclean.cli.main sensitivity-oneway `
  --config configs/offline_fixture_full_year.yaml `
  --parameter economics.electricity_tariff_sar_per_kwh `
  --steps 5
```

Map the interaction of two registered parameters:

```powershell
python -m solarclean.cli.main sensitivity-winner-map `
  --config configs/offline_fixture_full_year.yaml `
  --parameter-a economics.electricity_tariff_sar_per_kwh `
  --parameter-b coating.capex_sar_per_m2 `
  --grid-steps 5
```

Find a scenario tie within a parameter's registered range:

```powershell
python -m solarclean.cli.main break-even `
  --config configs/offline_fixture_full_year.yaml `
  --parameter coating.capex_sar_per_m2 `
  --scenario-a coating `
  --scenario-b baseline
```

See [calibration and evidence](../concepts/calibration-and-evidence.md) before choosing a range or
interpreting a threshold.

## Compare historical weather years

Multi-year comparison needs a weather source that changes by year. Use the live NASA POWER
configuration, not the deterministic fixture:

```powershell
python -m solarclean.cli.main compare-multi-year `
  --config configs/default.yaml `
  --start-year 2019 `
  --end-year 2025
```

This command requires network access for uncached years and at least three successful weather
years.
