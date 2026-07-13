# SolarClean-DT Dashboard (T8/T9)

The dashboard is a web front end for the existing use cases: it launches runs,
watches them, and displays the artifact files they write. It deliberately does
no science of its own — every number on screen exists in a file under
`outputs/<run_id>/`, and the artifact list at the bottom of each results page
links to those files directly. The only transformations the dashboard performs
are reshaping stored values (picking CSV columns, grouping rows) and display
formatting (rounding, thousands separators, best-of-row highlighting of
already-stored numbers).

## Install and run (workstation)

```powershell
python -m pip install -e ".[dashboard]"
python -m solarclean.dashboard
```

Then open http://127.0.0.1:8050. By default the server binds to localhost and
resolves `configs/` and `outputs/` from the working directory, so run it from
the repository root — exactly as the CLI does.

## Deploying as a web app

The dashboard has no hardcoded machine paths; everything it needs is
configurable through the environment:

| Variable | Default | Purpose |
|---|---|---|
| `SOLARCLEAN_DASHBOARD_HOST` | `127.0.0.1` | Bind address. Use `0.0.0.0` behind a reverse proxy. |
| `SOLARCLEAN_DASHBOARD_PORT` | `8050` | Listen port. |
| `SOLARCLEAN_ROOT` | current working directory | Base directory containing `configs/` and `outputs/`. |
| `SOLARCLEAN_CONFIGS_DIR` | `<root>/configs` | Explicit configs directory (wins over `SOLARCLEAN_ROOT`). |
| `SOLARCLEAN_OUTPUTS_DIR` | `<root>/outputs` | Explicit outputs directory (wins over `SOLARCLEAN_ROOT`). |

Example (Linux server behind nginx/Caddy):

```bash
pip install -e ".[dashboard]"
export SOLARCLEAN_ROOT=/srv/solarclean
export SOLARCLEAN_DASHBOARD_HOST=0.0.0.0
export SOLARCLEAN_DASHBOARD_PORT=8050
python -m solarclean.dashboard
# or run uvicorn directly:
# uvicorn solarclean.dashboard.app:app --host 0.0.0.0 --port 8050
```

Notes and known limits:

- Serve the app at the domain root (or its own subdomain). Static assets and
  API calls use root-relative paths (`/static/...`, `/api/...`), so mounting
  under a sub-path such as `/dashboard/` is not supported.
- Chart.js (`static/chart.umd.js`) and the location-picker world map
  (`static/world_land.js`, Natural Earth public domain) are vendored — pages
  load no CDN or tile-server assets. The server itself needs outbound HTTPS to
  `power.larc.nasa.gov` when a run's weather is not yet cached (the Default
  config fetches live NASA POWER weather).
- **Authentication:** set `SOLARCLEAN_DASHBOARD_TOKEN` to require the token on
  every request (HTTP Basic — any username, the token as password; browsers
  prompt natively). Unset, the dashboard is open: fine on localhost, not on a
  shared network. Anyone authenticated can start runs, edit the Default
  config, and delete runs, so treat the token as an admin credential.
- **One run at a time:** launching while another session is queued or running
  returns 409 — simulations are CPU-bound and concurrent runs only slow each
  other down. Wait, or cancel the active session.
- Run once per deployment: live jobs are tracked in-process and a single
  worker is assumed (uvicorn default). Finished sessions persist to
  `outputs/.dashboard_jobs.json` and reappear after a restart; a job lost to
  a crash mid-run leaves no session record (its run directory, if written,
  still shows under Completed runs).

## Home page

**Configuration and period.** The bundled **Default** configuration
(`configs/default.yaml`) starts with the Riyadh site, **live NASA POWER weather**
(`weather.provider: nasa_power`), the 2025 site-year, and the central-v2
calibration set. The 2025 dates are the validated reference preset, not an
engine restriction. The launch form's start and end fields can override them
with any whole-day range for one run; the selected YAML remains unchanged and
the resolved dates are recorded in that run's `config_resolved.yaml`.

Partial-year and multi-year periods are useful for simulation experiments, but
annual-labelled output fields then represent the configured period total. The
comparison intentionally blocks an economic recommendation unless the period
is exactly one Jan 1–Dec 31 site-year. Live NASA POWER runs also depend on the
requested dates being available from the provider.

Because the provider is live, the site coordinates genuinely drive the
simulation — see "Map location picker" below. The first run for a given
location and period fetches the weather from NASA POWER (internet required)
and caches it under `data/cache/weather`; later runs reuse the cache.

**Analyses.** The launch panel offers the same five analyses as the CLI:

| Analysis | Wraps |
|---|---|
| Compare all scenarios | `CompareAllScenarios` (T6) |
| Monte Carlo | `MonteCarloExperiment` (T7) |
| One-way sensitivity | `OneWaySensitivityExperiment` (T7) |
| Two-way winner map | `TwoWaySensitivityExperiment` (T7) |
| Break-even search | `BreakEvenExperiment` (T7) |

