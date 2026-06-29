# ADR-003: Hourly PV And Daily Contamination

## Status

Accepted.

## Decision

Calculate clean PV production hourly and update contamination state daily.

## Rationale

PV output responds strongly to hourly irradiance, temperature, and wind. Dust/rainfall cleaning assumptions are less certain and are easier to inspect as daily state transitions.

## Consequences

The daily soiling ratio is applied to that day's hourly clean production before daily aggregation. The daily loop avoids look-ahead bias.
