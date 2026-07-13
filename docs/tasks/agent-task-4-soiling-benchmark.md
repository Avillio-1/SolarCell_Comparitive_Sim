# Task 4: Benchmark the soiling model against published pvlib models (script only)

## Project context

- You are working in the repo `SolarCell_Comparitive_Sim` (Windows). It contains a Python
  3.11+ package named `solarclean` under `src/`, installed editable via pip.
- SolarClean-DT simulates a 10,000-panel PV farm in Riyadh. Its dust/soiling model is a
  custom empirical "Kimber-style" model in
  `src/solarclean/domain/contamination/soiling.py`, calibrated to provisional targets,
  not to measured site data. Read `README.md` and
  `docs/calibration/source_bibliography.md` first.

## The problem you are fixing

The project's soiling model has never been compared against any independently published
model. pvlib (already a dependency) ships two peer-reviewed soiling models:
`pvlib.soiling.kimber` (Kimber et al. 2006) and `pvlib.soiling.hsu` (Coello & Boyle
2019, HSU model). Your job: run all three on the SAME Riyadh 2025 rainfall series and
produce a report showing whether the project's central soiling behavior falls inside
the envelope of the published models under literature-typical arid parameters. This is
external corroboration of model form — not site validation — and the report must say so.

This is a **script + report only**. Do NOT modify anything under `src/`.

## Before you start, read these files

1. `src/solarclean/domain/contamination/soiling.py` — the whole file. Note:
   - `KimberStyleSoilingModel(config: SoilingConfig, rainfall: RainfallCleaningConfig)`
   - `update(previous_state, environment, rng, event_inputs=None)` advances ONE day and
     returns a `SoilingUpdate` whose `state.dust_soiling_ratio` is the end-of-day ratio
     (1.0 = perfectly clean).
   - `ContaminationState()` default is the clean starting state.
   - `DailyEnvironment(date=..., precipitation_mm=..., mean_relative_humidity_pct=...,
     max_relative_humidity_pct=...)` is the daily input.
2. `src/solarclean/config/models.py` — `SoilingConfig` and `RainfallCleaningConfig`
   field names (they match the `soiling:` and `rainfall_cleaning:` blocks in
   `configs/default.yaml`).
3. `configs/default.yaml` — the `soiling:` and `rainfall_cleaning:` values (e.g. base
   daily loss 0.001/day, full-rain threshold 5.0 mm, partial 1.0 mm).
4. `src/solarclean/config/loader.py` and `src/solarclean/application/use_cases.py` —
   how to load the config and obtain the normalized NASA weather dataset through the
   project's provider path (a cache exists under `data/cache/weather`, so this is
   offline).
5. In a Python session: `help(pvlib.soiling.kimber)` and `help(pvlib.soiling.hsu)`.
   Confirm signatures, units, and — critically — what each returns:
   `kimber` returns soiling **loss** (0 = clean); `hsu` returns soiling **ratio**
   (1 = clean). Normalize everything to ratio (1 = clean) before comparing.

## Steps

1. Create `scripts/benchmark_soiling_vs_published.py`, structured as importable
   functions plus `main()` (functions will be unit tested).
2. **Load weather**: get the hourly 2025 Riyadh dataset via the project config/provider
   path. Derive from it, in `Asia/Riyadh` time: (a) the hourly precipitation series
   (mm) for pvlib, and (b) per-day aggregates: total precipitation, mean relative
   humidity, max relative humidity — for the project model.
3. **Run the project model** for the year, starting from `ContaminationState()`:
   - Central stochastic band: run 200 independent full-year passes with
     `numpy.random.default_rng(seed)` for seeds 0..199, using the config's soiling
     values as-is (`event_inputs=None` so the model draws its own dust events). Collect
     the daily `state.dust_soiling_ratio` series of each pass; compute per-day mean,
     5th percentile, and 95th percentile across passes.
   - Deterministic central curve: one additional pass with a config copy where
     `stochastic_std_fraction=0` and `dust_event_probability=0` (build the modified
     `SoilingConfig` via pydantic `model_copy(update=...)` or by revalidating a dumped
     dict — whichever works).
