# Install and run the first comparison

This procedure installs the project and runs a deterministic full-year comparison without network
access.

## Requirements

- Python 3.11 or newer
- A shell opened at the repository root

## Install

```powershell
python -m pip install -e ".[dev]"
```

Verify the command-line interface:

```powershell
python -m solarclean.cli.main --help
```

## Run

```powershell
python -m solarclean.cli.main compare-all-scenarios `
  --config configs/offline_fixture_full_year.yaml
```

The configuration covers the 2025 calendar year in `Asia/Riyadh`. It uses deterministic synthetic
weather and seed-controlled contamination events, so it is suitable for development and
reproducibility checks. It is not measured Riyadh weather.

## Check the result

The command prints the new `outputs/<run_id>/` path. Read these files first:

1. `reconciliation_report.json` — confirms that all scenarios used the same inputs and that daily,
   annual, operational, and economic totals agree.
2. `recommendation.json` — separates calculation validity from the evidence tier.
3. `scenario_annual_summary.csv` — compares energy, operations, and financial metrics.
4. `config_resolved.yaml` — records the exact configuration used.

See [output files](../reference/outputs.md) for the complete package and
[run a comparison](../guides/run-a-comparison.md) for interpretation.

For the canonical fixture, expect `calculation_valid: true` but `valid: false` and
`recommendation_tier: exploratory`. The scenarios reconcile, but synthetic weather and
non-validated parameters do not support a decision-grade recommendation.

## Optional dashboard

```powershell
python -m pip install -e ".[dashboard]"
python -m solarclean.dashboard
```

Open `http://127.0.0.1:8050` and select `offline_fixture_full_year.yaml`. See the
[dashboard guide](../guides/use-dashboard.md) before binding to a shared network.
