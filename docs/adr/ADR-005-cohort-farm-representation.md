# ADR-005: Cohort Farm Representation

## Status

Accepted.

## Decision

Implement both a representative-panel farm and a configurable cohort farm. The default cohort farm has 100 cohorts with 100 panels each.

## Rationale

Phase 3 must avoid permanently limiting the simulator to one representative panel. Cohorts create a stable extension point for future targeted inspections and cleaning.

## Consequences

Energy aggregation must avoid double-counting panel count. Homogeneous cohort output is tested against representative scaling.