Extra fields appear depending on the analysis (trial count, parameters,
scenario pair). Sensitivity, winner-map, and break-even parameters are picked
from dropdowns populated with the T7-supported catalog of
`data/calibration/parameter_registry.yaml` — hover an option to see its
registry low/central/high range — instead of hand-typing registry keys.

**Run sessions.** Runs execute on background threads; the sessions table polls
every two seconds and shows status, a progress bar, elapsed time, and an ETA:

- *Compare* reports progress per scenario simulated (3 units); *Monte Carlo*
  per trial (central comparison + N trials); *one-way sensitivity* per sweep
  point (base variant + every point of every swept parameter); *winner map*
  per grid cell.
- *Break-even* is a search that can converge early, so its exact length is
  unknowable upfront. Progress is reported against the experiment's stated
  evaluation budget (`max_evaluations`, default 24): the bar is a truthful
  lower bound that jumps to 100% when the search finishes, and the ETA is
  correspondingly a worst-case figure.
- The ETA is measured pace (elapsed time per completed unit) times remaining
  units — it appears only after the first unit finishes.

**Deleting a session.** Each session row has a delete button. A finished
session is removed immediately (also from the persisted history). A running
session is cancelled cooperatively: it is hidden from the list at once and the
worker stops at its next progress checkpoint (for a comparison, between
scenarios). Cancellation never corrupts results — artifact packages are
written only after all scenarios complete. Deleting a session never deletes
run directories; those are managed separately (below). Finished sessions are
persisted to `outputs/.dashboard_jobs.json`, so the table survives server
restarts.

**Completed runs.** The runs list shows every run directory under `outputs/`
(dashboard- or CLI-made) with its creation time. Each row has a **Delete**
button, and rows can be check-selected for **Delete selected** — both ask for
confirmation because deletion permanently removes the run directory,
including all exports; download the `.zip` first if the files matter. (On
OneDrive-synced folders the sync client can briefly hold the emptied folder
shell open; the data is gone, the shell is hidden from the list, and it is
swept automatically once the handle is released.)

**Re-running.** Every result page has a *re-run this analysis* button. It
relaunches the analysis using the run's own stored `config_resolved.yaml` —
the exact configuration that produced the result, not the current Default —
with the analysis options (trial count, parameters, scenario pair)
reconstructed from the run's summary artifacts. The new job appears in the
sessions table.

## Theme

The topbar has a light/dark toggle. The choice is stored in the browser
(`localStorage`) and reapplied before first paint on refresh; with no stored
choice the OS preference is used.

## Comparison results page

Reading order is intentional:

0. **Headline cards and provenance.** For a run whose recommendation is valid,
   the answer sits at the top: recommended strategy, its margin over the
   runner-up, net annual benefit, energy gain, and payback — all straight from
   `recommendation.json`. Below it, a provenance strip states the weather
   provider, site coordinates, weather checksum, and creation time from the
   run's `metadata.json`, so results from different sites cannot be confused.
   (T7 analysis pages show the same strip from their `config_resolved.yaml`.)
1. **Reconciliation strip.** Every T6 check as a pass/fail chip (hover for the
   message), with a plain-English "What is this?" explainer: reconciliation is
   the run's self-audit, including **cost reconciliation** — costs must match
   operational quantities (crew hours × labour rate, water used × water
   price). If any check fails the strip turns red, a notice explains that no
   ranking was accepted, and the ranking section is absent — the dashboard
   never shows a winner the backend refused to certify.
2. **Ranking and recommendation.** Net-annual-benefit ranking with the winner
   highlighted, followed by the recommendation's warnings (always expanded)
   and the full assumption list (collapsible).
3. **Annual KPIs.** Selected columns of `scenario_annual_summary.csv`,
   transposed so scenarios read across. The best stored value in each row is
   highlighted green using the metric's direction: higher is better for
   revenue, energy gain, net benefit, and ROI; lower is better for losses,
   costs, payback, and LCOE. Operational rows (water, crew hours, drone
   hours) are not ranked. Financial row labels carry hover definitions, and a
   collapsible "What these metrics mean" glossary spells out ROI, payback,
   LCOE, and annualized CAPEX in plain English.
4. **Interactive charts.** Daily AC energy, daily energy loss, daily soiling
   ratio, the **cumulative energy gain vs baseline** (a running total T6 now
   writes into the daily summary — where a curve climbs, the strategy is
   pulling ahead; its final value equals the annual gain), and an annual
   revenue/cost/benefit bar chart. All are stored columns of the run's CSVs;
   the backend's PNG exports are still listed under Artifacts.
