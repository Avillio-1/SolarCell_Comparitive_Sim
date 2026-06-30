# SolarClean-DT Phase 1-3, Phase 3.5, And T1 Plan

## Source Of Truth

No existing project brief was found in the repository. The active prompt dated 2026-06-29 is the source of truth for this implementation.

## Architecture Decisions

- Build a Python 3.11+ modular monolith using a `src/solarclean` package.
- Keep domain and simulation code independent of CLI, persistence, pvlib, HTTP, NASA response structures, plotting, databases, dashboards, drones, coating logic, and economics.
- Use dependency inversion with provider protocols for weather, PV power calculation, soiling, and farm representation.
- Use typed Pydantic configuration models at system boundaries and dataclasses for domain results and states.
- Use timezone-aware datetimes and Asia/Riyadh daily aggregation for simulation outputs.
- Use `numpy.random.Generator` with `SeedSequence` spawning for reproducible stochastic dust and bird events.
- Store run outputs in unique directories under `outputs/<run_id>/` using CSV, JSON, YAML, and PNG.
- Keep NASA POWER code isolated in `solarclean.infrastructure.weather.nasa_power`; unit tests use fixture, CSV, or mocked HTTP paths.
- Use explicit pvlib PVWatts functions rather than exposing a raw `ModelChain`, because the domain contract must return SolarClean-owned result objects, keep whole-farm scaling visible, and avoid leaking pvlib objects across the boundary.

## Milestones

Phase 1-3 is complete. Phase 3.5 adds validation, reproducibility, calibration presets, and performance reporting without starting Phase 4. T1 freezes shared scenario contracts for parallel development of future reactive, coating, economics, analytics, and dashboard modules.

### Checkpoint 1: Repository And Architecture Foundation

- Create the `src` layout, configuration, CLI package, documentation folders, tests, and quality tooling.
- Add `PLAN.md`, `PROGRESS.md`, `AGENTS.md`, `pyproject.toml`, and base README structure.
- Define core contracts and high-level application boundaries.

### Checkpoint 2: Weather Provider Subsystem

- Implement provider-independent `WeatherRequest`, `WeatherDataset`, and `WeatherProvider`.
- Implement fixture, CSV, and NASA POWER providers.
- Add canonical schema validation, timezone conversion, units metadata, local caching, and mocked NASA failure tests.

### Checkpoint 3: Phase 1 Clean PV Model

- Implement PV system configuration and `CleanEnergyProfile`.
- Implement `PVWattsPowerModel` behind a `PVPowerModel` protocol.
- Add `RunCleanPVSimulation` and `solarclean run-clean`.
- Save normalized weather, hourly clean energy, daily clean energy, metadata, and summary files.

### Checkpoint 4: Phase 2 Baseline Soiling Simulation

- Implement contamination state, daily environment, soiling updates, events, and baseline result models.
- Implement a configurable Kimber-style soiling model with rainfall cleaning.
- Add `RunBaselineSimulation` and `solarclean run-baseline`.
- Save daily results, event logs, summaries, and diagnostic plots.

### Checkpoint 5: Phase 3 Cohort Farm Model

- Implement `FarmRepresentation`, `RepresentativePanelFarm`, and `CohortFarm`.
- Add cohort state, sparse bird-dropping events, cohort variation, and deterministic RNG hierarchy.
- Validate cohort invariants and output optional cohort-level daily details.

### Checkpoint 6: Integration, Documentation, And Final Validation

- Complete README and architecture/data-contract/assumption/ADR documents.
- Add end-to-end fixture tests and a deterministic regression fixture.
- Run all required verification commands and record outcomes in `PROGRESS.md`.

### Checkpoint 7: Phase 3.5 Git And Validation Foundation

- Initialize git on `main` with generated artifacts ignored.
- Add Phase 3.5 design and plan documentation.
- Preserve all Phase 1-3 behavior while adding validation/reporting interfaces.

### Checkpoint 8: Exogenous Event Tape And RNG Streams

- Replace scenario-dependent stochastic generation with a serializable immutable event tape.
- Use separate deterministic streams for dust, birds, cohort variation, and future scenario-specific uncertainty.
- Preserve deterministic seed-based fallback for existing Phase 1-3 APIs where practical.

### Checkpoint 9: Full-Year NASA And Simulation Validation

- Validate complete 2025 Riyadh NASA POWER hourly weather.
- Report timestamps, gaps, duplicates, units, ranges, timezone, metadata, and checksum.
- Run and validate full-year clean PV and no-intervention baseline simulations.
- Report annual/monthly energy, specific yield, capacity factor, clipping, soiling loss, and contamination/rain events.
- Verify homogeneous representative-panel and cohort-farm equivalence.

