# T6 Three-Scenario Comparison

T6 runs `baseline`, `reactive`, and `coating` against one resolved
configuration, one weather dataset, and one immutable exogenous event tape.
All three strategies run through `ScenarioSimulationEngine`; T6 does not add a
second annual simulation loop.

## Run

```powershell
solarclean compare-all-scenarios --config configs/default.yaml
```

`configs/default.yaml` is the sole runtime config. Unit and regression tests
derive short and full-year deterministic fixture variants programmatically in
`tests/config_factory.py`; those variants are not user-facing configuration files.

## Public API

- `solarclean.application.comparison.CompareAllScenarios`
- `CompareAllScenarios.run() -> CompareAllScenariosResult`
- `CompareAllScenarios(..., scenario_order=(...))` supports order-independence
  tests. The output package is still written in canonical order:
  `baseline`, `reactive`, `coating`.

## Output Package

Each run writes `outputs/<run_id>/` with:

- `config_resolved.yaml`
- `comparison_metadata.json` and `metadata.json`
- `weather_hourly.csv`, `clean_energy_hourly.csv`, `daily_clean_energy.csv`
- `event_tape.json`
- `scenario_daily_summary.csv` (per-scenario daily records; includes
  `cumulative_energy_gain_vs_baseline_kwh`, a running total of daily AC energy
  minus the baseline's whose final value equals the scenario's annual
  `energy_gain_vs_baseline_kwh`)
- `scenario_annual_summary.csv`
- `scenario_cost_summary.csv`
- `scenario_events.csv`
- `scenario_ranking.json`
- `recommendation.json`
- `reconciliation_report.json`
- `comparison_daily_energy.png`
- `comparison_cumulative_energy.png`
- `comparison_annual_kpi_breakdown.png`

`scenario_annual_summary.csv` includes shared weather/event checksums, annual
energy, operational totals, baseline-relative energy gain, and T4 financial
KPIs. `scenario_cost_summary.csv` includes component-level cost rows plus the
scenario annual financial totals.

## Reconciliation Checks

- `same_weather_checksum`: all scenarios used the same resolved weather input.
- `same_event_tape_checksum`: all scenarios used the same immutable event tape.
- `*_annual_energy_reconciles_with_daily`: annual clean and actual AC energy
  match summed daily outputs within the explicit kWh tolerance.
- `*_annual_operational_quantities_reconcile_with_daily`: annual operations
  match the daily operational records supplied to T4 economics.
- `reactive_*_reconcile_with_event_log`: reactive inspection and cleaning
  counts match event logs where T2 emits those events.
- `coating_coated_panel_count_reconciles_with_cost_basis`: the coating
  operational panel count matches the T3 coating cost basis.
- `*_economic_totals_reconcile`: T4 output totals are internally consistent
  with cost components and net benefit.
- `*_baseline_relative_energy_gain_uses_annual_ac_energy`: gain versus baseline
  is calculated from annual AC energy fields.
- `assumption_warnings_present`: provisional, fixture, or non-validated
  assumptions are surfaced before recommendation.
- `exactly_one_ranking_produced_for_valid_run` and
  `ranking_sorted_by_net_annual_benefit`: ranking is produced only after the
  prior reconciliation checks pass and is sorted by T4 net annual benefit.

If reconciliation fails, `recommendation.valid` is `false` and the ranking list
is empty. Ties within `RANKING_TOLERANCE_SAR` are reported through
`tied_winners` instead of forcing a winner.
