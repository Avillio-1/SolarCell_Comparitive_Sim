# Output reference

Each command creates `outputs/<run_id>/`. The run ID contains the configuration prefix, command,
UTC timestamp, and a short random suffix.

## Common provenance

| File | Content |
| --- | --- |
| `config_resolved.yaml` | Fully resolved configuration used by the run |
| `metadata.json` | Command, code version, Git state, site, weather, and calibration provenance |
| `summary.json` | Machine-readable command summary |
| `summary.txt` | Plain-text summary when the command provides one |
| `weather_hourly.csv` | Normalized input weather |
| `clean_energy_hourly.csv` | Hourly POA, temperature, DC, and AC results |
| `daily_clean_energy.csv` | Daily clean AC energy |

Not every command writes every common file.

## Individual simulations

| Command | Additional files |
| --- | --- |
| `run-baseline` | `daily_results.csv`, `cohort_daily_results.csv`, `events.csv`, `event_tape.json`, `diagnostic_plot.png` |
| `run-reactive` | `scenario_daily_results.csv`, `scenario_events.csv`, `scenario_summary.json`, `reactive_comparison_summary.json` |
| `run-coating` | Scenario result files, `coating_comparison_summary.json`, coating diagnostic plots |
| `validate-phase-3-5` | `phase35_*_report.json`, `phase35_event_tape.json`, `phase35_summary.json` |
| `validate-field` | `field_validation_report.json`, `field_validation_report.md` |

## Three-scenario comparison

| File | Content |
| --- | --- |
| `comparison_metadata.json` | Shared input checksums and traceability |
| `daily_weather_diagnostics.csv` | Daily irradiance, temperatures, and rainfall |
| `event_tape.json` | Shared exogenous contamination inputs |
| `scenario_daily_summary.csv` | One row per scenario and day |
| `scenario_annual_summary.csv` | Energy, operations, economics, and shared checksums |
| `scenario_cost_summary.csv` | Cost components, sources, status, and reconciled totals |
| `scenario_events.csv` | Ordered events for all scenarios |
| `reconciliation_report.json` | Input-fairness and arithmetic checks |
| `scenario_ranking.json` | Ranking emitted after calculation reconciliation |
| `recommendation.json` | Calculation validity, evidence validity and tier, warnings, winner, and ties |
| `comparison_*.png` | Energy, loss, cleanliness, coating, and KPI diagnostics |

Read `reconciliation_report.json` before the ranking. A failed check results in an empty ranking
and invalid recommendation.

`scenario_daily_summary.csv` includes
`cumulative_energy_gain_vs_baseline_kwh`; its final value equals the period energy gain reported in
the annual summary.

## Robustness analyses

| Command | Main artifacts |
| --- | --- |
| `compare-multi-year` | `multi_year_scenario_summary.csv`, `multi_year_summary.json`, `multi_year_net_benefit.png` |
| `monte-carlo` | `monte_carlo_trials.csv`, optional parameter samples, summary JSON, distribution plots |
| `sensitivity-oneway` | `sensitivity_oneway.csv`, summary JSON, tornado plot |
| `sensitivity-winner-map` | `sensitivity_twoway.csv`, summary JSON, winner-map plot |
| `break-even` | `breakeven_report.json`, crossing plot |

## Scenario daily columns

Every generic daily scenario result contains:

| Column | Meaning |
| --- | --- |
| `date`, `scenario_name` | Site-local day and scenario |
| `clean_energy_kwh` | Shared unsoiled reference |
| `actual_energy_kwh` | Scenario output |
| `energy_loss_kwh`, `soiling_ratio` | Derived difference and ratio |
| `operational_*` | Shared inspection, cleaning, labor, flight, water, energy, and cost quantities |
| `extension_*` | Scenario-specific diagnostics |

Unknown extension columns must be preserved or ignored by common consumers. Structured extension
values are JSON-encoded.

## Event columns

`scenario_events.csv` records `date`, scenario, sequence, phase, effective energy date, event type,
magnitude, description, optional cohort, and JSON metadata. A cleaning event recorded on one date
may have the next date as `effective_for_energy_date`.

## Period naming

Some compatibility fields retain an `annual_` prefix. For a partial-year run they represent the
configured period total. Partial-year comparisons block an economic recommendation.
