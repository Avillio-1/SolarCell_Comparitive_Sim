# ADR-0004: Deterministic event tape

## Status

Accepted.

## Context

Independent stochastic draws would expose scenarios to different dust, bird, or cohort events and
confound the comparison.

## Decision

Generate one immutable exogenous event tape from deterministic `SeedSequence` streams. Every
scenario consumes the same tape. Scenario-local randomness may affect interventions but cannot
regenerate or mutate exogenous events.

## Consequences

Runs are reproducible and scenario order does not change environmental inputs. New exogenous
processes require a versioned tape extension and compatibility tests.
