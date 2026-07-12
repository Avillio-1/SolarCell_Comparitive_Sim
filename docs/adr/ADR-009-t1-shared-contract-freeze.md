# ADR-009: T1 Shared Contract Freeze

## Status

Accepted.

## Decision

Freeze shared scenario contracts around `ScenarioContext`, `MitigationStrategy`, `DailyScenarioResult`, `AnnualScenarioResult`, `DomainEvent`, `OperationalQuantities`, `ScenarioComparisonInput`, and generic scenario persistence outputs.

The shared `ScenarioSimulationEngine` owns the annual daily loop. Scenario strategies own only initial state and per-day behavior. Existing baseline behavior is preserved by adapting it through `BaselineStrategy` while keeping `BaselineSimulationEngine` as a compatibility facade.

## Rationale

Reactive CV, coating, economics, analytics, and dashboard work need stable interfaces before parallel development starts. A generic strategy contract prevents duplicated annual loops and prevents scenario-name conditionals from accumulating in simulation code.

## Consequences

Future strategies can run under the same weather, clean PV, farm, and exogenous event inputs. Common result handling can compare annual energy and operational quantities while preserving scenario-specific extension fields. Changes to these contracts now require contract-test and ADR updates.

## Adversarial Hardening Amendment (2026-07-12)

The frozen boundary is recursively immutable for structured metadata, not only at
the outer mapping. Each engine run also receives an isolated copy of the mutable
Pydantic farm configuration. This prevents one strategy or run from changing the
weather provenance, clean-energy provenance, run metadata, or farm structure seen
by another run.

The engine now fails fast unless each strategy result echoes the current input
date, strategy name, and shared daily clean-energy reference. Daily clean and
actual energy must be finite. `OperationalQuantities` count fields must be
non-negative integers, and continuous quantity/cost fields must be finite and
non-negative. These checks make violations explicit before they can poison annual
summaries or economic reconciliation.

## Non-Goals

This decision does not implement reactive CV logic, drone operations, manual cleaning, coating physics, economics, sensitivity analysis, APIs, or dashboard behavior.
