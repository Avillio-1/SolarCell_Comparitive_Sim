# ADR-013: Apply Explicit Non-Soiling PV System Losses Before Inversion

## Status

Accepted.

## Context

The pvlib PVWatts path modeled irradiance, cell temperature, DC production,
inverter efficiency, and clipping, but omitted balance-of-system losses. As a
result, absolute energy and revenue outputs were systematically optimistic.

## Decision

Represent wiring, mismatch, connections, nameplate, light-induced degradation,
and availability as six explicit configurable fractions. Multiply their
complements to form one system-loss multiplier and apply it once to PVWatts DC
power before inverter efficiency and clipping. Soiling remains in the existing
contamination model; shading and snow remain excluded.

## Consequences

Default absolute energy outputs fall by about 10 percent, with clipping effects
calculated after the losses. The calibration registry now documents ranges for
the six parameters so sensitivity analysis can vary them independently.
