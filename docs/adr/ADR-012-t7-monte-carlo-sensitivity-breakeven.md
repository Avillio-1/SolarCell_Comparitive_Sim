# ADR-012: T7 Monte Carlo, Sensitivity, and Break-Even Reuse T6 as a Black Box

## Status

Accepted.

## Context

T6 (`CompareAllScenarios`) produces a single, deterministic, reconciled ranking of
baseline vs. reactive vs. coating for one set of point-estimate assumptions. T7 must
answer the question T6 cannot: is that ranking robust, or does it flip once the
uncertain physical, operational, and financial assumptions documented in the T5
parameter registry vary?

Three constraints shaped the design:

1. **Fairness must not regress.** Every trial and every swept variant must keep the
   same per-scenario fairness guarantees T6 already enforces (shared weather and event
   tape, no scenario-specific input drift). The cheapest way to guarantee this is to
   never reimplement the comparison -- reuse `CompareAllScenarios` unchanged.
2. **Ranges come from T5, not from T7.** The plan requires that sensitivity and
   break-even ranges are drawn from the shared registry, never invented in the
   experiment runner.
3. **The registry's `configuration_path` strings are not all resolvable.** Several T5
   parameters document paths that are interface placeholders
   (`calibration.central_v2_targets.*`, `reactive_cv.operations.*`,
   `reactive_cv.cleaning.*`), composite expressions (two coating cost fields summed),
   economics names consumed by `build_economics_from_parameter_registry` rather than by
   `SolarCleanConfig`, or a stale namespace (`coating.performance.*` where the real
   section is `coating.physics`). A blind path-walk over `configuration_path` would
   silently misapply or crash on these.

## Decision

Implement T7 as three application use cases -- `MonteCarloExperiment`,
`OneWaySensitivityExperiment` / `TwoWaySensitivityExperiment`, and
`BreakEvenExperiment` -- that each call `CompareAllScenarios` as a black box.

`CompareAllScenarios` gains two backward-compatible options: `write_artifacts=False`
(skip the CSV/PNG/JSON package and the empty run directory, since T7 calls it hundreds
of times) and `parameter_registry=...` (inject an in-memory registry so an economics
parameter can be perturbed without writing a temp YAML per trial). Default behavior is
unchanged; all pre-existing T6 tests pass untouched.

Parameter perturbation goes through a hand-verified catalog,
`domain/calibration/parameter_overrides.py`, that maps each supported registry
parameter to exactly one real, validated `SolarCleanConfig` field (or economics
registry name) and **explicitly lists every registry parameter it excludes, with the
reason**. Ranges (low/central/high) are always read live from the registry so
calibration updates flow through automatically; only the name-to-field mapping is fixed
in code. Config overrides are applied with pydantic `model_copy`, preserving
immutability of the base config and re-running every cross-field validator (e.g. the
coating `useful_life_years` deployment/costs sync).

Monte Carlo reproducibility uses the single point-of-entropy the rest of the codebase
already uses -- `config.soiling.random_seed`, which seeds both the event tape and the
scenario engine. Trial seeds are generated deterministically from one `base_seed` via
`random.Random`, so a fixed experiment configuration reproduces identical results.

## Consequences

- T7 inherits T6's fairness and reconciliation guarantees for free; a broken fairness
  check surfaces as an unreconciled trial rather than a silently unfair comparison.
- The override catalog is the single place to audit which uncertainties T7 can and
  cannot currently sweep. 35 of 53 registry parameters are directly sweepable today;
  the remaining 18 are blocked on unimplemented config interfaces and are reported as
  such rather than skipped silently.
- Two-way winner maps and larger Monte Carlo counts remain the expensive operations.
  Per the plan's risk note, grid resolution and trial counts are explicit caller inputs
  (never auto-selected), and performance work is deferred until profiling justifies it.
