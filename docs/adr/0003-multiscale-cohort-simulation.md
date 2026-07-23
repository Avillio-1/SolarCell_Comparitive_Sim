# ADR-0003: Multiscale cohort simulation

## Status

Accepted.

## Context

PV production depends on hourly irradiance and temperature, while soiling, rainfall, inspection,
and cleaning decisions are naturally daily. Per-panel state for 10,000 panels is unnecessary for
current questions.

## Decision

Calculate clean PV hourly, aggregate it by site-local day, and update contamination and
interventions daily. Represent the farm as configurable cohorts with panel counts and local state.
Cleaning actions recorded during a day affect the next day's energy state.

## Consequences

The model retains weather and intervention timing without per-panel cost. It cannot resolve
sub-daily contamination or within-cohort electrical mismatch.
