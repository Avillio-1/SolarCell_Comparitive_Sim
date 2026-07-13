# Task 2: Multi-year weather robustness command (`compare-multi-year`)

## Project context

- You are working in the repo `SolarCell_Comparitive_Sim` (Windows). It contains a Python
  3.11+ package named `solarclean` under `src/`, installed editable via pip.
- SolarClean-DT simulates a 10,000-panel PV farm in Riyadh and compares three
  dust-mitigation scenarios (baseline / reactive cleaning / coating) using live NASA
  POWER weather for a configured year, an economics layer, and a Typer CLI. Read
  `README.md` first.

## The problem you are fixing

Every headline result currently comes from a single weather year (2025). Rain timing
dominates annual soiling loss — the project's own tuning target was ~25% annual no-clean
loss, yet the real 2025 NASA weather produced 13.9%, purely because of when it rained.
A single year is one draw from a distribution. Your job: add a command that runs the
full three-scenario comparison once per historical weather year (default 2019–2025) and
reports how stable the results are across years.

## Before you start, read these files

1. `src/solarclean/application/comparison.py` — the `CompareAllScenarios` use case, its
   constructor/`run` signature, the `write_artifacts` flag, and the module-level
   `_load_weather` helper.
2. `src/solarclean/application/sensitivity.py` — ONLY as a pattern reference: it shows
   how to run `CompareAllScenarios` repeatedly as a black box with
   `write_artifacts=False` and how results/reconciliation failures are extracted.
3. `src/solarclean/application/monte_carlo.py` — same pattern reference, plus how an
   aggregated experiment persists one run directory at the end via `OutputWriter`
   (`src/solarclean/infrastructure/persistence/outputs.py`).
4. `src/solarclean/cli/main.py` — how existing Typer commands are declared.
5. `src/solarclean/config/models.py` — `SolarCleanConfig`, especially
   `simulation.start` / `simulation.end` types and validators.
6. `configs/default.yaml` — note `weather.provider: nasa_power` with
   `cache_enabled: true` (fetches are cached per coordinate/period under
   `data/cache/weather`).

## Steps

1. Create `src/solarclean/application/multi_year.py` containing:
   - A frozen dataclass `YearResult` holding: `year: int`, plus per-scenario
     (`baseline`, `reactive`, `coating`) values of `annual_clean_energy_kwh`,
     `annual_actual_energy_kwh`, `annual_energy_loss_percent`,
     `energy_gain_vs_baseline_percent`, `net_annual_benefit_sar`,
     `incremental_net_annual_benefit_vs_baseline_sar`, and the `winner` scenario id,
     plus `reconciled: bool`. Extract these from the `ComparisonResult` the same way
     `sensitivity.py` / `monte_carlo.py` do — copy their extraction approach, do not
     invent new paths into the result object.
   - A pure function `aggregate_years(results: Sequence[YearResult]) -> dict[str, object]`
     that computes, per scenario: mean, standard deviation, minimum, maximum of each
     numeric metric across years; plus `winner_counts` (how many years each scenario
     won) and `winner_by_year`. Keep it a pure function — it will be unit tested
     directly.
   - A runner function/class `run_multi_year_comparison(config, start_year, end_year,
     output_writer_or_path, progress_callback=None)` that for each year:
     a. Builds a per-year config: `payload = config.model_dump(mode="python")`, set
        `payload["simulation"]["start"] = datetime.fromisoformat(f"{year}-01-01T00:00:00+03:00")`
        and `payload["simulation"]["end"] = datetime.fromisoformat(f"{year}-12-31T23:00:00+03:00")`,
        then `SolarCleanConfig.model_validate(payload)`. (If `model_dump` round-tripping
        fails validation for reasons unrelated to your edit, report it — do not patch
        validators.)
     b. Runs `CompareAllScenarios` with `write_artifacts=False`, loading weather per
        year exactly the way the class loads it when no preloaded weather is injected
        (or via `_load_weather(per_year_config)` if injection is required — follow
        whichever pattern `comparison.py` actually supports).
     c. If the NASA fetch for a year fails (network error), record the year as failed
        with the error message and CONTINUE with remaining years. Require at least 3
        successful years to produce the aggregate; otherwise raise a clear error.
2. Persist one run directory (reuse `OutputWriter` conventions used by
   `monte_carlo.py`) containing:
   - `multi_year_scenario_summary.csv` — one row per (year, scenario) with the metrics
     above, units in column names where the existing CSVs do that.
   - `multi_year_summary.json` — the `aggregate_years` output plus metadata: years
     requested, years succeeded/failed, config checksum fields if the other experiment
     writers include them (mirror `monte_carlo.py`'s metadata style).
   - `multi_year_net_benefit.png` — a simple matplotlib line/marker plot, one series
     per scenario, x = year, y = `net_annual_benefit_sar`. Follow the plotting style in
     `src/solarclean/infrastructure/persistence/plots.py` (add the function there).
3. Add a Typer command `compare-multi-year` in `src/solarclean/cli/main.py` with options
   `--config` (default `configs/default.yaml`), `--start-year` (default 2019),
   `--end-year` (default 2025). Follow the exact style of the existing commands
   (help text, config loading, output messages).
4. Tests (offline — no network in tests):
   - `tests/unit/test_multi_year_aggregation.py`: feed `aggregate_years` 3 hand-built
     `YearResult` objects and assert means/std/min/max/winner_counts exactly.
   - A test that builds per-year configs for 2019 and 2020 from the test fixture config
     (see `tests/config_factory.py`) and asserts start/end dates and timezone are
     correct, without running a simulation.
   - Optionally ONE integration test running two full fixture-weather years through the
     runner IF (a) the fixture weather provider supports arbitrary years and (b) total
     runtime stays under ~2 minutes. If either fails, skip this test and say so in your
     report — do not force it.
   - A network-gated live test is optional; if you add one, it must be skipped unless
     env var `SOLARCLEAN_RUN_NETWORK_TESTS=1` (existing pattern, see README).

## Constraints

- Touch ONLY the files listed below. No refactors, renames, or reformatting of
  unrelated code. Do not modify `comparison.py`, `sensitivity.py`, or `monte_carlo.py`.
- Do not change existing golden regression data. If golden tests fail, your change is
  wrong.
- The same random seed (`config.soiling.random_seed`) is intentionally reused across
  years — do not vary it.
- mypy runs strict on `src/`: fully annotate all new code.
- If anything in this brief contradicts what you find in the code, STOP and report the
  discrepancy instead of guessing.
- Do not commit or push. Do not create accounts or API keys (NASA POWER needs no key).

## Files you may create or modify

- `src/solarclean/application/multi_year.py` (new)
- `src/solarclean/cli/main.py` (add one command only)
- `src/solarclean/infrastructure/persistence/plots.py` (add one plot function only)
- `tests/unit/test_multi_year_aggregation.py` (new) and at most one new integration
  test file under `tests/`

## Verification (all must pass before you finish)

```
python -m pytest -q
python -m ruff format <only the files you changed>
python -m ruff check .
python -m mypy src
```

If `import solarclean` fails, first run: `python -m pip install -e ".[dev]"`

Then, if network is available, do ONE live smoke run and include its output in your
report: `solarclean compare-multi-year --config configs/default.yaml --start-year 2023 --end-year 2025`
(first run fetches and caches NASA weather per year; reruns are offline). If network is
unavailable, say so — the code deliverable stands on the offline tests.

## Final report

List: files changed; the CLI command and options; if the live run worked, the per-year
winners and the min→max range of `energy_gain_vs_baseline_percent` for reactive and
coating; test/lint/type results; anything you could not complete.
