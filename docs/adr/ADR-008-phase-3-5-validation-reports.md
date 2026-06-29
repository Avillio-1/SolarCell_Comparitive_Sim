# ADR-008: Phase 3.5 Validation Reports

## Status

Accepted.

## Decision

Implement Phase 3.5 validation as local CLI/report-generation use cases rather than a dashboard, API, or database.

## Rationale

The current project needs reproducible evidence for weather completeness, simulation invariants, annual performance, event-tape stability, and runtime/output size. Local JSON/CSV reports are enough and keep the architecture aligned with the Phase 1-3 modular monolith.

## Consequences

Validation commands write files under `outputs/<run_id>/`. Reports can later be consumed by notebooks or dashboards, but Phase 3.5 does not implement those interfaces.

