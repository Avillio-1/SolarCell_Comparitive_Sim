# ADR-002: Weather Provider Abstraction

## Status

Accepted.

## Decision

Use a provider-independent `WeatherProvider` protocol returning a canonical `WeatherDataset`.

## Rationale

NASA POWER is useful for bootstrap simulations, but future measured Riyadh station data must be able to replace it without changing PV or simulation logic.

## Consequences

NASA field names, HTTP behavior, and cache details are isolated in the NASA adapter. CSV and fixture providers share the same domain contract.
