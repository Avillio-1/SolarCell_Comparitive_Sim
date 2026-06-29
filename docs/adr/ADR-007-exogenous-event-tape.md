# ADR-007: Exogenous Event Tape

## Status

Accepted.

## Decision

Represent stochastic environmental and contamination inputs as one immutable, serializable `ExogenousEventTape`.

## Rationale

Future scenarios must compare interventions under the same exogenous conditions. If each scenario draws its own dust, bird, or cohort-variation events during simulation, scenario results can differ because of RNG ordering rather than intervention logic.

## Consequences

Baseline simulation can consume a pre-generated event tape. The same tape can later be reused by reactive inspection, manual cleaning, coating, or economic scenarios without changing the exogenous inputs. Future scenario-specific uncertainty is assigned its own RNG stream and is not consumed by Phase 1-3 baseline logic.

