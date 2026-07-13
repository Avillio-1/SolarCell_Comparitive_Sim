# Task 7: Surface parameter evidence quality in outputs and dashboard

## RUN THIS CHECK FIRST

Run `git status` in the repo root. If any of `src/solarclean/dashboard/static/dashboard.css`,
`src/solarclean/dashboard/static/dashboard.js`,
`src/solarclean/dashboard/templates/run_comparison.html`, or `tests/test_dashboard.py`
show as modified (uncommitted work by someone else), STOP IMMEDIATELY and report that
this task must wait until that in-flight dashboard work is committed. Do not attempt to
work around or on top of someone else's uncommitted changes.

## Project context

- You are working in the repo `SolarCell_Comparitive_Sim` (Windows). It contains a Python
  3.11+ package named `solarclean` under `src/`, installed editable via pip.
- SolarClean-DT simulates a 10,000-panel PV farm in Riyadh, compares three
  dust-mitigation scenarios, and serves results through a FastAPI + Jinja2 dashboard
  (`src/solarclean/dashboard/`). It has a calibration parameter registry
  (`data/calibration/parameter_registry.yaml`) where every parameter carries
  `evidence_type` (e.g. measured/literature/inferred/assumed), `confidence`
  (low/medium/high), and `status` (e.g. provisional/validated). Read `README.md` first.

## The problem you are fixing

The registry knows exactly how weak the evidence behind each number is, but the
comparison outputs and dashboard present energy, ROI, and payback as if they were
settled facts. The recommendation JSON already carries some assumption records; nothing
aggregates them into an at-a-glance honesty signal. Your job: compute an evidence-
quality summary from the registry and surface it (a) in the comparison output files and
(b) as a visible banner in the dashboard comparison view. No visual redesign — this is
an information-honesty feature, not a styling task.

## Before you start, read these files

1. `src/solarclean/domain/calibration/registry.py` — how the registry is loaded and
   what a parameter record exposes.
2. `src/solarclean/application/comparison.py` — find where `recommendation.json`,
   `summary.json`, and `scenario_annual_summary.csv` content is assembled (follow
   imports into `src/solarclean/domain/economics/summary.py` /
   `src/solarclean/infrastructure/persistence/` as needed). Identify the single best
   place to attach a new block to the comparison outputs.
3. An existing run directory under `outputs/` whose name contains
   `compare-all-scenarios` — inspect `recommendation.json` (it already embeds
   assumption records with `status`/`confidence`) and `summary.json` so you match
   existing shapes.
4. `src/solarclean/dashboard/app.py`, `src/solarclean/dashboard/templates/run_comparison.html`,
   and `src/solarclean/dashboard/jobs.py`/`artifacts.py` — how the dashboard reads a
   run's JSON artifacts and passes context into templates.
5. `tests/test_dashboard.py` — existing dashboard test patterns to mirror.

## Steps

1. **Evidence summary function.** In a sensible existing module (e.g. next to the
   registry code or the comparison summary assembly — pick ONE place, do not spread
   it), add a pure function `build_validation_status(registry) -> dict` returning:
   - `absolute_outputs_field_validated`: hardcode `False` with a comment that this flag
     must remain false until a measured-production validation exists (grep for a
     field-validation harness; if `validate-field` exists, mention it in the comment).
   - `parameter_counts_by_status` and `parameter_counts_by_evidence_type` (dict of
     counts over all registry parameters).
   - `lowest_confidence`: the worst confidence present (order: high > medium > low).
   - `key_uncertain_parameters`: the 5 parameters with the largest relative range
     `(high_value − low_value) / |central_value|` (skip parameters where
     `central_value == 0` or any bound is missing), each as
     `{name, central_value, low_value, high_value, confidence, status}`.
   - `disclaimer`: the fixed sentence: `"Internally verified simulation calibrated to
     literature and provisional assumptions; absolute energy, cost, and ROI outputs
     have not been validated against measured production data from an operating
     site."`
2. **Attach to comparison outputs.** Add the block under a top-level key
   `validation_status` in BOTH `summary.json` and `recommendation.json` written by the
   comparison flow. Add nothing to CSVs. Do not remove or rename any existing field
   (other tools parse these files).
3. **Dashboard banner.** In the comparison results view (`run_comparison.html` + its
   route in `app.py` + any JS that renders that view):
   - Render a clearly visible banner ABOVE the results using the `validation_status`
     block: the disclaimer sentence, the status counts (e.g. "41 provisional / 9
     assumed / 4 literature-backed parameters"), and a small expandable list of the 5
     `key_uncertain_parameters` with their low/central/high values.
   - If a run's JSON lacks `validation_status` (old runs), show nothing — the template
     must not error on old artifacts.
   - Reuse existing CSS classes/patterns from `dashboard.css`; add at most a few new
     styles. No layout redesign, no new JS framework, no external assets.
4. **Recommendation caveat.** Where the recommendation message/text is composed, if any
   parameter in the registry has status other than `validated`, append one sentence:
   `"This recommendation rests on provisional calibration parameters; see
   validation_status."` (Match the surrounding message style; add it once, not per
   parameter.)
5. **Tests:**
   - Unit test for `build_validation_status` against a small in-memory/temporary
     registry YAML with 3 fabricated parameters — assert counts, worst confidence, the
     top-range selection math, and the zero-central skip rule.
   - Extend the comparison-output tests (find existing tests that assert
     `summary.json` / `recommendation.json` content) to assert the new block exists
     and old fields are untouched.
   - Dashboard test in the style of `tests/test_dashboard.py`: a comparison run WITH
     `validation_status` renders the disclaimer text; a run WITHOUT it renders the page
     with no error and no banner.

## Constraints

- Touch ONLY the files listed below. No visual redesign, no renaming existing JSON
  fields, no removal of existing template content.
- Do not change existing golden regression data UNLESS a golden explicitly snapshots
  the full `summary.json`/`recommendation.json` — in that case update only by adding
  the new block via the established regeneration flow and say so in your report.
- mypy runs strict on `src/`: fully annotate all new code.
- If anything in this brief contradicts what you find in the code, STOP and report the
  discrepancy instead of guessing.
- Do not commit or push. Do not create accounts or API keys.

## Files you may create or modify

- ONE module for the evidence function (registry- or summary-adjacent, your pick)
- The comparison/summary assembly module(s) that write `summary.json` and
  `recommendation.json`
- `src/solarclean/dashboard/app.py`, `src/solarclean/dashboard/templates/run_comparison.html`,
  `src/solarclean/dashboard/static/dashboard.css`, `src/solarclean/dashboard/static/dashboard.js`
- Test files: new unit test file, plus targeted additions to existing comparison-output
  tests and `tests/test_dashboard.py`

## Verification (all must pass before you finish)

```
python -m pytest -q
python -m ruff format <only the files you changed>
python -m ruff check .
python -m mypy src
```

If `import solarclean` fails, first run: `python -m pip install -e ".[dev]"`

If a weather cache exists (`data/cache/weather`), also run
`solarclean compare-all-scenarios --config configs/default.yaml` offline and paste the
new `validation_status` block from the generated `summary.json` into your report.

## Final report

List: files changed; the `validation_status` block from a real run (or from tests if no
cache); a screenshot-level description of where the banner appears; test/lint/type
results; anything you could not complete.
