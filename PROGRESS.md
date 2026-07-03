# SolarClean-DT Progress

## Current Source

- Active prompt from 2026-06-29 is the source of truth.
- Active T1 continuation prompt from 2026-06-30 adds contract-freeze scope on top of completed Phase 1-3.5 work.
- Repository brief files searched: `SolarClean-DT_Internship_Brief.pdf`, `PROJECT_BRIEF.md`, `README.md`, `PLAN.md`, and `AGENTS.md`.
- No existing brief was found before implementation.

## Checkpoints

### Checkpoint 1: Repository And Architecture Foundation

- Status: completed.
- Evidence gathered:
  - Workspace root: `C:\Users\PC\Desktop\PersonalProj\SolarCell_Simulation`.
  - Python executable: `C:\Users\PC\miniconda3\python.exe`, version `3.13.5`.
  - Existing workspace content before build: `.agents`, `.codex`, `.git`.
  - `git` does not currently recognize the workspace as a repository.
  - Installed packages before project setup: `numpy`, `pandas`, `pydantic`, `yaml`, `httpx`, `matplotlib`, and `typer`; missing `pvlib`, `pytest`, `ruff`, and `mypy`.
- Design decisions recorded:
  - Use prompt as source of truth because no brief was present.
  - Work in the current workspace because the active goal explicitly requests autonomous implementation and the repo is not recognized by git.
- Built:
  - `src` package layout, configs, tests, documentation skeleton, `pyproject.toml`, `PLAN.md`, `AGENTS.md`, and `README.md`.

### Checkpoint 2: Weather Provider Subsystem

- Status: completed.
- Built:
  - Provider-independent `WeatherRequest`, `WeatherDataset`, and `WeatherProvider` protocol.
  - `FixtureWeatherProvider`, `CsvWeatherProvider`, `NasaPowerWeatherProvider`, and `WeatherCache`.
  - NASA POWER adapter maps `ALLSKY_SFC_SW_DWN`, `ALLSKY_SFC_SW_DNI`, `ALLSKY_SFC_SW_DIFF`, `T2M`, `WS2M`, `RH2M`, and `PRECTOTCORR` into canonical columns.
- Verified:
  - Canonical schema validation, timezone validation, duplicate timestamp rejection, CSV column/unit mapping, cache round trip, and mocked malformed NASA responses.

### Checkpoint 3: Phase 1 Clean PV Model

- Status: completed.
- Built:
  - `PVSystemConfig`, `CleanEnergyProfile`, `PVPowerModel` protocol, and pvlib PVWatts adapter.
  - `RunCleanPVSimulation` and `solarclean run-clean`.
- Verified:
  - Night power equals zero, power and energy are non-negative, fixture energy is positive, scaling from one panel to 10,000 panels occurs once, and daily aggregation follows the Asia/Riyadh calendar.

### Checkpoint 4: Phase 2 Baseline Soiling Simulation

- Status: completed.
- Built:
  - `ContaminationState`, `DailyEnvironment`, `SoilingUpdate`, `SimulationEvent`, `BaselineSimulationResult`, and `BaselineSimulationEngine`.
  - Configurable Kimber-style soiling model with rainfall cleaning and no manual cleaning.
  - `RunBaselineSimulation` and `solarclean run-baseline`.
- Verified:
  - Zero accumulation preserves clean state, dry days reduce soiling ratio, partial and strong rain restore within configured bounds, actual energy never exceeds clean energy, and identical seeds reproduce events/results.

### Checkpoint 5: Phase 3 Cohort Farm Model

- Status: completed.
- Built:
  - `FarmRepresentation`, `RepresentativePanelFarm`, `CohortFarm`, `FarmState`, and `CohortState`.
  - Configurable 100 cohort x 100 panel default and sparse bird-dropping events.
- Verified:
  - Cohort panel counts sum to 10,000, homogeneous cohorts equal representative scaling, heterogeneous aggregate equals explicit sum, invalid cohort configuration fails validation, and identical seeds reproduce cohort events.

### Checkpoint 6: Integration, Documentation, And Final Validation

