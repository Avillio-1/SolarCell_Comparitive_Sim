# SolarClean-DT Phase 3.5 Design

## Context

Phase 1-3 is implemented as a clean Python modular monolith. Phase 3.5 must harden the foundation before scenario expansion by validating full-year NASA weather and simulations, making stochastic inputs scenario-independent, adding calibration presets, and adding reproducible reporting and performance evidence.

## Approach

Use an additive validation/reporting layer around the existing architecture. Keep domain-level event tape and RNG stream models pure and serializable. Keep NASA validation, report writing, profiling, and CLI orchestration in application/infrastructure layers. Do not introduce Phase 4 scenario behavior.

## Components

- `domain/random`: deterministic RNG stream names and seed spawning.
- `domain/events`: immutable serializable exogenous event tape for dust accumulation variation, heavy dust events, bird events, and cohort variation.
- `domain/calibration`: low/medium/high Riyadh soiling presets clearly marked as provisional.
- `domain/validation`: weather, energy, baseline, and farm invariant report dataclasses.
- `application`: Phase 3.5 validation use cases for full-year weather, clean PV, baseline, farm equivalence, and profiling.
- `infrastructure/persistence`: JSON/CSV report writers.
- `cli`: `validate-weather`, `validate-phase-3-5`, and `profile-full-year` commands.

## Data Flow

1. Load config.
2. Load or fetch NASA POWER 2025 hourly weather without interpolation.
3. Validate timestamps, gaps, duplicates, canonical units, ranges, timezone, metadata, and checksum.
4. Generate one immutable exogenous event tape from deterministic streams.
5. Run clean PV and no-intervention baseline using the event tape.
6. Compare homogeneous representative and cohort farm results.
7. Write reports for weather, energy, events, invariants, performance, and summaries.

## Testing

Add tests for event-tape immutability, serialization, deterministic stream independence, scenario RNG non-interference, calibration preset ordering, weather validation reports, farm equivalence reports, multi-week golden regression, and CLI/report file creation. Keep unit tests offline and deterministic; live NASA remains opt-in.

## Scope Boundary

Phase 3.5 creates data and extension points for future scenarios but does not implement inspections, cleaning dispatch, coating behavior, economics, optimization, APIs, dashboards, or sensitivity sweeps.

