# Agent task pack — accuracy & validation upgrades

Seven self-contained tasks. Give each file's full contents to one agent as its prompt.
Each task embeds its own context and ground rules — no shared preamble needed.

## Parallel-run rules (for the human dispatcher)

1. **One branch (ideally one git worktree) per agent.** Do not run two agents in the
   same working tree — they share `outputs/`, caches, and pytest temp dirs.
2. **Merge order matters, development order does not.** All 7 can be developed in
   parallel. Merge in this order:
   - **Task 1 first** (system losses). It is the only task allowed to change existing
     energy numbers and golden regression data. Everything numeric shifts ~−10% after it.
   - Tasks 2, 3, 4, 5, 6 in any order after that. Tasks 2/5/6 each add a CLI command to
     `src/solarclean/cli/main.py` — expect a trivial one-hunk merge conflict there.
   - **Task 7 last**, and only after the currently uncommitted dashboard work
     (`dashboard.css`, `dashboard.js`, `run_comparison.html`, `test_dashboard.py`) is
     committed or discarded. Task 7 touches those same files.
3. After merging Task 1, re-run the experiments from Tasks 2 and 5 — their infrastructure
   is unaffected but their previously produced numbers become stale.
4. Only Task 1 may update golden regression fixtures. If any other agent reports failing
   golden tests, its change is wrong — reject it.

## The tasks

| File | Deliverable | Touches core src? |
|---|---|---|
| `agent-task-1-system-losses.md` | Balance-of-system loss chain in the PV model (fixes ~10% optimistic bias) | Yes: config models, pvwatts adapter, default.yaml, registry, goldens |
| `agent-task-2-multi-year-comparison.md` | `compare-multi-year` CLI: 2019–2025 weather-year robustness | New module + CLI hunk |
| `agent-task-3-pvgis-crosscheck.md` | Independent irradiance/yield cross-check vs PVGIS TMY | No (script only) |
| `agent-task-4-soiling-benchmark.md` | Benchmark soiling model vs published pvlib Kimber/HSU models | No (script only) |
| `agent-task-5-parameter-uncertainty-monte-carlo.md` | Monte Carlo mode that samples registry parameter ranges | monte_carlo.py + CLI hunk |
| `agent-task-6-field-validation-harness.md` | Staged validation harness (MAE/RMSE/MBE/R²) with synthetic round-trip test | New module + CLI hunk |
| `agent-task-7-evidence-quality-reporting.md` | Surface parameter evidence quality in outputs & dashboard | Dashboard + summary writers |
