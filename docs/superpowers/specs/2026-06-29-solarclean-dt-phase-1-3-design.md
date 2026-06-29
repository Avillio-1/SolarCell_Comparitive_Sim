# SolarClean-DT Phase 1-3 Design

## Context

The workspace started as an empty scaffold with no project brief. The active 2026-06-29 prompt is the source of truth. The design below implements only the reusable foundation and Phases 1-3: weather ingestion, clean PV production, no-intervention baseline soiling, and cohort farm representation.

## Recommended Approach

Use a modular monolith with clean domain contracts and infrastructure adapters. This keeps scientific calculations testable offline while allowing NASA POWER, CSV weather, pvlib, CLI, output writing, and plotting to be replaced independently. A smaller script-based approach would be faster initially but would violate the required dependency boundaries and make Phases 4+ harder to add safely.

## Architecture

The CLI loads typed YAML configuration and calls application use cases. Use cases resolve weather providers, PV models, soiling models, farm representations, and output writers. Domain code owns the weather contract, clean energy profile, contamination state transitions, farm state, and simulation loops. Infrastructure code owns NASA POWER HTTP/caching, CSV parsing, fixture loading, pvlib PVWatts integration, output persistence, and diagnostic plotting.

## Data Flow

1. Configuration is loaded and validated.
2. The selected weather provider returns a canonical hourly `WeatherDataset`.
3. The PV model calculates clean hourly and daily energy from canonical weather.
4. The baseline engine applies daily soiling and rainfall cleaning to hourly clean energy.
5. The farm representation scales representative or cohort states to exactly 10,000 panels.
6. Outputs are written to a unique run directory with resolved config, metadata, weather, energy tables, events, summaries, and an optional diagnostic plot.

## Error Handling

Invalid configuration fails early. Weather providers validate duplicate timestamps, missing columns, timezones, numeric ranges, and unit mappings. NASA POWER errors, timeouts, rate limits, malformed responses, and missing variables raise explicit exceptions. Domain invariants reject energy increases from contamination and invalid cohort panel totals.

## Testing

Tests are offline by default. They cover weather validation, timezone conversion, CSV mapping, NASA mocked errors and caching, PV night/non-negative/scaling/daily aggregation, soiling transitions and reproducibility, cohort invariants and representative equivalence, and end-to-end offline fixture output generation. Live NASA tests are integration-marked and skipped unless explicitly enabled.

## Scope Boundaries

Do not implement drone inspection, CV inference, manual cleaning dispatch, coatings, economics, optimization, sensitivity sweeps, databases, dashboards, Docker, authentication, or microservices.
