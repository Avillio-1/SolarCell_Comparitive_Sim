# ADR-010: T3 Coating Scenario Uses T1 Strategy Extensions

## Status

Accepted.

## Context

Scenario 3 needs coating physics, water accounting, and cost-ready quantities
while T4 economics and T5 calibration are developed independently.

## Decision

Implement the coating scenario as `CoatingStrategy`, a T1 `MitigationStrategy`.
Store coating-specific values in `DailyScenarioResult.extensions` and generic
scenario outputs. Expose `CoatingCostBasis` as quantities only, without
annualization, tariffs, discounted cash flow, or water revenue.

## Consequences

The shared `ScenarioSimulationEngine` remains the only annual loop. Baseline and
coating can share the same exogenous event tape. T4 can consume coating outputs
without importing coating physics internals.
