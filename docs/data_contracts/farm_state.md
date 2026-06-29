# Farm State Data Contract

`FarmState` represents a dated collection of cohort states.

## Cohort State

Each `CohortState` contains:

- `cohort_id`
- `panel_count`
- `dust_soiling_ratio`
- `bird_drop_coverage_fraction`
- `bird_drop_loss_fraction`
- `days_since_effective_rain`
- `days_since_manual_cleaning`
- optional `zone_id`
- optional metadata

## Invariants

- Sum of cohort panel counts equals the configured fleet size.
- Default cohort farm has 100 cohorts and 100 panels per cohort.
- Dust ratios remain between 0 and 1.
- Bird-dropping coverage and loss fractions remain between 0 and 1.
- Aggregate actual energy cannot exceed aggregate clean energy.
- With homogeneous cohort state, cohort aggregation equals representative-panel scaling within numeric tolerance.

## Extension Points

Future phases can target cohorts by `cohort_id` for inspection, crew cleaning, coating state, and zone-specific behavior. Those controllers are not implemented in Phases 1-3.
