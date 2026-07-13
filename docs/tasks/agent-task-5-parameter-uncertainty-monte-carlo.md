# Task 5: Parameter-uncertainty Monte Carlo mode

## Project context

- You are working in the repo `SolarCell_Comparitive_Sim` (Windows). It contains a Python
  3.11+ package named `solarclean` under `src/`, installed editable via pip.
- SolarClean-DT simulates a 10,000-panel PV farm in Riyadh and compares three
  dust-mitigation scenarios (baseline / reactive / coating). It has a calibration
  parameter registry (`data/calibration/parameter_registry.yaml`, 54 parameters, each
  with `low_value` / `central_value` / `high_value`) and a Monte Carlo module. Read
  `README.md` first.

## The problem you are fixing

The existing Monte Carlo (`src/solarclean/application/monte_carlo.py`, note the
module-level constant `UNCERTAINTY_MODE = "stochastic_seed_only"`) varies ONLY the
random seed: dust events, bird strikes, CV observation noise. Every uncertain
*parameter* (soiling rate, coating effectiveness, costs, tariffs…) stays pinned at its
central value in every trial. So the published Monte Carlo spread badly understates the
true uncertainty — parameter uncertainty dominates here. One-way sensitivity explores
parameters only one at a time. Your job: add a second Monte Carlo mode that jointly
samples parameters from their registry ranges (triangular distribution) in every trial,
on top of seed variation, and reports honest outcome distributions and win
probabilities.

## Before you start, read these files

1. `src/solarclean/application/monte_carlo.py` — the WHOLE file: the experiment entry
   point, how trial seeds are derived from `base_seed`, how each trial runs
   `CompareAllScenarios` with `write_artifacts=False`, how reconciliation failures are
   recorded, what the aggregated outputs/JSON/CSV contain, and how the run directory is
   written.
2. `src/solarclean/application/sensitivity.py` — module docstring and the code that
   uses `build_parameter_catalog`, `apply_config_override`, and
   `apply_economics_override` from
   `src/solarclean/domain/calibration/parameter_overrides.py`. You MUST apply parameter
   values through this same hand-verified override catalog — never by walking
   `configuration_path` strings yourself (the parameter_overrides docstring explains
   why).
3. `src/solarclean/domain/calibration/parameter_overrides.py` — `ParameterOverrideSpec`
   (what low/central/high it carries, and whether a spec is a config override or an
   economics override).
4. `src/solarclean/domain/calibration/registry.py` — how the registry is loaded.
5. `src/solarclean/cli/main.py` — find the existing monte-carlo command and its options.
6. Existing Monte Carlo tests: search `tests/` for files referencing `monte_carlo` and
   mirror their structure.

## Steps

1. In `monte_carlo.py`, introduce a mode parameter. Replace reliance on the single
   constant with an explicit argument threaded from the CLI:
   `uncertainty_mode: Literal["stochastic_seed_only", "parameters_and_seed"]`, default
   `"stochastic_seed_only"` (existing behavior must remain byte-identical for the
   default — that is your backward-compatibility contract).
2. In `parameters_and_seed` mode, per trial:
   a. Derive the trial's parameter-sampling RNG deterministically from `base_seed` and
      the trial index, SEPARATELY from the simulation seed stream (e.g.
      `random.Random(f"{base_seed}-params-{trial_index}")` — deterministic and
      independent of the existing seed derivation, which you must not change).
   b. For every spec in the override catalog (build it exactly as `sensitivity.py`
      does), sample one value with `rng.triangular(low_value, high_value, central_value)`.
      CAREFUL: Python's `random.triangular` argument order is `(low, high, mode)` — the
      mode (peak) goes LAST. If a spec has `low == high`, use the central value directly.
   c. Apply each sampled value via `apply_config_override` / `apply_economics_override`
      exactly the way `sensitivity.py` dispatches between them, all overrides applied
      together in one trial config.
   d. Run the trial like the existing mode (same seed handling, same
      `write_artifacts=False`, same reconciliation-failure handling).
   e. Record the sampled parameter values in the trial record.
3. Extend the aggregated outputs (keep every existing field; add, do not rename):
   - Per scenario: 5th, 25th, 50th, 75th, 95th percentiles of
     `net_annual_benefit_sar` and of energy gain vs baseline, plus win probability
     (fraction of valid trials in which the scenario has the highest
     `net_annual_benefit_sar`).
   - `uncertainty_mode` recorded in the metadata/JSON.
   - New CSV `monte_carlo_parameter_samples.csv`: one row per trial, one column per
     sampled parameter (registry `name`), plus the trial's per-scenario
     `net_annual_benefit_sar` and the trial winner. This enables later importance
     analysis without rerunning.
   - Do not touch the existing plots; if a new plot is not trivial, skip plots for the
     new mode entirely.
4. CLI: add an option `--uncertainty-mode` (choices: the two mode strings, default
   `stochastic_seed_only`) to the existing monte-carlo command in
   `src/solarclean/cli/main.py`. Follow the command's existing option style. Do not
   change any other option or default.
5. Tests (offline, fixture weather via `tests/config_factory.py`, small trial counts):
   - Determinism: two runs of `parameters_and_seed` with the same `base_seed` and
     trial_count=4 produce identical sampled values and identical aggregate JSON.
   - Bounds: every sampled value lies within `[low_value, high_value]` of its spec.
   - Backward compatibility: `stochastic_seed_only` results with a fixed seed are
     unchanged by your edit (if an existing test already pins this, rely on it and say
     so; otherwise add one BEFORE making changes and confirm it passes on the untouched
     code first).
   - Schema: the new CSV exists, has one row per trial and one column per catalog
     parameter; percentiles and win probabilities are present and win probabilities
     sum to ~1.0 over scenarios (allowing for ties/invalid trials per the existing
     validity handling — mirror how the current code counts valid trials).

## Constraints

- Touch ONLY the files listed below. Do not modify `sensitivity.py`,
  `parameter_overrides.py`, `comparison.py`, or the registry.
- Do not change existing golden regression data. If golden tests fail, your change is
  wrong.
- Preserve the repo's determinism discipline: same inputs → identical outputs. No use
  of global random state, `numpy.random.seed`, or time-based seeds.
- mypy runs strict on `src/`: fully annotate all new code.
- If anything in this brief contradicts what you find in the code (e.g. the entry-point
  shape differs), follow the code and note the deviation in your report; if it blocks
  the design, STOP and report.
- Do not commit or push. Do not create accounts or API keys.

## Files you may create or modify

- `src/solarclean/application/monte_carlo.py`
- `src/solarclean/cli/main.py` (one option on the existing monte-carlo command only)
- New/updated Monte Carlo test files under `tests/`

## Verification (all must pass before you finish)

```
python -m pytest -q
python -m ruff format <only the files you changed>
python -m ruff check .
python -m mypy src
```

If `import solarclean` fails, first run: `python -m pip install -e ".[dev]"`

Then do one smoke run on the real config if the weather cache allows it offline
(check `data/cache/weather` exists), with a SMALL trial count, e.g.:
`solarclean <monte-carlo command> --config configs/default.yaml --uncertainty-mode parameters_and_seed` with
trials set to ~10 via whatever option the command already exposes. Report the win
probabilities and the P5–P95 net-benefit interval per scenario from that smoke run.

## Final report

List: files changed; the exact CLI invocation for the new mode; smoke-run win
probabilities and P5/P50/P95 net benefit per scenario (state trial count); confirmation
that default-mode outputs are unchanged; test/lint/type results; anything you could not
complete.
