# SolarClean-DT Dashboard (T8)

The dashboard is a web front end for the existing use cases: it launches runs,
watches them, and displays the artifact files they write. It deliberately does
no science of its own — every number on screen exists in a file under
`outputs/<run_id>/`, and the artifact list at the bottom of each results page
links to those files directly.

## Install and run

```powershell
python -m pip install -e ".[dashboard]"
python -m solarclean.dashboard
```

Then open http://127.0.0.1:8050. Run it from the repository root — configs and
outputs resolve relative to the working directory, exactly as they do for the
CLI. The server binds to localhost only; it is a workstation tool, not a
deployment.

## Home page

The launch panel offers the same five analyses as the CLI:

| Analysis | Wraps |
|---|---|
| Compare all scenarios | `CompareAllScenarios` (T6) |
| Monte Carlo | `MonteCarloExperiment` (T7) |
| One-way sensitivity | `OneWaySensitivityExperiment` (T7) |
| Two-way winner map | `TwoWaySensitivityExperiment` (T7) |
| Break-even search | `BreakEvenExperiment` (T7) |

Extra fields appear depending on the analysis (trial count, parameter names,
scenario pair). Parameter names are registry keys from
`data/calibration/parameter_registry.yaml`, same as the CLI options.

Runs execute in the background; the jobs table polls every two seconds and
links to the results page when a run finishes. If a run fails, the error is
shown in the row — hover the status for the traceback summary. The jobs table
is in-memory: restarting the server clears it, but finished run directories
stay on disk and remain in the "Completed runs" list, which also picks up runs
made through the CLI.

## Comparison results page

Reading order is intentional:

1. **Reconciliation strip.** Every T6 check as a pass/fail chip (hover for
   the message). If any check fails the strip turns red, a notice explains
   that no ranking was accepted, and the ranking section is absent — the
   dashboard never shows a winner the backend refused to certify.
2. **Ranking and recommendation.** Net-annual-benefit ranking with the winner
   highlighted, followed by the recommendation's warnings (always expanded —
   provisional assumptions are not hidden behind a click) and the full
   assumption list (collapsible, since it is long).
3. **Annual KPIs.** Selected columns of `scenario_annual_summary.csv`,
   transposed so scenarios read across. Values are rounded for reading; the
   caption links to the CSV for full precision.
4. **Daily AC energy chart.** Interactive, fed by column selection from
   `scenario_daily_summary.csv`.
5. **Generated plots, cost components, artifacts.** The matplotlib plots the
   run already produced, the cost component table, and a download link for
   every file plus a full-run `.zip`.

## Analysis results page

Monte Carlo runs get a summary strip (trials reconciled, central vs majority
winner, uncertainty mode, base seed) and the per-scenario statistics table
(win probability, mean/std/P5/P95 net benefit). Failed trials are called out,
not silently dropped. Sensitivity, winner-map, and break-even runs show the
run's own `summary.txt` plus its plots and artifacts.

## Config viewer / editor

"view / edit config" on the launch panel opens any YAML in `configs/`.
**Validate** round-trips the text through `load_config`, so schema errors are
the same Pydantic messages a CLI run would raise. **Validate and save** writes
to a new file name in `configs/` — the original is never overwritten — and the
new file immediately appears in the launch form.

## Boundaries (what the dashboard will not do)

- No physics, economics, or statistics in routes, templates, or JS. The only
  data transformation is reshaping (picking CSV columns for a chart, rounding
  for display).
- No second simulation loop, no strategy logic, no direct registry mutation.
- Artifact and config paths are validated against traversal; run downloads
  are zipped from the run directory as-is.

If a screen needs a number that no use case writes, that is a backend change
(T6/T7), not a dashboard formula.

## Tests

`tests/test_dashboard.py` runs one real offline comparison and checks that the
rendered page reconciles with `scenario_ranking.json`, that the zip export
matches the run directory exactly, that traversal attempts 404, and that
config validation accepts/rejects correctly:

```powershell
python -m pytest tests/test_dashboard.py -q
```
