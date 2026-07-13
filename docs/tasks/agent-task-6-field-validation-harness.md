# Task 6: Field-data validation harness with synthetic round-trip proof

## Project context

- You are working in the repo `SolarCell_Comparitive_Sim` (Windows). It contains a Python
  3.11+ package named `solarclean` under `src/`, installed editable via pip.
- SolarClean-DT simulates a PV farm and compares dust-mitigation scenarios. It already
  supports measured-station weather via a CSV weather provider (see README section
  "Local Riyadh CSV Replacement"), and has internal validation reports (Phase 3.5) that
  check invariants — but it has NO way to compare simulated energy against measured
  production data. Read `README.md` first.

## The problem you are fixing

The simulator is verified (code does what the model says) but not validated (model
matches reality). The blocker is partly data, but equally that no harness exists: even
if someone handed the team a real farm dataset tomorrow, there is no code to ingest it,
align it with a simulation, and compute accuracy metrics. Your job: build that harness
with a documented CSV contract and staged metrics, and PROVE it works end-to-end with a
synthetic round-trip test (simulate → add noise → validate → recover known accuracy).
Real public data acquisition is a stretch goal, not the core deliverable.

## Before you start, read these files

1. `README.md` — "Local Riyadh CSV Replacement" (the CSV weather provider config) and
   "Offline Tests" (fixture configs come from `tests/config_factory.py`).
2. `src/solarclean/infrastructure/weather/csv_provider.py` — the existing measured-
   weather ingestion you will reuse (do not duplicate it).
3. `src/solarclean/domain/validation/reports.py` and `docs/architecture/phase_3_5_validation.md`
   — existing validation-report style to imitate.
4. `src/solarclean/application/comparison.py` OR the baseline-run use case in
   `src/solarclean/application/use_cases.py` — you need a way to run the BASELINE
   scenario (no intervention) for a period and obtain its daily actual energy series;
   find the cleanest existing entry point rather than building a new engine path.
5. `src/solarclean/cli/main.py` — Typer command style.
6. `src/solarclean/infrastructure/persistence/outputs.py` and `reports.py` — how run
   directories and JSON reports are written.

## Steps

1. **Document the dataset contract** in `docs/data_contracts/field_validation_dataset.md`:
   - Measured-production CSV: columns `timestamp` (ISO 8601 WITH timezone offset) and
     `measured_ac_energy_kwh` (energy per interval); optional column `cleaning_event`
     (0/1, marking days the plant was manually cleaned). Hourly or daily rows accepted;
     hourly is summed to daily in `Asia/…` site-local time.
   - Weather: provided separately through the EXISTING csv weather provider config (link
     to the README section; do not invent a second weather path).
   - Site parameters (capacity, tilt, azimuth, coordinates): provided via a normal
     project config YAML pointing at that weather CSV.
2. **Create the metrics/domain module**
   `src/solarclean/domain/validation/field_validation.py` with pure, unit-testable
   functions:
   - `daily_align(simulated: pd.Series, measured: pd.Series) -> pd.DataFrame` — inner
     join on date; raise a clear error if overlap is under 30 days.
   - `mae(df)`, `rmse(df)`, `mbe(df)` (mean bias, simulated − measured), `r2(df)` —
     on daily energy; also each as percent of mean measured daily energy where
     meaningful (MAE%, RMSE%, MBE%).
   - `stage_metrics(df, precip_daily_mm, cleaning_flags, full_rain_threshold_mm)` →
     a dict with the four stages:
     - `clean_days`: metrics restricted to days 0–2 after a cleaning event or after
       rain ≥ threshold (tests the clean-generation model).
     - `decline_slopes`: for each dry spell ≥ 10 days between cleaning/rain events, the
       linear slope (per day) of daily performance index simulated vs measured, where
       performance index = actual energy / clean-model energy if a clean reference is
       available, else normalized daily energy; report the mean slope of each and the
       ratio (tests the soiling-rate realism).
     - `recovery`: mean step-change in daily energy across cleaning/rain events,
       simulated vs measured (tests cleaning-restoration realism).
     - `holdout`: metrics computed ONLY on rows after a caller-supplied
       `holdout_start` date, meant to be excluded from any tuning.
