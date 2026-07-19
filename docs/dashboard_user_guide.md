# SolarClean-DT Dashboard (T8/T9)

The dashboard is a web front end for the existing use cases: it launches runs,
watches them, and displays the artifact files they write. It deliberately does
no science of its own — every number on screen exists in a file under
`outputs/<run_id>/`, and the artifact list at the bottom of each results page
links to those files directly. The only transformations the dashboard performs
are reshaping stored values (picking CSV columns, grouping rows) and display
formatting (rounding, thousands separators, best-of-row highlighting of
already-stored numbers, plus a display-only subtraction on the two-run diff).

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

**Configuration cockpit.** The first viewport is an instrument cluster for the
selected configuration, not a marketing hero. It shows the resolved site and
coordinates, an offline locator map (clicking it opens the location picker on
the config page), simulation period, assumption set, exact weather-cache
readiness, and the most recent matching run's winner and margin. Changing the
configuration selector updates the cockpit as well as the launch-period fields
and sensitivity catalog.

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

**Analyses.** The launch form asks the question first: five radio cards phrase
each analysis as the question it answers, with the method name as fine print.

| Question card | Method | Wraps |
|---|---|---|
| Which strategy wins? | compare all scenarios | `CompareAllScenarios` (T6) |
| How sure are we of the winner? | Monte Carlo | `MonteCarloExperiment` (T7) |
| Which assumption moves the result most? | one-way sensitivity | `OneWaySensitivityExperiment` (T7) |
| Where does the winner flip? | two-way winner map | `TwoWaySensitivityExperiment` (T7) |
| At what value do two strategies tie? | break-even search | `BreakEvenExperiment` (T7) |

Extra fields appear depending on the analysis (trial count, parameters,
scenario pair), each explained by microcopy next to the field itself.
One-way sensitivity requires an explicit parameter selection. Its workload
preview gives the exact number of comparison evaluations before launch; use
**Select all** only when an exhaustive catalog sweep is intentional. With the
default five steps, selecting all 35 currently supported parameters means 176
comparison evaluations (one base plus five values per parameter).
Sensitivity, winner-map, and break-even parameters are picked from a
searchable checklist grouped by domain (soiling, rainfall, economics, …) over
the T7-supported catalog of `data/calibration/parameter_registry.yaml`. Every
row shows a human label, the registry key, and the registry low/central/high
range with a tick at the central value — no hand-typing registry keys, no
hover-only tooltips. The native selects remain underneath as the no-JS
fallback and state store.

**Run sessions.** Runs execute on background threads. A launched analysis is
one object with one home: it appears immediately as a live card at the top of
the runs panel (status, progress bar, elapsed time, ETA, cancel button),
polls every two seconds, and on success resolves in place into the finished
run's card in the archive below. Failed sessions stay as red cards with the
stored error until dismissed. While a run is active the browser tab title
shows its progress ("⏳ 42% compare · SolarClean-DT"), and — with permission,
requested once on the first launch click — a browser notification fires when
a run finishes or fails while the tab is in the background. Progress
semantics per analysis kind:

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

**Deleting a session.** A running session card's **Cancel & remove** stops it
cooperatively: it disappears at once and the worker stops at its next progress
checkpoint (for a comparison, between scenarios). Cancellation never corrupts
results — artifact packages are written only after all scenarios complete.
Dismissing a failed card removes it from the persisted history too. Deleting a
session never deletes run directories; those are managed separately (below).
Finished sessions are persisted to `outputs/.dashboard_jobs.json`, so cards
survive server restarts.