5. **Cost components.** Grouped per scenario into CAPEX and OPEX with the
   backend's stored subtotals (total CAPEX, annual OPEX) and totals
   (annualized CAPEX, total annual cost), formatted with thousands separators
   and units. Per-component **evidence status** (the stored `source_status`
   field: quoted / provisional / blocked) is deliberately not in the main
   table — it lives in the collapsed "Evidence status & sources (advanced)"
   section together with sources and notes.
6. **Artifacts.** A download link for every file plus a full-run `.zip`.

## Analysis results page

Every analysis kind now gets interactive charts built from its own stored
artifacts (the backend's PNG exports remain in a collapsed section and the
artifact list):

- **Monte Carlo** — summary strip and statistics table, win-probability and
  P5/mean/P95 bars from `monte_carlo_summary.json`, plus a **distribution dot
  plot**: every reconciled trial's net benefit from `monte_carlo_trials.csv`,
  one dot per trial per scenario. Overlapping clouds mean the ranking is
  seed-sensitive. Unreconciled trials are excluded, matching the statistics.
- **One-way sensitivity** — an interactive **tornado chart** from
  `sensitivity_oneway_summary.json`: each parameter's stored net-benefit swing
  across its registry range, largest first, with winner-flipping parameters
  highlighted in amber.
- **Two-way winner map** — a colored **heatmap grid** from
  `sensitivity_twoway_summary.json`: cell colour = winning scenario at that
  parameter pair, hover for each scenario's stored net benefit, × for
  unreconciled points.
- **Break-even** — a **crossing chart** from `breakeven_report.json`: the
  stored margin at every evaluated value, a dashed zero line, and markers at
  the found break-even value(s).

## Config viewer / editor

"view / edit config" opens the Default configuration. **Validate** round-trips
the text through `load_config`, so schema errors are the same Pydantic
messages a CLI run would raise. **Validate and save** overwrites the Default —
the next dashboard or CLI run uses it.

### Map location picker

Below the editor, a "Site location" panel shows a world map (a vendored
public-domain Natural Earth land outline in `static/world_land.js` — the map
itself needs no tile servers). Clicking the map, or typing coordinates, sets
latitude/longitude; **Apply to config above** rewrites the `site.latitude` /
`site.longitude` lines in the editor, after which the normal validate/save
flow applies. The picker edits YAML text; the weather change happens at run
time.

**What changes with the location.** The Default config uses `nasa_power`, so
runs fetch that location's real hourly weather from NASA POWER: irradiance
(GHI/DNI/DHI), air temperature, wind speed, relative humidity, and
precipitation. Those drive clean PV production, rainfall cleaning, coating
cooling/humidity behaviour, and drone weather cancellations. (Spot check:
Riyadh vs Berlin for the same June 2025 days differ as expected — mean 33.6 °C
/ 11 % RH vs 19.2 °C / 68 % RH, with ~35 % less irradiance in Berlin.)

**What does not change.** Soiling/dust-event statistics and all cost
calibration remain the Riyadh central-v2 assumption set wherever the site is
placed — moving the site moves the weather, not the dust climate or the cost
basis. And with `fixture`/`csv` providers the weather data is fixed, so the
panel switches to an explicit warning that coordinates are metadata only and
will **not** change results. The panel detects `weather.provider` live from
the YAML and states the applicable case.

## Boundaries (what the dashboard will not do)

- No physics, economics, or statistics in routes, templates, or JS. The only
  data transformation is reshaping (picking CSV columns for a chart, grouping
  cost rows) and display formatting (rounding, separators, highlighting the
  best of already-stored values).
- Progress and ETA are never estimated beyond measured unit counts reported by
  the use cases themselves (or, for the break-even search, its declared
  evaluation budget — an upper bound, labelled as such).
- The location picker edits YAML text only and states when coordinates do not
  affect results; it never implies fixture weather follows the map.
- No second simulation loop, no strategy logic, no direct registry mutation.
- Artifact and config paths are validated against traversal; run downloads are
  zipped from the run directory as-is.

If a screen needs a number that no use case writes, that is a backend change
(T6/T7), not a dashboard formula.

## Tests

`tests/test_dashboard.py` runs one real offline comparison and checks that the
rendered page reconciles with `scenario_ranking.json`, that the zip export
matches the run directory exactly, that traversal attempts 404, and that
config validation accepts/rejects correctly. T9 additions cover the
Default-only launch flow, session delete/cancel, progress/ETA honesty, KPI
best-value direction, cost-table grouping and formatting, evidence-status
visibility, theme-toggle persistence markers, environment-overridable paths
and bind address, run deletion (single and traversal-guarded), parameter
dropdowns, the four analysis charts, headline cards, the KPI glossary,
weather provenance, the cumulative-gain column reconciling with the annual
gain, persistent job history, re-run, the auth token, and the
one-run-at-a-time guard:

```powershell
python -m pytest tests/test_dashboard.py -q
```
