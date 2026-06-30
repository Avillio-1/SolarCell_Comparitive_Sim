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

## Non-Goals

This decision does not implement reactive CV logic, drone operations, manual cleaning, coating physics, economics, sensitivity analysis, APIs, or dashboard behavior.