**The run archive.** The gallery shows every run directory under `outputs/`
(dashboard- or CLI-made), **grouped by study** — the site, period, and
assumption set stored in each run's own `config_resolved.yaml` — with studies
ordered by their most recent run and runs newest-first inside each study. A
study header rules off each block, so "Riyadh · 2025 · central-v2" reads as
one investigation rather than a flat list of ids. Cards lead with the finding:
site, human date, the stored winner with its margin (or the MC majority
winner's win share), and the validity chip; the run id is demoted to small
type. Older card batches append automatically near the bottom; the button
there is a manual fallback, not pagination. Fingerprints load only when their
cards approach the viewport. **Select all** loads and selects the remaining
batches before enabling the bulk action. Comparison packages that contain
daily artifacts carry one slice per stored day, combining daily GHI and
baseline cleanliness, with stored cleaning events as ticks; packages without
daily artifacts show an explicit "daily tape unavailable" hatch rather than
inventing a year.

Selecting cards raises a **contextual action bar** pinned near the bottom of
the panel (count, Compare 2 selected, Delete selected, Clear) so actions stay
next to the selection. Deletion is deliberately two-step: a card's **Delete**
button arms to "Really delete?" and only a second click within a few seconds
executes; **Delete selected** opens a dialog stating the exact count. Both
exist because deletion permanently removes the run directory, including all
exports — download the `.zip` first if the files matter. (On OneDrive-synced
folders the sync client can briefly hold the emptied folder shell open; the
data is gone, the shell is hidden from the list, and it is swept automatically
once the handle is released.)

**Command palette.** `Ctrl+K` (or the topbar button) opens a palette that
fuzzy-matches every stored run by id, site, kind, and winner, plus actions
(new analysis, open config, toggle audit mode or theme). It reads the same
stored listing as the run cards via `/api/command-index`.

**Re-running.** Every result page has a *re-run this analysis* button. It
relaunches the analysis using the run's own stored `config_resolved.yaml` —
the exact configuration that produced the result, not the current Default —
with the analysis options (trial count, parameters, scenario pair)
reconstructed from the run's summary artifacts. The new job appears in the
sessions table.

## Theme

The topbar names the two shifts **Daylight** and **Night shift**. The control is
drawn as a sun-elevation dial; internally it retains the light/dark preference
keys for compatibility. The choice is stored in the browser (`localStorage`)
and reapplied before first paint on refresh; with no stored choice the OS
preference is used. IBM Plex Sans, IBM Plex Mono, and IBM Plex Sans Arabic are
self-hosted under `static/fonts/` with their Open Font License.

## Comparison results page

Reading order is intentional:

0. **Engineering document header and certification.** Every run page starts
   with a bilingual EN/AR CAD-style title block: run ID, site and coordinates,
   weather provider and checksum, assumption set, period, issue date, status,
   and sheet 1 of 1. Directly beneath it sits the **certification block** —
   one approval area, as on a real engineering document, joining the run's
   stored trust signals: the reconciliation verdict (every T6 check as a
   pass/fail chip; click a chip for its stored message), the parameter
   evidence quality (blocked/provisional counts, the stored disclaimer, and
   the most uncertain parameters), the recommendation tier, and the warnings.
   Repeated parameter-status warnings ("X has status blocked; …") are grouped
   into one sentence with the parameter list expandable, instead of eleven
   near-identical lines. If any reconciliation check fails the block turns
   red, a notice quotes the stored failure, and the ranking section is absent
   — the dashboard never shows a winner the backend refused to certify.
1. **Finding banner and decision strip.** The declarative stored finding, a
   **decision strip** — the stored net change vs baseline per scenario drawn
   as diverging bars around a zero line (bar length is the same purely visual
   |value|/max scaling the KPI micro-bars use) — and compact headline cards
   from `recommendation.json`. If a Monte Carlo run of the same study exists,
   each bar carries that run's stored win probability ("wins 78% of trials")
   with a link — a display join of stored values, not new statistics. When
   baseline wins, the margin card relabels to "Best mitigation falls short
   by" (same stored number, honest framing) and the degenerate "energy gain
   vs baseline: 0" card is dropped.
2. **Related runs.** A strip under the command bar lists the study's other
   stored runs (same site, period, and assumption set) with a one-line stored
   finding each — the Monte Carlo majority winner, the tornado's top driver,
   break-even crossings — plus a "Compare against" selector that opens the
   two-run diff. Runs stop being islands: the comparison, its uncertainty
   check, and its sensitivity sweeps read as one investigation.
3. **Ranking and recommendation.** The annual financial-outcome ranking makes
   the stored arithmetic visible at the decision point: value of extra energy,
   added annual cost, net change versus baseline, and total net annual benefit.
   A formula strip names the run's stored electricity tariff, and each scenario
   has an expandable ledger showing annual AC energy × tariff, annualized CAPEX,
   annual OPEX, and the resulting total. The dashboard only joins and formats
   values already stored in the ranking, annual-summary, and metadata artifacts;
   it does not recalculate economics. The winner is highlighted, followed by the
   full assumption list (collapsible). The cost-boundary note makes clear that
   common solar-farm costs are outside the mitigation decision, so baseline has
   no mitigation CAPEX or OPEX.
4. **Annual KPIs.** Selected columns of `scenario_annual_summary.csv`,
   transposed so scenarios read across. The best stored value in each row is
   highlighted green **and marked ▲** (information survives without colour)
   using the metric's direction: higher is better for revenue, energy gain,
   net benefit, and ROI; lower is better for losses, costs, payback, and
   LCOE. Operational rows (water, crew hours, drone hours) are not ranked.
   Financial row labels open plain-English definitions in an anchored popover
   (keyboard- and touch-accessible, unlike hover tooltips), and a collapsible
   "What these metrics mean" glossary spells out ROI, payback, LCOE, and
   annualized CAPEX.
5. **Annual water balance.** Three alternative-strategy cards select the
   stored external cleaning-water use, harvested coating dew, net water
   position, litre and cubic-metre volumes, 1,000 L tank equivalents, and
   dew-eligible nights from `scenario_annual_summary.csv`. Net position and
   every conversion are persisted by the comparison application, not
   calculated in the dashboard. Legacy records keep their original litre
   totals visible and explicitly mark newer fields as unavailable until the
   record is re-run.
6. **Humidity and dew-point simulator.** RH, air-temperature, and wind sliders
   call `/api/runs/{run_id}/dew-simulator`. The endpoint loads that run's
   immutable `config_resolved.yaml` and delegates to
   `application.dew_simulator`, which reuses the coating domain's surface
   cooling, dew-point, and condensation functions. It reports the humidity
   gate, dew margin, per-square-metre harvest rate, and whole-farm one-hour
   rate. The preview fixes irradiance at 0 W/m² and exposure at one hour; it
   is non-persistent and does not alter the annual record.
7. **The daily explorer — one instrument for the year.** A metric switcher
   redraws the main chart from the same stored daily columns: **Energy**
   (`actual_energy_kwh`, with the clean-reference dashes), **Loss**
   (`energy_loss_kwh`), **Cleanliness** (the stored scenario cleanliness
   fields), and **Cumulative gain** (`cumulative_energy_gain_vs_baseline_kwh`
   — where a curve climbs, the strategy is pulling ahead; its final value
   equals the annual gain). The standalone daily chart panels are gone; every
   view shares the explorer's aligned cursor, keyboard day-stepping, scenario
   focus, and selected-day panel. Context tracks beneath show GHI,
   temperature, rainfall, **daily mean relative humidity**, and stored events
   for the same dates. Selecting a day opens the stored hourly humidity series,
   so intraday variation remains available without making the year overview
   unreadably dense. The full-width fingerprint above the charts is the
   **scrubber**: drag a window across it to zoom every explorer chart to that
   date range (a "Reset range" button restores the year), click to select a
   day. An annual revenue/cost/benefit bar chart keeps its own panel.
8. **Cost components.** Grouped per scenario into CAPEX and OPEX with the
   backend's stored subtotals (total CAPEX, annual OPEX) and totals
   (annualized CAPEX, total annual cost), formatted with thousands separators
   and units. Per-component **evidence status** (the stored `source_status`
   field: quoted / provisional / blocked) is deliberately not in the main
   table — it lives in the collapsed "Evidence status & sources (advanced)"
   section together with sources and notes.
9. **Artifacts.** A download link for every file plus a full-run `.zip`.

The sticky section nav highlights the section currently in view (scroll spy).
Between the KPI table and explorer, a collapsed strategy-rhythm disclosure
creates three 53-by-7 dust calendars only when opened. They render stored daily
cleanliness plus inspection, cleaning, and coating action marks. Permanent line
glyphs identify baseline (bare panel), reactive
(droplet), and coating (hex film) in HTML and Chart.js legends.

### Audit mode and print

**Audit mode** turns source-annotated values and figures into dotted,
clickable traces. Clicking opens a source card **anchored next to the clicked
value** naming the artifact and field; cost components also show the stored
quantity/rate note and the matching numbered reconciliation check. While
armed, a banner under the topbar states "AUDIT ACTIVE" and `Esc` exits. This
is presentation over stored values, not a second economics engine. The same
anchored-popover component replaces hover-only `title` tooltips everywhere
(reconciliation chips, KPI definitions, winner-map cells), so the information
is reachable by keyboard and touch.

The print stylesheet removes application chrome, forces an A4 landscape
calculation-record palette, preserves rules/hatching, and keeps the bilingual
title block and verification stamp. Invalid and missing winner-map cells use
diagonal drawing hatch in screen and print output.

## Compare runs

The two-run page is a diff: changed resolved-config assumptions are rendered as
minus/plus lines, identical fields are collapsed, and changed annual KPIs show
paired values plus a directional delta. The preferred KPI direction is used
only to colour the displayed change; it does not alter either stored run.
Framing follows the studies: two runs of the **same** study read as
"A · BEFORE / B · AFTER"; runs from different studies (site, period, or
assumption set differ) are labelled neutrally "RUN A / RUN B", because neither
is an iteration of the other. Every comparison record also offers a
"Compare against" selector in its related-runs strip, so the diff is reachable
without the home-page checkbox flow.

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

"Review configuration" opens the Default configuration, essentials first: the
knobs most runs actually change (site location and period) sit at the top,
and the raw YAML editor is a collapsed "YAML source (advanced)" escape hatch
below. **Validate** round-trips the text through `load_config`, so schema
errors are the same Pydantic messages a CLI run would raise. **Validate and
save** overwrites the Default — the next dashboard or CLI run uses it.
**Reset to Riyadh defaults** loads the immutable packaged Riyadh factory
preset into the editor, even if the active Default was previously saved with
another site. Press **Validate and save** to make the restored preset active
for subsequent runs.

### Map location picker and period

The essentials panel shows a world map (a vendored public-domain Natural
Earth land outline in `static/world_land.js` — the map itself needs no tile
servers). Clicking the map, or typing coordinates, sets latitude/longitude;
the period fields are pre-filled from the YAML. **Apply to YAML source**
looks up the matching IANA timezone automatically from an offline
timezone-boundary dataset, rewrites `site.latitude`, `site.longitude`,
`site.timezone`, and `simulation.target_timezone`, and rebuilds the
simulation start/end values — at the existing local dates and times, or at
the new whole-day period if the period fields were changed (00:00–23:00
local, the same convention as the launch form). The server derives the
correct UTC offset for each boundary, including DST; the edit lands in the
YAML editor (opened automatically) and the normal validate/save flow then
applies. The picker edits YAML text; the weather change happens at run time.

**What changes with the location.** The Default config uses `nasa_power`, so
runs fetch that location's real hourly weather from NASA POWER: irradiance
(GHI/DNI/DHI), air temperature, wind speed, relative humidity, and
precipitation. Those drive clean PV production, rainfall cleaning, coating
cooling/humidity behaviour, and drone weather cancellations. (Spot check:
Riyadh vs Berlin for the same June 2025 days differ as expected — mean 33.6 °C
/ 11 % RH vs 19.2 °C / 68 % RH, with ~35 % less irradiance in Berlin.)
Hourly weather is kept in the selected site timezone, so daily rainfall,
seasonal soiling, shared event-tape dates, and cleaning decisions all use that
location's civil-day boundaries. Multi-year runs build each calendar year in
the same selected timezone rather than assuming Riyadh's `+03:00` offset.

**What does not change.** Soiling/dust-event statistics and all cost
calibration remain the Riyadh central-v2 assumption set wherever the site is
placed — moving the site moves the weather, not the dust climate or the cost
basis. And with `fixture`/`csv` providers the weather data is fixed, so the
panel switches to an explicit warning that coordinates are metadata only and
will **not** change results. The panel detects `weather.provider` live from
the YAML and states the applicable case.

## Boundaries (what the dashboard will not do)

- No physics, economics, or statistics are implemented in routes, templates,
  or JS. The dew preview route delegates to the application-layer simulator,
  which reuses domain coating physics and the run's stored config. The only
  data transformation is reshaping (picking CSV columns for a chart, grouping
  cost rows) and display formatting (rounding, separators, highlighting the
  best of already-stored values, and subtracting two stored values for the
  two-run diff). Display deltas are never persisted or fed back into ranking.
- Progress and ETA are never estimated beyond measured unit counts reported by
  the use cases themselves (or, for the break-even search, its declared
  evaluation budget — an upper bound, labelled as such).
- The location picker asks the server to make a validated, timezone-consistent
  YAML edit and states when coordinates do not affect results; it never
  implies fixture weather follows the map.
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
one-run-at-a-time guard. Redesign additions cover the question-card launcher,
the parameter picker mounts, session cards replacing the jobs table, study
grouping and the related-runs strip, the certification block and warning
aggregation, the decision strip, baseline-win headline relabelling, neutral
vs before/after diff framing, the command-index endpoint, and the
apply-location period rewrite:

```powershell
python -m pytest tests/test_dashboard.py -q
```