- Status: completed.
- Built:
  - End-to-end fixture tests for fetch weather, Phase 1 clean PV, and Phase 2/3 baseline cohort output generation.
  - README installation and CLI instructions.
  - Architecture, weather-provider, simulation-flow, weather contract, farm-state contract, assumptions, calibration todo, and six ADR documents.
  - Clean local virtual environment install verification.

### Checkpoint 7: Phase 3.5 Git And Validation Foundation

- Status: in progress.
- Evidence gathered:
  - `PROJECT_OVERVIEW.md` existed but was empty before Phase 3.5.
  - `.git` directory existed but `git rev-parse --is-inside-work-tree` failed, so the project was not initialized as a usable git repository.
  - Current architecture keeps domain code independent of NASA, pvlib, CLI, persistence, and plotting.
- Design decisions:
  - Add Phase 3.5 as validation/reporting and reproducibility infrastructure only.
  - Keep Phase 4 behaviors explicitly out of scope.
- Built:
  - Initialized git repository on branch `main`.
  - Added `.gitignore` for generated outputs, caches, venvs, and local cache data.
  - Added Phase 3.5 design and implementation plan docs.
- Verification:
  - `python -m pytest -q`: `29 passed, 1 skipped in 6.01s`.

### Checkpoint 8: Exogenous Event Tape And RNG Streams

- Status: completed.
- Built:
  - `RngStreamFactory` with separate dust, dust-event, bird, cohort-variation, and future-scenario streams.
  - Immutable JSON-serializable `ExogenousEventTape` and `DailyEventInputs`.
  - Baseline engine support for tape-driven soiling, cohort variation, and bird events while preserving seed-based fallback.
- Verification:
  - `python -m pytest tests/unit/test_event_tape.py tests/unit/test_soiling.py tests/unit/test_farm.py -q`: `13 passed in 4.52s`.
  - `python -m pytest -q`: `32 passed, 1 skipped in 4.73s`.

### Checkpoint 9: Full-Year NASA And Simulation Validation

- Status: completed.
- Built:
  - `Phase35Validator` application use case.
  - Weather, energy, farm-equivalence, event-tape, performance, and summary JSON report outputs.
  - CLI commands: `validate-weather`, `validate-phase-3-5`, and `profile-full-year`.
- Verification:
  - `python -m pytest tests/unit/test_phase35_validation.py tests/regression/test_phase35_reports.py -q`: `4 passed in 5.40s`.
  - `python -m pytest -q`: `36 passed, 1 skipped in 5.82s`.
  - `python -m ruff format --check .`: `52 files already formatted`.
  - `python -m ruff check .`: `All checks passed!`.
  - `python -m mypy src`: `Success: no issues found in 40 source files`.
  - `solarclean validate-phase-3-5 --config configs/offline_fixture.yaml`: succeeded and wrote `outputs\offline-fixture-phase-3-5-20260629T195020Z-60a8a5aa`.
  - `solarclean validate-weather --config configs/offline_fixture.yaml`: succeeded and wrote `outputs\offline-fixture-validate-weather-20260629T195058Z-d94389af`.
  - `solarclean profile-full-year --config configs/offline_fixture.yaml`: succeeded and wrote `outputs\offline-fixture-phase-3-5-20260629T195115Z-f8c64704`.
  - `solarclean validate-weather --config configs/riyadh_2025.yaml`: succeeded and wrote `outputs\riyadh-2025-validate-weather-20260629T233826Z-02c47217`.
  - `solarclean validate-phase-3-5 --config configs/riyadh_2025.yaml`: succeeded and wrote `outputs\riyadh-2025-phase-3-5-20260629T233845Z-62f990a5`.
  - `solarclean profile-full-year --config configs/riyadh_2025.yaml`: succeeded and wrote `outputs\riyadh-2025-phase-3-5-20260629T233928Z-c193806b`.

### Checkpoint 10: Calibration, Golden Regression, And Profiling

- Status: completed.
- Built:
  - Calibration registry with low, medium, and high provisional Riyadh soiling presets.
  - `configs/riyadh_soiling_low.yaml`, `configs/riyadh_soiling_medium.yaml`, and `configs/riyadh_soiling_high.yaml`.
  - Deterministic multi-week golden regression fixture at `data/fixtures/golden_multiweek_expected.json`.
