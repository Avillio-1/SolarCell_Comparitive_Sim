# SolarClean-DT T1 Contract Freeze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze shared scenario contracts so baseline, reactive CV, coating, economics, analytics, and dashboard work can proceed in parallel.

**Architecture:** Add a small domain-level scenario contract package and one shared simulation engine. Preserve the existing baseline API by adapting it to the new generic engine rather than rewriting Phase 1-3.5 behavior.

**Tech Stack:** Python 3.11+, dataclasses, Protocol, pandas, NumPy Generator, Pydantic configuration models, pytest, Ruff, mypy.

---

### Task 1: Contract Tests First

**Files:**
- Create: `tests/unit/test_scenario_contracts.py`
- Create: `tests/regression/test_t1_baseline_compatibility.py`

- [ ] **Step 1: Add a mock strategy substitution test**

Create a test that imports wished-for APIs from `solarclean.domain.scenario.contracts` and `solarclean.domain.simulation.scenario_engine`, builds fixture weather and clean PV, runs a `MockFutureStrategy`, and asserts the annual result has common totals plus preserved extensions.

- [ ] **Step 2: Add immutable shared-input tests**

Create tests asserting `ScenarioContext.metadata`, `DailyScenarioResult.extensions`, `AnnualScenarioResult.extensions`, `DomainEvent.metadata`, and `DailyEventInputs` mappings reject assignment or item mutation.

- [ ] **Step 3: Add baseline compatibility regression**

Run existing `BaselineSimulationEngine` on `configs/offline_fixture.yaml` inputs and assert fixture values from `data/fixtures/regression_expected_offline_summary.json` remain unchanged.

- [ ] **Step 4: Verify RED**

Run:

```powershell
python -m pytest tests/unit/test_scenario_contracts.py tests/regression/test_t1_baseline_compatibility.py -q
```

Expected before implementation: fail during import because scenario contracts do not exist yet.

### Task 2: Scenario Contract Models

**Files:**
- Create: `src/solarclean/domain/scenario/__init__.py`
- Create: `src/solarclean/domain/scenario/contracts.py`

- [ ] **Step 1: Implement immutable dataclasses**

Add `ScenarioContext`, `DailyScenarioInput`, `OperationalQuantities`, `DomainEvent`, `DailyScenarioResult`, `AnnualScenarioResult`, `StrategyStep`, `MitigationStrategy`, `ScenarioComparisonInput`, and `ScenarioOutputBundle`.

- [ ] **Step 2: Add JSON/frame helpers**

Implement `DailyScenarioResult.to_record()`, `DomainEvent.to_record()`, `AnnualScenarioResult.to_daily_frame()`, and `AnnualScenarioResult.summary()`.

- [ ] **Step 3: Verify GREEN for contract model tests**

Run:

```powershell
python -m pytest tests/unit/test_scenario_contracts.py -q
```

Expected after Task 2 and before Task 3: contract model tests pass, engine-related tests still fail until the engine exists.

### Task 3: Shared Scenario Engine And Baseline Adapter

**Files:**
- Create: `src/solarclean/domain/simulation/scenario_engine.py`
- Create: `src/solarclean/domain/simulation/baseline_strategy.py`
- Modify: `src/solarclean/domain/simulation/baseline.py`

- [ ] **Step 1: Implement `ScenarioSimulationEngine`**

The engine iterates `clean.daily` once, builds `DailyScenarioInput`, delegates day behavior to the supplied strategy, clamps common energy invariants, and returns `AnnualScenarioResult`.

- [ ] **Step 2: Implement `BaselineStrategy`**

Move baseline day-level logic behind `MitigationStrategy` while reusing `KimberStyleSoilingModel`, `CohortFarm`, `_daily_environment`, and `_apply_dust_to_farm`.

- [ ] **Step 3: Preserve `BaselineSimulationEngine.run()`**

Keep the public API and return type unchanged. Internally build a `ScenarioContext`, run `BaselineStrategy` through `ScenarioSimulationEngine`, then convert the generic annual result into the legacy `BaselineSimulationResult`.

- [ ] **Step 4: Verify baseline compatibility**

Run:

```powershell
python -m pytest tests/regression/test_t1_baseline_compatibility.py tests/unit/test_soiling.py tests/unit/test_event_tape.py -q
```

Expected: all pass with unchanged fixture totals and event records.

### Task 4: Generic Persistence Contract

**Files:**
- Modify: `src/solarclean/infrastructure/persistence/outputs.py`
- Test: `tests/unit/test_scenario_contracts.py`

- [ ] **Step 1: Add `OutputWriter.write_scenario_result()`**

Write `scenario_daily_results.csv`, `scenario_events.csv`, and `scenario_summary.json` from `AnnualScenarioResult` or `ScenarioOutputBundle`. Preserve extension columns by prefixing daily extension keys with `extension_`.

- [ ] **Step 2: Add test coverage**

Assert a mock result with an unknown extension writes common fields and extension fields without failing common handling.

### Task 5: Documentation And ADR

**Files:**
- Create: `docs/data_contracts/scenario_contracts.md`
- Create: `docs/architecture/t1_shared_interfaces.md`
- Create: `docs/integration/t1_parallel_development.md`
- Create: `docs/adr/ADR-009-t1-shared-contract-freeze.md`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `PLAN.md`
- Modify: `PROGRESS.md`

- [ ] **Step 1: Document field names, types, units, and ownership**

Write the scenario contract data dictionary and module ownership boundary.

- [ ] **Step 2: Add architecture diagram and integration checklist**

Include Mermaid module boundaries and T2/T3/T4 developer checklist.

- [ ] **Step 3: Add branch/module ownership guidance**

Record ownership for baseline/contracts, T2 reactive CV, T3 coating/economics, T4 analytics/dashboard.

- [ ] **Step 4: Add ADR-009**

Record the contract-freeze decision, rationale, and consequences.

### Task 6: Final Verification

**Files:**
- All modified files

- [ ] **Step 1: Run targeted tests**

```powershell
python -m pytest tests/unit/test_scenario_contracts.py tests/regression/test_t1_baseline_compatibility.py -q
```

- [ ] **Step 2: Run full quality gates**

```powershell
python -m pytest -q
python -m ruff format --check .
python -m ruff check .
python -m mypy src
```

- [ ] **Step 3: Audit for forbidden Phase 4 implementation**

Search for reactive, drone, coating, economics, sensitivity, dashboard behavior. The only allowed references are contracts/docs/placeholders for ownership and extension points.

- [ ] **Step 4: Record outcomes**

Update `PROGRESS.md` with commands, results, frozen contracts, unchanged baseline evidence, and remaining work for T2/T3/T4.