3. **Create the application use case** `src/solarclean/application/field_validation.py`:
   load config → run the baseline scenario for the dataset period (reuse the existing
   entry point you found; `write_artifacts=False`-style, no full artifact package) →
   load + daily-aggregate the measured CSV → compute all metrics →
   write one run directory containing `field_validation_report.json` and
   `field_validation_report.md` (headline table: MAE/RMSE/MBE/R² overall and per
   stage, days used per stage, holdout metrics separated, plus an explicit note that
   metrics on the tuning period are NOT evidence of predictive accuracy — only holdout
   metrics are).
4. **CLI command** `validate-field` in `src/solarclean/cli/main.py` with options:
   `--config` (project YAML whose weather section points at the measured-weather CSV),
   `--measured-csv` (path), `--holdout-start` (YYYY-MM-DD, required). Follow existing
   command style.
5. **Synthetic round-trip test** (the core proof; offline):
   `tests/integration/test_field_validation_roundtrip.py`:
   a. Build a fixture config via `tests/config_factory.py`; run the baseline scenario;
      take its daily actual energy as ground truth.
   b. Create a synthetic "measured" CSV: ground truth × multiplicative Gaussian noise,
      sigma = 2%, seeded (`numpy.random.default_rng(0)`).
   c. Run the full harness (use case, not just the metrics functions) against that CSV
      with a holdout covering the last 25% of days.
   d. Assert: R² > 0.95 overall AND on holdout; |MBE%| < 1%; MAE% between 0.5% and 5%
      (noise floor sanity: it should be ≈ 2×sigma/√(π/2) ≈ 1.6%, so this band is
      generous but nonzero); the report files exist and parse as JSON.
   e. A negative control: multiply the synthetic measured series by 1.10 and assert
      MBE% detects ≈ −10% bias (harness catches systematic error).
6. Plus focused unit tests `tests/unit/test_field_validation_metrics.py` for the pure
   functions on tiny hand-built frames (5–10 rows, exact expected values).
7. **Stretch goal (attempt ONLY after everything above is done and passing):** try to
   download one real desert PV dataset with daily production, e.g. from the public
   DKASC Alice Springs site (dkasolarcentre.com.au) or NREL PVDAQ public S3/OEDI data.
   HARD RULES: no account creation, no API-key signup, no scraping behind auth. If a
   plain HTTP download of a CSV works, convert it to the documented contract, run
   `validate-field`, and include the metrics in your report, clearly labeled as a
   different-site (not Riyadh) pipeline demonstration. If it does not work within a
   modest effort, STOP and write down exactly what blocked you — that is an acceptable
   outcome; the harness plus synthetic proof is the deliverable.

## Constraints

- Touch ONLY the files listed below. Do not modify the simulation engine, scenario
  strategies, soiling model, or economics.
- Do not change existing golden regression data. If golden tests fail, your change is
  wrong.
- mypy runs strict on `src/`: fully annotate all new code. Pure functions must not do
  I/O.
- If the baseline-run entry point does not expose a daily actual-energy series cleanly,
  STOP and report what is available rather than restructuring application code.
- Do not commit or push.

## Files you may create or modify

- `src/solarclean/domain/validation/field_validation.py` (new)
- `src/solarclean/application/field_validation.py` (new)
- `src/solarclean/cli/main.py` (add one command only)
- `docs/data_contracts/field_validation_dataset.md` (new)
- `tests/unit/test_field_validation_metrics.py`,
  `tests/integration/test_field_validation_roundtrip.py` (new)
- If the stretch goal succeeds: a small converter script `scripts/convert_field_dataset.py`
  and data under `data/external/` (do not add downloaded data to git)

## Verification (all must pass before you finish)

```
python -m pytest -q
python -m ruff format <only the files you changed>
python -m ruff check .
python -m mypy src
```

If `import solarclean` fails, first run: `python -m pip install -e ".[dev]"`

## Final report

List: files changed; the round-trip test's recovered metrics (MAE%, RMSE%, MBE%, R²
overall and holdout) proving the harness works; the negative-control result; stretch
goal outcome (metrics or the exact blocker); test/lint/type results; anything you could
not complete.
