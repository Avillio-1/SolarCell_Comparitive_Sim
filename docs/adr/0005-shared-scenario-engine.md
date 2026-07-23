# ADR-0005: Shared scenario engine

## Status

Accepted.

## Context

Separate annual loops for baseline, reactive cleaning, and coating would duplicate timing,
aggregation, and validation logic.

## Decision

Define `MitigationStrategy` with state initialization and one-day simulation methods. Run every
strategy through `ScenarioSimulationEngine` using a copy-protected `ScenarioContext`. Store
scenario-specific fields in result extensions.

## Consequences

All scenarios share the calendar, clean reference, and daily input construction. Strategies cannot
change common contracts for local needs; consumers must tolerate unknown extension keys.