- Verification:
  - `python -m pytest tests/unit/test_calibration_registry.py tests/regression/test_golden_multiweek.py -q`: `3 passed in 5.31s`.
  - `python -m pytest -q`: `39 passed, 1 skipped in 11.99s`.
  - `python -m pytest --cov=solarclean --cov-report=term-missing`: `39 passed, 1 skipped`, total coverage `89%`.
  - `python -m ruff format --check .`: `52 files already formatted`.
  - `python -m ruff check .`: `All checks passed!`.
  - `python -m mypy src`: `Success: no issues found in 40 source files`.
  - Clean install: `.venv_clean\Scripts\python.exe -m pip install -e ".[dev]"` succeeded.
  - Clean install tests: `.venv_clean\Scripts\python.exe -m pytest -q`: `39 passed, 1 skipped in 16.97s`.
  - Clean install CLI: `.venv_clean\Scripts\solarclean.exe validate-phase-3-5 --config configs/offline_fixture.yaml` succeeded and wrote `outputs\offline-fixture-phase-3-5-20260629T234740Z-c8c03875`.

### Checkpoint 11: T1 Shared Contract Freeze

- Status: completed.
- Audit findings:
  - Already existed: provider-independent weather input, clean PV profile, farm states, exogenous event tape, baseline simulation result, validation reports, output writer, and Phase 3.5 reports.
  - Missing before T1: generic scenario context, mitigation strategy protocol, common daily/annual scenario result models, operational quantities, domain-event contract, extension-preserving result handling, comparison input, and generic scenario persistence contract.
- Built so far:
  - T1 design spec at `docs/superpowers/specs/2026-06-30-solarclean-dt-t1-contract-freeze-design.md`.
  - T1 implementation plan at `docs/superpowers/plans/2026-06-30-solarclean-dt-t1-contract-freeze.md`.
  - Shared contracts in `src/solarclean/domain/scenario/contracts.py`.
  - Shared `ScenarioSimulationEngine`.
  - `BaselineStrategy` adapter and compatibility-preserving `BaselineSimulationEngine` delegation.
  - Generic `OutputWriter.write_scenario_result()`.
  - Contract documentation, T1 architecture diagram, T2/T3/T4 integration checklist, ownership guidance, and ADR-009.
- Verification so far:
  - RED: `python -m pytest tests/unit/test_scenario_contracts.py tests/regression/test_t1_baseline_compatibility.py -q` failed with `ModuleNotFoundError: No module named 'solarclean.domain.scenario'`.
  - GREEN after implementation: `python -m pytest tests/unit/test_scenario_contracts.py tests/regression/test_t1_baseline_compatibility.py -q`: `5 passed in 3.66s`.
  - Targeted regression slice: `python -m pytest tests/unit/test_scenario_contracts.py tests/regression/test_t1_baseline_compatibility.py tests/unit/test_soiling.py tests/unit/test_event_tape.py tests/regression/test_end_to_end.py -q`: `16 passed in 5.38s`.
  - Full suite: `python -m pytest -q`: `44 passed, 1 skipped in 7.88s`.
  - Format check: `python -m ruff format --check .`: `58 files already formatted`.
  - Lint: `python -m ruff check .`: `All checks passed!`.
  - Type check: `python -m mypy src`: `Success: no issues found in 44 source files`.
- Frozen contracts:
  - `ScenarioContext`, `DailyScenarioInput`, `MitigationStrategy`, `StrategyStep`, `DailyScenarioResult`, `AnnualScenarioResult`, `OperationalQuantities`, `DomainEvent`, `ScenarioComparisonInput`, and `ScenarioOutputBundle`.
  - `ScenarioSimulationEngine` owns the annual daily loop and delegates only day-level behavior to strategies.
  - `BaselineSimulationEngine` remains backward-compatible and delegates through `BaselineStrategy`.
  - Generic persistence output contract writes `scenario_daily_results.csv`, `scenario_events.csv`, and `scenario_summary.json`.
