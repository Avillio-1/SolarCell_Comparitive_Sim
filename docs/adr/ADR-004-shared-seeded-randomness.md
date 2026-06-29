# ADR-004: Shared Seeded Randomness

## Status

Accepted.

## Decision

Use `numpy.random.Generator` with explicit seeds for stochastic dust and bird-dropping events.

## Rationale

Reproducibility is required for regression tests and scenario comparison. Hidden global random state would make runs harder to audit.

## Consequences

The same seed and input weather produce identical event sequences and results. Different seeds can change stochastic events.
