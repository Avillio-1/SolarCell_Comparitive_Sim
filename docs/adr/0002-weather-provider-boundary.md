# ADR-0002: Weather provider boundary

## Status

Accepted.

## Context

Studies may use NASA POWER, measured station data, or deterministic fixtures. Provider-specific
fields and time conventions must not leak into simulation rules.

## Decision

All providers implement `WeatherProvider` and return the same timezone-aware hourly
`WeatherDataset`. NASA responses are normalized from UTC, CSV columns and units are mapped
explicitly, and fixtures carry `test_only` metadata.

## Consequences

Changing providers does not change domain or PV code. Each adapter must enforce coverage, units,
and provenance before returning data.