- Baseline unchanged evidence:
  - `tests/regression/test_t1_baseline_compatibility.py` verifies the offline fixture baseline clean energy, actual energy, soiling loss, event count, and cohort rows against `data/fixtures/regression_expected_offline_summary.json`.
  - Existing Phase 1-3.5 regression tests still pass in the full suite.

### Checkpoint 12: T5 Scientific And Economic Calibration

- Status: completed.
- Built:
  - Authoritative shared parameter registry at `data/calibration/parameter_registry.yaml`.
  - Calibration documentation under `docs/calibration/`:
    - `parameter_registry.md`
    - `source_bibliography.md`
    - `evidence_notes.md`
    - `open_issues.md`
    - `interface_requests.md`
  - Current-model low, central, and high calibration overlays:
    - `configs/calibration/low.yaml`
    - `configs/calibration/central.yaml`
    - `configs/calibration/high.yaml`
  - `ParameterRegistry` and `CalibrationParameter` loader/query types in `src/solarclean/domain/calibration/registry.py`.
  - `scripts/calibration/run_preset_sensitivity.py`, which resolves calibration overlays through `SolarCleanConfig` and calls `Phase35Validator` for executable runs.
- Registry coverage:
  - Dry-weather soiling rate, minimum soiling floor, stochastic daily variation, March/April/May seasonal multipliers, dust-event probability and severity bounds.
  - Partial and strong rainfall thresholds and cleaning efficiencies.
  - Bird-dropping event frequency, coverage bounds, power-loss mapping, rainfall removal, and a blocked explicit persistence request.
  - Future T2 CV confusion-matrix and severity-error inputs.
  - Future T2 inspection, flight duration, battery, cleaning speed, water, and labor inputs.
  - Future T3 coating cost, dust-reduction effectiveness, cooling, dew, degradation, optical penalty, and water-collection inputs.
  - Future T3 economics inputs for tariff, labor, water, drone equipment, discount rate, and useful life.
- Interface requests:
  - T2 owns future `reactive_cv.*` detector, operations, and cleaning paths.
  - T3 owns future `coating.*` and `economics.*` paths.
  - T1/core must decide whether to add `bird_droppings.persistence_days_without_rain`.
  - T5 did not add future-owner config sections to `SolarCleanConfig`, so current presets remain accepted by the strict production model.
- Unresolved parameters and later review:
  - Soiling, dust-event, rainfall-cleaning, and bird-dropping values remain provisional until measured Saudi/Riyadh site data are available.
  - CV values require T2 model/test-set evidence.
  - Drone and cleaning operations require T2 route, hardware, heat-derating, and crew assumptions.
  - Coating and economics values require T3 technology selection, vendor quotes, tariff-class confirmation, water-delivery cost, finance assumptions, and useful-life review.
- Verification:
  - RED first: `python -m pytest tests/unit/test_t5_calibration_registry.py -q` failed on missing `ParameterRegistry`, then passed after implementation.
  - `python -m pytest -p no:cacheprovider tests/unit/test_t5_calibration_registry.py -q` with local `PYTHONPATH=src`: `3 passed`.
  - Full suite with elevated temp access because sandboxed pytest temp cleanup was blocked: `python -m pytest --basetemp "$env:TEMP\solarclean_pytest_tmp_251d" -q`: `47 passed, 1 skipped in 17.93s`.
  - `python -m ruff format --check .`: `60 files already formatted`.
  - `python -m ruff check .`: `All checks passed!`.
  - `python -m mypy src`: `Success: no issues found in 44 source files`.
  - Dry-run script: `python scripts/calibration/run_preset_sensitivity.py --base-config configs/offline_fixture.yaml --preset-dir configs/calibration --dry-run` succeeded and reported `Phase35Validator` as the production interface.
  - Executable script: `python scripts/calibration/run_preset_sensitivity.py --base-config configs/offline_fixture.yaml --preset-dir configs/calibration` ran low, central, and high presets through `Phase35Validator`; offline fixture soiling loss increased from `0.4315884571418468%` to `0.8896787922616349%` to `2.3114260961408584%`.

