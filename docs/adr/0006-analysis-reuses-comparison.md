# ADR-0006: Robustness analysis reuses comparison

## Status

Accepted.

## Context

Monte Carlo, sensitivity, and break-even studies repeat the three-scenario decision under changed
seeds or parameters. Reimplementing comparison logic would risk different fairness or economics.

## Decision

Treat `CompareAllScenarios` as the black box for robustness studies. Apply parameter changes through
a reviewed override catalog and take ranges from the calibration registry. Permit artifact-free
inner runs for performance while preserving reconciliation.

## Consequences

Robustness results inherit the same checks and ranking logic. Unsupported parameter paths are
reported instead of guessed, and large studies remain computationally expensive.
