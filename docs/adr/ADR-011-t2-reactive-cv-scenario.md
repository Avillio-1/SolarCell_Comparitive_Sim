# ADR-011: T2 Reactive CV Drone/Crew Scenario Uses an Isolated CV RNG Stream

## Status

Accepted.

## Context

Scenario 2 needs periodic drone inspection, an imperfect computer-vision
observer, capacity-limited human cleaning, and a perfect-information
benchmark for isolating the cost of CV error -- while keeping true
contamination/bird state identical to `BaselineStrategy` for fair
comparison, and while guaranteeing the dispatch policy cannot use ground
truth and that CV/drone/dispatch configuration can never perturb the
exogenous dust/bird simulation.

## Decision

Implement the reactive scenario as `ReactiveCVStrategy`, a T1
`MitigationStrategy`. True per-cohort state reuses
`solarclean.domain.farm.representation.CohortState`/`CohortFarm` and
`KimberStyleSoilingModel`. The strategy draws and records the shared daily
dust/rain drivers once per day, then applies those drivers to each cohort's
own prior dust state so targeted crew cleaning remains local to the cleaned
cohort on later days. The strategy consumes the same immutable event tape and
the same per-day `rng` argument in the same call order for shared daily
drivers, so day-1 true dust/bird outcomes are unaffected by any reactive-only
configuration.

All CV/drone/dispatch stochasticity draws from a second, independent
generator (`cv_rng`), spawned once from `rng` inside `initial_state()` via
`numpy.random.Generator.spawn()`. `spawn()` derives a new `SeedSequence`
without consuming from the parent generator's bit stream, so `cv_rng`
existing and being used arbitrarily can never shift the sequence of draws
`rng` produces for the shared soiling/farm model.

The dispatch policy (`ThresholdDispatchPolicy.select_for_cleaning`) accepts
only `DispatchSignal` values -- a dataclass with `cohort_id`,
`estimated_loss_fraction`, and `confidence`, and no ground-truth field.
`CVObservation` (which does carry a `_ground_truth_dirty` label, used only
for offline precision/recall/F1 evaluation) is converted to `DispatchSignal`
via `to_dispatch_signal()` before dispatch ever sees it. This makes the
"dispatch cannot see true state" requirement a type-level guarantee rather
than a convention. Estimated loss and confidence are bounded to `[0, 1]`
before dispatch thresholds are evaluated.

Inspections skipped because of weather cancellation or drone daily capacity
are kept in an overdue inspection backlog. Backlogged cohorts are prepended
to the next day's scheduled inspection list before capacity is applied.

`PerfectInformationObserver` implements the same `CVObserver` protocol as
`StatisticalCVObserver` with zero detection error, so the benchmark run
reuses the identical scheduler/drone/dispatch/crew pipeline and differs from
the primary run only in observer behavior -- isolating the energy cost of CV
error as `perfect_info.annual_actual_energy_kwh -
reactive.annual_actual_energy_kwh`.

## Consequences

The shared `ScenarioSimulationEngine` remains the only annual loop. Baseline
and reactive scenarios share the same exogenous event tape and produce
identical day-1 true-state events regardless of CV configuration (see
`tests/unit/test_reactive_strategy.py::test_changing_cv_randomness_does_not_change_true_dust_or_bird_events`
and the direct mechanism test
`test_cv_rng_spawn_does_not_perturb_the_shared_rng_draw_sequence`). From day 2
onward, true state legitimately diverges between configurations because
cleaning actions taken on prior days feed back into future soiling -- that
feedback is the scenario's point, not a leak.

T2 does not implement economics or dashboard behavior. `OperationalQuantities`
reports physical/operational quantities only (inspections, cleaning actions,
crew hours, drone flight hours, water, and drone/compute energy);
`opex_cost`/`capex_cost` remain 0.0, owned by T4.

## Known issue found in existing T1/core code (not fixed here)

While writing the rng-isolation test, we found that `BaselineStrategy`'s
carried-over `FarmState.date` never advances past the first simulated day:
`_apply_dust_to_farm()` and `CohortFarm.advance_day()` both propagate
`state.date` from the *previous* day's `FarmState` rather than the current
`day_input.date`. `DailyScenarioResult.date` is still correct (it comes
directly from `day_input.date`), but bird-dropping `DomainEvent`s attached to
`daily_results[1:]` in the baseline scenario carry day 1's date. This is
core-owned code (`src/solarclean/domain/simulation/baseline_strategy.py`),
so we are flagging it here rather than fixing it as part of T2; the reactive
strategy constructs its daily `FarmState` with `day_input.date` and does not
have this problem.