### Checkpoint 10: Calibration, Golden Regression, And Profiling

- Create provisional low/medium/high Riyadh soiling presets and registry.
- Add deterministic multi-week golden regression fixture.
- Profile full-year runtime, memory, and output size.
- Update documentation, ADRs, `PLAN.md`, and `PROGRESS.md`.

### Checkpoint 11: T1 Shared Contract Freeze

- Audit existing Phase 1-3.5 contracts and preserve baseline behavior.
- Add frozen scenario context, mitigation strategy protocol, daily and annual scenario results, shared operational quantities, domain-event contract, scenario-specific extensions, comparison input, and generic persistence output contract.
- Ensure `BaselineStrategy`, future `ReactiveCVStrategy`, and future `CoatingStrategy` can use `ScenarioSimulationEngine` without duplicated annual loops or scenario-name conditionals.
- Add mock future strategy tests, immutability tests, extension-preservation tests, and baseline compatibility regression tests.
- Document field names, types, units, ownership, architecture boundaries, T2/T3/T4 checklist, team ownership, and ADR-009.

## Expected Files

- `src/solarclean/domain/environment/*`: provider-independent weather contracts and daily environment.
- `src/solarclean/domain/pv/*`: PV system config, clean energy results, and PV model protocol.
- `src/solarclean/domain/contamination/*`: soiling state, updates, events, and empirical model.
- `src/solarclean/domain/farm/*`: representative and cohort farm abstractions.
- `src/solarclean/domain/simulation/*`: baseline daily loop and result aggregation.
- `src/solarclean/domain/scenario/*`: T1 scenario context, strategy protocol, common daily/annual result models, domain events, operational quantities, and comparison/output contracts.
- `src/solarclean/application/*`: use cases and provider/model factories.
- `src/solarclean/infrastructure/weather/*`: NASA POWER, CSV, fixture, and cache adapters.
- `src/solarclean/infrastructure/pvlib_adapter/*`: pvlib PVWatts implementation.
- `src/solarclean/infrastructure/persistence/*`: output writers and diagnostic plot generation.
- `src/solarclean/cli/*`: Typer command surface.
- `src/solarclean/config/*`: YAML loading and validated config models.
- `configs/*.yaml`: Riyadh NASA, offline fixture, and local CSV examples.
- `data/fixtures/*`: deterministic weather and regression input data.
- `data/local_weather/*`: documented local CSV import example.
- `docs/*`: architecture, data contracts, assumptions, and ADRs.
- `tests/unit`, `tests/integration`, `tests/regression`: acceptance-focused tests.

## Test Strategy

- Write behavior tests before production code for weather validation, PV scaling, soiling, reproducibility, cohort invariants, and end-to-end fixture runs.
- Keep unit tests fully offline and deterministic.
- Mark NASA POWER network tests as `integration` and skip them unless `SOLARCLEAN_RUN_NETWORK_TESTS=1`.
- Include a short deterministic regression scenario with expected annual clean and baseline values from the fixture configuration.
- Verify actual energy never exceeds clean energy and repeated seed/config/weather inputs reproduce identical outputs.
- Verify future strategies can be substituted through `ScenarioSimulationEngine`.
- Verify frozen scenario inputs and extension mappings cannot be mutated by strategy or consumer code.
- Verify unknown scenario-specific extension fields survive common result handling.

## Verification Commands

Run from the repository root:

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python -m pytest --cov=solarclean --cov-report=term-missing
python -m ruff format --check .
python -m ruff check .
python -m mypy src
solarclean fetch-weather --config configs/offline_fixture.yaml
solarclean run-clean --config configs/offline_fixture.yaml
solarclean run-baseline --config configs/offline_fixture.yaml
python -m pytest tests/unit/test_scenario_contracts.py tests/regression/test_t1_baseline_compatibility.py -q
```

## Risks And Assumptions

- Default soiling, rainfall, and bird-dropping values are provisional engineering assumptions awaiting Saudi-site calibration.
- The offline fixture is deterministic test data, not representative Riyadh weather.
- Real NASA POWER retrieval depends on internet access and service availability; the adapter is implemented and tested with mocked responses plus optional live integration.
- pvlib is required for the production PVWatts model. The code fails clearly when the dependency is missing instead of silently substituting a scientific model.
- CSV output is used instead of Parquet to avoid an unnecessary dependency in Phases 1-3.
- The current workspace has an empty or partial `.git` directory and is not recognized by `git`; no commits can be created until the repository is initialized or repaired.
- T1 freezes shared contracts but does not implement the future scenario behavior that will consume them.
