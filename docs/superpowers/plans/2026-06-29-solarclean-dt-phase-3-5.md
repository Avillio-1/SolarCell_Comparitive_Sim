# SolarClean-DT Phase 3.5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Phase 3.5 validation, event-tape reproducibility, calibration presets, golden regression, profiling, and documentation without starting Phase 4.

**Architecture:** Preserve the Phase 1-3 clean architecture. Add pure domain models for deterministic event tapes and calibration presets; add application use cases and infrastructure report writers for validation and profiling; expose only CLI commands for local operation.

**Tech Stack:** Python 3.11+, numpy, pandas, pydantic, PyYAML, pvlib, Typer, pytest, Ruff, mypy.

---

### Task 1: Git And Planning Foundation

**Files:**
- Create: `.gitignore`
- Modify: `PROJECT_OVERVIEW.md`
- Modify: `PLAN.md`
- Modify: `PROGRESS.md`

- [ ] Initialize git on `main`.
- [ ] Add generated artifacts to `.gitignore`.
- [ ] Record Phase 3.5 checkpoints in `PLAN.md` and `PROGRESS.md`.
- [ ] Run `git status --short` to confirm tracked/untracked scope is understandable.

### Task 2: Exogenous Event Tape

**Files:**
- Create: `src/solarclean/domain/random/streams.py`
- Create: `src/solarclean/domain/events/tape.py`
- Modify: `src/solarclean/domain/contamination/soiling.py`
- Modify: `src/solarclean/domain/farm/representation.py`
- Modify: `src/solarclean/domain/simulation/baseline.py`
- Test: `tests/unit/test_event_tape.py`

- [ ] Write failing tests for immutable tape serialization, deterministic stream independence, and baseline results unaffected by future scenario RNG use.
- [ ] Implement stream spawning and event tape generation.
- [ ] Change baseline soiling/farm advancement to consume tape rows when supplied while preserving seed-based fallback behavior.
- [ ] Run event-tape and existing soiling/farm tests.

### Task 3: Validation And Reporting

**Files:**
- Create: `src/solarclean/domain/validation/reports.py`
- Create: `src/solarclean/application/phase35.py`
- Create: `src/solarclean/infrastructure/persistence/reports.py`
- Modify: `src/solarclean/cli/main.py`
- Test: `tests/unit/test_phase35_validation.py`
- Test: `tests/regression/test_phase35_reports.py`

- [ ] Write failing tests for weather timestamp/gap/unit/range/checksum reports, energy metrics, farm equivalence, and report file creation.
- [ ] Implement weather validation, clean/baseline metrics, monthly energy, specific yield, capacity factor, clipping, soiling loss, contamination/rain events, and report writers.
- [ ] Add CLI commands for `validate-weather`, `validate-phase-3-5`, and `profile-full-year`.
- [ ] Run validation/report tests.

### Task 4: Calibration Presets And Golden Regression

**Files:**
- Create: `src/solarclean/domain/calibration/registry.py`
- Create: `configs/riyadh_soiling_low.yaml`
- Create: `configs/riyadh_soiling_medium.yaml`
- Create: `configs/riyadh_soiling_high.yaml`
- Create: `data/fixtures/golden_multiweek_expected.json`
- Test: `tests/unit/test_calibration_registry.py`
- Test: `tests/regression/test_golden_multiweek.py`

- [ ] Write failing tests for low/medium/high preset ordering and clear provisional labels.
- [ ] Write a deterministic multi-week golden regression test.
- [ ] Implement registry, config presets, and golden expected fixture.
- [ ] Run calibration and regression tests.

### Task 5: Full-Year NASA Validation, Profiling, Docs, And Gates

**Files:**
- Create: `docs/architecture/phase_3_5_validation.md`
- Create: `docs/adr/ADR-007-exogenous-event-tape.md`
- Create: `docs/adr/ADR-008-phase-3-5-validation-reports.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `PLAN.md`
- Modify: `PROGRESS.md`

- [ ] Run full-year NASA weather validation.
- [ ] Run full-year clean PV and baseline validation.
- [ ] Run profiling and record runtime, memory, and output size.
- [ ] Run `python -m pytest -q`, coverage, Ruff format/check, mypy, clean install, and CLI smoke commands.
- [ ] Record all outcomes, annual results, performance, limitations, and the Phase 4 extension point in `PROGRESS.md`.