## Phase 3.5 Annual NASA 2025 Results

From `outputs\riyadh-2025-phase-3-5-20260629T233845Z-62f990a5` and the explicit profile run `outputs\riyadh-2025-phase-3-5-20260629T233928Z-c193806b`:

- Weather rows: `8760` expected and `8760` observed.
- Weather period: `2025-01-01T00:00:00+03:00` through `2025-12-31T23:00:00+03:00`.
- Weather timezone: `Asia/Riyadh`.
- Weather gaps: `0`.
- Weather duplicates: `0`.
- Suspicious weather values: `0`.
- Weather checksum: `19b4d25e020013822edcb945809fcc3f5b87ad5bbe3c4e0f3416d6362047b676`.
- Clean PV energy: `7458701.439620493 kWh`.
- Actual no-intervention baseline energy: `5612976.603475776 kWh`.
- Soiling loss: `1845724.8361447174 kWh`.
- Soiling loss percent: `24.745927304989834%`.
- Specific yield: `1864.6753599051233 kWh/kWp`.
- Capacity factor: `21.286248400743414%`.
- Clipping energy: `325843.72656679846 kWh`.
- Clipping percent of DC energy: `4.185777326877402%`.
- Contamination event count: `1118`.
- Rain event count: `27`.
- Event tape checksum: `46acc9898bf11b13ab137dfe6a1d4091e17a1723f8612e5d2143c095ea0263ee`.
- Event tape records: `37233`.
- Farm equivalence passed: `true`.
- Representative/cohort absolute difference: `9.313225746154785e-10 kWh`, tolerance `1e-06 kWh`.
- Full-year profile runtime: `15.512733099996694 s`.
- Full-year profile peak memory: `55.08552265167236 MB`.
- Full-year profile output size: `12.858773231506348 MB`.

## Phase 3.5 Offline Fixture Smoke Results

From `outputs\offline-fixture-phase-3-5-20260629T195020Z-60a8a5aa\phase35_summary.json`:

- Clean energy: `28042.50025091375 kWh`.
- Actual baseline energy with event tape: `27993.560993712505 kWh`.
- Soiling loss percent: `0.1745181662239594%`.
- Specific yield: `7.010625062728437 kWh/kWp`.
- Capacity factor: `14.605468880684244%`.
- Event tape checksum: `a0048a6d35b3fd8b58cf9240ff4f844c0519735213d32c7562109359c6243493`.
- Farm equivalence passed: `true`.
- Runtime: `0.4125372000016796 s`.
- Peak memory: `0.6248569488525391 MB`.
- Output size: `0.0747528076171875 MB`.

## Verification Log

- `python -m pytest -q`
  - First red run after test scaffold: failed during collection because implementation modules were missing.
  - After implementation, sandboxed run failed because pytest temp-directory setup and cleanup were blocked by sandbox permissions.
  - Phase 1-3 closeout rerun after fixes: `29 passed, 1 skipped in 6.24s`.
  - Phase 3.5 final rerun after annual NASA validation and report work: `39 passed, 1 skipped in 11.99s`.
  - Skip reason: live NASA POWER integration test is disabled by default unless `SOLARCLEAN_RUN_NETWORK_TESTS=1`.
- `python -m pytest --cov=solarclean --cov-report=term-missing`
  - Phase 3.5 final outcome: `39 passed, 1 skipped`, total coverage `89%`.
- `python -m ruff format --check .`
  - Phase 3.5 final outcome: `52 files already formatted`.
- `python -m ruff check .`
  - Phase 3.5 final outcome: `All checks passed!`.
- `python -m mypy src`
  - Phase 3.5 final outcome: `Success: no issues found in 40 source files`.
- `$env:SOLARCLEAN_RUN_NETWORK_TESTS='1'; python -m pytest tests/integration/test_nasa_power_live.py -q`
  - Outcome: `1 passed in 4.98s`.
  - Real NASA POWER retrieval was verified for a one-day hourly Riyadh request.
