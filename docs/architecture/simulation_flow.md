# Simulation Flow

## Phase 1: Clean PV

1. Load and validate YAML configuration.
2. Resolve the configured weather provider.
3. Load canonical hourly weather.
4. Run the pvlib PVWatts adapter.
5. Save normalized weather, hourly clean energy, daily clean energy, metadata, and summary.

## Phase 2: Baseline Soiling

The baseline uses daily contamination state and hourly clean PV production.

Daily sequence:

1. Read the day's precipitation and humidity.
2. Apply daily dust accumulation and stochastic heavy dust events.
3. Apply rainfall natural-cleaning effect.
4. Determine the daily dust soiling ratio.
5. Apply contamination to the day's clean energy.
6. Aggregate actual daily energy.
7. Record state and events.

This order avoids look-ahead bias because only the current day's environment is used.

## Phase 3: Cohort Farm

When `farm.representation: cohort`, the baseline engine initializes the configured cohort fleet, applies the shared environmental dust ratio to all cohorts, optionally adds cohort variation, advances sparse bird-dropping state, computes cohort energy from per-panel clean energy, and aggregates farm energy exactly once.
