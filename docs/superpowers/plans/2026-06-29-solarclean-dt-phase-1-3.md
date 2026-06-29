# SolarClean-DT Phase 1-3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested, documented Python foundation for SolarClean-DT Phases 1-3.

**Architecture:** A modular monolith separates pure domain simulation from application orchestration and infrastructure adapters. Weather and PV dependencies are injected through protocols, with NASA POWER and pvlib isolated behind adapters.

**Tech Stack:** Python 3.11+, numpy, pandas, pvlib, pydantic, PyYAML, httpx, matplotlib, typer, pytest, pytest-cov, ruff, and mypy.

---

### Task 1: Foundation And Configuration

**Files:**
- Create: `pyproject.toml`
- Create: `src/solarclean/config/models.py`
- Create: `src/solarclean/config/loader.py`
- Create: `configs/riyadh_2025.yaml`
- Create: `configs/offline_fixture.yaml`
- Create: `configs/local_riyadh_csv_example.yaml`
- Test: `tests/unit/test_config.py`

- [ ] Write config validation tests for default Riyadh settings, invalid cohort totals, invalid weather provider names, and invalid date ranges.
- [ ] Run the config tests and confirm they fail because config code is missing.
- [ ] Implement typed configuration models and YAML loading.
- [ ] Run config tests until they pass.

### Task 2: Weather Contracts And Providers

**Files:**
- Create: `src/solarclean/domain/environment/weather.py`
- Create: `src/solarclean/infrastructure/weather/fixture.py`
- Create: `src/solarclean/infrastructure/weather/csv_provider.py`
- Create: `src/solarclean/infrastructure/weather/nasa_power.py`
- Create: `src/solarclean/infrastructure/weather/cache.py`
- Test: `tests/unit/test_weather.py`

- [ ] Write tests for canonical schema validation, timezone handling, duplicate timestamps, CSV mapping, cache round trip, and mocked NASA malformed responses.
- [ ] Run weather tests and confirm they fail because weather code is missing.
- [ ] Implement provider contracts, fixture provider, CSV provider, cache helpers, and NASA POWER adapter.
- [ ] Run weather tests until they pass.

### Task 3: Clean PV Phase 1

**Files:**
- Create: `src/solarclean/domain/pv/model.py`
- Create: `src/solarclean/infrastructure/pvlib_adapter/pvwatts.py`
- Create: `src/solarclean/application/use_cases.py`
- Test: `tests/unit/test_pv.py`

- [ ] Write tests for night power, non-negative power, positive fixture annual energy, single scaling to 10,000 panels, and Riyadh daily aggregation.
- [ ] Run PV tests and confirm they fail because PV code is missing.
- [ ] Implement clean energy contracts, PVWatts adapter, and clean simulation use case.
- [ ] Run PV tests until they pass.

### Task 4: Baseline Phase 2

**Files:**
- Create: `src/solarclean/domain/contamination/soiling.py`
- Create: `src/solarclean/domain/simulation/baseline.py`
- Test: `tests/unit/test_soiling.py`

- [ ] Write tests for zero accumulation, dry-day soiling, partial rain, strong rain, physical bounds, and actual energy never exceeding clean energy.
- [ ] Run soiling tests and confirm they fail because contamination code is missing.
- [ ] Implement contamination states, events, empirical soiling model, and baseline engine.
- [ ] Run soiling tests until they pass.

### Task 5: Cohort Phase 3

**Files:**
- Create: `src/solarclean/domain/farm/representation.py`
- Test: `tests/unit/test_farm.py`

- [ ] Write tests for panel-count validation, homogeneous cohort equivalence, heterogeneous explicit-sum aggregation, invalid cohort configuration, and seeded reproducibility.
- [ ] Run farm tests and confirm they fail because farm code is missing.
- [ ] Implement representative and cohort farm representations with bird-dropping state.
- [ ] Run farm tests until they pass.

### Task 6: CLI, Persistence, End-To-End, And Docs

**Files:**
- Create: `src/solarclean/infrastructure/persistence/outputs.py`
- Create: `src/solarclean/infrastructure/persistence/plots.py`
- Create: `src/solarclean/cli/main.py`
- Create: `README.md`
- Create: `docs/architecture/*.md`
- Create: `docs/data_contracts/*.md`
- Create: `docs/assumptions/*.md`
- Create: `docs/adr/*.md`
- Test: `tests/regression/test_end_to_end.py`

- [ ] Write end-to-end fixture tests for `fetch-weather`, `run-clean`, and `run-baseline` output files and finite numeric outputs.
- [ ] Run end-to-end tests and confirm they fail because CLI and persistence code is missing.
- [ ] Implement output writers, diagnostic plotting, CLI commands, docs, and regression fixture.
- [ ] Run the full required verification suite and record results in `PROGRESS.md`.