- Full-year NASA verification:
  - `solarclean validate-weather --config configs/riyadh_2025.yaml`: succeeded.
  - `solarclean validate-phase-3-5 --config configs/riyadh_2025.yaml`: succeeded.
  - `solarclean profile-full-year --config configs/riyadh_2025.yaml`: succeeded.
  - Full-year NASA POWER retrieval and caching were verified for the complete 2025 Riyadh hourly dataset.
- Clean environment verification:
  - Created `.venv_clean` using `python -m venv .venv_clean`.
  - Ran `.venv_clean\Scripts\python.exe -m pip install -e ".[dev]"` successfully.
  - Ran `.venv_clean\Scripts\python.exe -m pytest -q`: `39 passed, 1 skipped in 16.97s`.
  - Ran `.venv_clean\Scripts\solarclean.exe validate-phase-3-5 --config configs/offline_fixture.yaml` successfully.
- Documented offline CLI verification:
  - `solarclean fetch-weather --config configs/offline_fixture.yaml` succeeded.
  - `solarclean run-clean --config configs/offline_fixture.yaml` succeeded.
  - `solarclean run-baseline --config configs/offline_fixture.yaml` succeeded.
  - `solarclean validate-weather --config configs/offline_fixture.yaml` succeeded.
  - `solarclean validate-phase-3-5 --config configs/offline_fixture.yaml` succeeded.
  - `solarclean profile-full-year --config configs/offline_fixture.yaml` succeeded.

## Sample Fixture Results

The deterministic offline fixture covers 2025-01-01 through 2025-01-02 inclusive.

- Clean PV energy: `28042.50025091375 kWh`.
- Baseline actual energy: `28003.317904929903 kWh`.
- Baseline soiling loss: `39.18234598384515 kWh`.
- Baseline soiling loss percent: `0.13972486630384687%`.
- Cohort daily output rows: `200`.
- Baseline event count: `4`.

## Known Remaining Work For Later Phases

- Next clean extension point for Phase 4: add scenario controllers that consume the immutable event tape and reserve scenario-specific uncertainty to `RngStream.FUTURE_SCENARIO`, without changing clean PV, weather providers, or baseline domain contracts.
- Coating cost calibration, annualization, and water valuation through T5/T4.
- Techno-economic model.
- Sensitivity analysis and Monte Carlo sweeps.
- Web dashboard, database, authentication, cloud, and Docker deployment.
- CV observer, drone, and crew parameter calibration through T5 (see `docs/assumptions/reactive_cv_scenario.md`).

### Checkpoint 12: T3 KAUST-Inspired Coating Scenario

- Status: completed.
- Built:
  - `CoatingStrategy` implemented through the shared `ScenarioSimulationEngine`.
  - Coating physics for dew point, coated-surface cooling, condensation, passive dust cleaning, limited bird-dropping removal, optical effect, thermal effect, and cleanliness effect.
  - `CoatingCostBasis` with coated area, material loading, material cost, surface preparation, application labor, process energy, setup cost, inspection/maintenance quantities, useful life, reapplication interval, and deployment mode.
  - `run-coating` CLI and generic scenario output artifacts.
  - Weak, central, strong, and paper-calibration coating configs.
- Source limitation:
  - The named paper PDF was not present in the workspace. The implementation uses prompt-provided paper facts as calibration anchors and marks cost/process values provisional unless directly prompt-quoted.
- Deployment limitation:
  - The prompt reports a 400 C, 30 minute treatment. Direct field application to installed PV modules is not demonstrated.
- T4/T5 interface requests:
  - T4 should annualize coating cost and value optional water collection outside coating physics.
  - T5 should replace provisional material loading, industrial process, application labor, maintenance, and useful-life assumptions with sourced registry values.
- Verification:
  - Focused T3 suite: `17 passed, 1 warning`.
  - Full suite: `61 passed, 1 skipped`.
  - Coverage: `61 passed, 1 skipped`, total coverage `91%`.
  - Ruff format check: `67 files already formatted`.
  - Ruff lint: `All checks passed!`.
  - Mypy: `Success: no issues found in 49 source files`.
  - CLI smoke: `python -m solarclean.cli.main run-coating --config configs/offline_fixture.yaml` wrote `outputs\offline-fixture-run-coating-20260630T211646Z-1afa868a` with scenario daily results, scenario events, scenario summary, and coating comparison summary.