4. **Run `pvlib.soiling.kimber`** on the hourly rain series, once per soiling rate in
   `[0.0005, 0.001, 0.002, 0.003, 0.005]` per day (literature arid-site range; cite
   Kimber et al. 2006 and Ilse et al. 2019 Joule, both already in
   `docs/calibration/source_bibliography.md`). Run each rate twice: with pvlib's default
   `cleaning_threshold`, and with `cleaning_threshold=5.0` to match the project's
   full-rain threshold. Convert loss → ratio.
5. **Run `pvlib.soiling.hsu`** on the hourly rain series with `surface_tilt=25`,
   `cleaning_threshold=5.0` (confirm the parameter name from the docstring), and
   literature-typical Riyadh particulate levels: PM2.5 = 60 µg/m³ and PM10 = 150 µg/m³
   held constant. CHECK THE UNITS in the pvlib docstring: if it expects g/m³, pass
   `60e-6` and `150e-6`. Label these values "literature-typical annual means,
   provisional" in the report.
6. **Write the report** to `outputs/soiling_benchmark/` (create the dir):
   - `soiling_benchmark.png`: daily soiling ratio over the year — project mean line
     with shaded 5–95% band, the kimber curves (thin lines, labeled by rate), and the
     hsu curve. One matplotlib figure, legible legend.
   - `soiling_benchmark.json` and `soiling_benchmark.md` containing, for every model
     variant: annual mean soiling ratio, minimum ratio, annual average loss
     (1 − mean ratio) in percent, and count of rain-cleaning resets (days with rain ≥
     5.0 mm). Then a verdict section: state whether the project's central annual loss
     falls inside the kimber envelope spanned by the swept rates, which kimber rate it
     tracks most closely (nearest annual loss), and how it compares to hsu. End with
     the caveat, in substance: this corroborates model form against published models
     under literature parameters; it is NOT validation against measured Riyadh soiling
     data.
7. **Unit test** `tests/unit/test_soiling_benchmark_script.py`: load the script module
   via `importlib.util.spec_from_file_location`; build a synthetic 30-day weather frame
   (e.g. zero rain for 20 days, one 10 mm day, then dry); assert (a) the project-model
   runner returns a daily ratio series of length 30 that decreases during dry days and
   jumps up on the rain day, and (b) your kimber wrapper returns a ratio series with
   ratio 1.0 restored after the rain day. No network in tests (build the synthetic
   frame directly; do not load real weather in the test).

## Constraints

- Do NOT modify anything under `src/`. Script + test + generated report only.
- Do not change golden regression data. If existing tests fail, your change is wrong.
- Runtime sanity: 200 passes × 365 daily updates is small (<1 minute); if it is much
  slower, something is wrong — investigate rather than reducing passes.
- Keep the script ruff-clean (ruff checks the whole repo).
- If anything in this brief contradicts what you find in the code (e.g. pvlib
  signatures differ), adapt to the code/library and note it in your report; if it
  blocks the comparison itself, STOP and report.
- Do not commit or push. Do not create accounts or API keys.

## Files you may create or modify

- `scripts/benchmark_soiling_vs_published.py` (new)
- `tests/unit/test_soiling_benchmark_script.py` (new)
- Generated artifacts under `outputs/soiling_benchmark/` (do not add to git)

## Verification (all must pass before you finish)

```
python -m pytest -q
python -m ruff format <only the files you changed>
python -m ruff check .
python -m mypy src
```

If `import solarclean` fails, first run: `python -m pip install -e ".[dev]"`

Then run the script end-to-end (`python scripts/benchmark_soiling_vs_published.py`) —
it should work offline via the existing weather cache — and confirm all three report
files appear.

## Final report

List: files changed; the project model's central annual soiling loss %; the kimber rate
it tracks most closely and the kimber envelope range; the hsu annual loss; the verdict
(inside/outside envelope); test/lint/type results; anything you could not complete.
