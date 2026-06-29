# ADR-006: NASA UTC To Riyadh Time

## Status

Accepted.

## Decision

Request NASA POWER hourly data with `time-standard=UTC` and convert normalized timestamps to the configured target timezone, defaulting to `Asia/Riyadh`.

## Rationale

UTC requests avoid ambiguity at the source. Simulation outputs and daily aggregation need Riyadh-local days.

## Consequences

Weather cache keys include request timestamps and target timezone. Daily PV and contamination outputs use the site calendar.