### Checkpoint 13: T2 Reactive CV Drone And Crew-Cleaning Scenario

- Status: completed.
- Built:
  - `ReactiveCVStrategy` implemented through the shared `ScenarioSimulationEngine`, reusing `CohortState`/`CohortFarm`/`KimberStyleSoilingModel` for true state so comparisons with baseline and coating stay fair.
  - `InspectionScheduler` (rotating cohort coverage), `DroneFleet` (flight capacity, weather cancellation, drone/compute energy), `StatisticalCVObserver` (recall, false-positive rate, missed images, severity/confidence noise) and `PerfectInformationObserver` (zero-error benchmark, same pipeline otherwise).
  - `ThresholdDispatchPolicy` operating only on `DispatchSignal` (no ground-truth field, by type -- not just convention) with a persistent, aging cleaning queue and crew-capacity limiting.
  - `CleaningCrew` targeted per-cohort cleaning with configurable dust/bird removal efficiency, crew hours, and water use.
  - `metrics.summarize_detection_performance()` aggregating realized precision/recall/F1 from per-day confusion-matrix counters recorded for evaluation only.
  - `run-reactive` CLI command and `RunReactiveSimulation`/`_reactive_summary`, which also runs the perfect-information benchmark (when `reactive_cv.perfect_information_benchmark` is enabled) and reports `cv_error_energy_cost_kwh`.
  - `configs/reactive_central.yaml`, ADR-011, `docs/data_contracts/reactive_cv_scenario.md`, `docs/assumptions/reactive_cv_scenario.md`.
- Isolation guarantee:
  - All CV/drone/dispatch randomness draws from `cv_rng`, spawned once from the shared per-strategy `rng` via `numpy.random.Generator.spawn()` inside `initial_state()`. `spawn()` does not consume from the parent generator's draw sequence, so no reactive-only config can perturb the true dust/bird simulation. Verified directly (`test_cv_rng_spawn_does_not_perturb_the_shared_rng_draw_sequence`) and at the scenario level for day 1 true-state events across differing CV configs and against baseline (`test_changing_cv_randomness_does_not_change_true_dust_or_bird_events`).
- Source limitation:
  - No CV model, drone hardware, or crew operations data was available in the workspace. Every `ReactiveCVConfig` default is a provisional, round-number placeholder; see `docs/assumptions/reactive_cv_scenario.md` for the full list and T5 hand-off.
- Issue found in existing T1/core code (not fixed here; flagged in ADR-011):
  - `BaselineStrategy`'s carried-over `FarmState.date` never advances past day 1 internally, so bird-dropping `DomainEvent`s attached to `daily_results[1:]` in the baseline scenario carry day 1's date in `scenario_events.csv`. `DailyScenarioResult.date` itself is unaffected. `ReactiveCVStrategy` does not have this problem (it passes `day_input.date` explicitly).
- T4/T5 interface requests:
  - T4 should own all cost valuation; `OperationalQuantities.opex_cost`/`capex_cost` are left at `0.0` throughout T2.
  - T5 should replace the CV observer, drone, and crew defaults with sourced values, and should derive the "dirty" detection threshold economically once T4 exists.
- Verification:
  - Focused T2 suite: `37 passed`.
  - Full suite: `113 passed, 1 skipped`.
  - Coverage: `113 passed, 1 skipped`, total coverage `90%`.
  - Ruff format check: clean.
  - Ruff lint: `All checks passed!`.
  - Mypy: `Success: no issues found in 58 source files` (checked with `--python-version 3.12` locally; the repo's configured `python_version = "3.11"` currently fails to import numpy's stubs under this sandbox's Python 3.12-only toolchain, a pre-existing environment mismatch unrelated to T2).
  - CLI smoke: `solarclean run-reactive --config configs/reactive_central.yaml` wrote a run directory with scenario daily results, scenario events, scenario summary, and `reactive_comparison_summary.json` including the perfect-information benchmark comparison.

