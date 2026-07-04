# T2 Reactive CV Scenario Assumptions

No CV model evidence, drone hardware specification, or crew operations data
was available in the workspace for this task. Every numeric default in
`ReactiveCVConfig` is a provisional, round-number placeholder chosen to be
physically plausible for a 10,000-panel Riyadh farm, not a sourced value.
All of it requires T5 calibration before any reported number is treated as
a real-world estimate.

## Detection ("dirty") threshold

A cohort is treated as ground-truth "dirty" (for both the statistical
observer's recall/false-positive draw and for offline precision/recall/F1
evaluation) when `dust_soiling_ratio < inspection.dirty_soiling_ratio_threshold`
(default `0.92`) or when it has any nonzero bird-dropping loss. This
threshold is a modeling convenience, not a measured "panel needs cleaning"
criterion; T5 should replace it with an economically or physically derived
value (e.g., the soiling level at which marginal cleaning cost is recovered
by marginal energy gain -- once T4 economics exists).

## CV observer

`recall_fraction=0.85`, `false_positive_rate=0.05`, `missed_image_fraction=0.03`,
`base_confidence=0.8` are round-number placeholders in a plausible range for
a deployed drone/CV pipeline, not derived from any measured confusion matrix.
`severity_error_std_fraction=0.15` and `confidence_std_fraction=0.1` are
similarly provisional noise scales. T5's calibration registry should replace
all five with sourced values from an actual model/test-set evaluation, per
`docs/integration/t1_parallel_development.md`.

## Drone fleet

`cohorts_per_flight=10`, `flights_per_day=4`, `flight_duration_minutes=18`,
`energy_kwh_per_flight=0.35`, and `compute_energy_kwh_per_image=0.01` are
placeholders sized for a small consumer/prosumer inspection drone, not a
specific vendor's datasheet. `max_wind_speed_m_s=12` and
`max_precipitation_mm=0.2` are conservative generic small-UAV operating
limits, not the specific fleet's certified limits.

Due inspections that are skipped because of weather cancellation or daily
drone capacity are carried in an overdue backlog and prioritized before new
scheduled cohorts on later days. This is a simple service-backlog model, not
a route optimizer or multi-day fleet dispatch planner.

## Cleaning crew

`daily_capacity_cohorts=6`, `setup_minutes_per_cohort=8`,
`cleaning_minutes_per_cohort=25`, `water_liters_per_cohort=180`,
`dust_removal_efficiency=0.92`, and `bird_removal_efficiency=0.95` are
placeholders for a small manual/semi-automated cleaning crew, not measured
crew performance data. Water use per cohort in particular should be
replaced with a real waterless/low-water cleaning technique assumption once
one is selected, since 180 L/cohort/cleaning implies non-trivial water
logistics at farm scale.

## Dispatch

`estimated_loss_threshold_fraction=0.05` and `confidence_threshold=0.5` are
round-number thresholds, not derived from an economic break-even analysis
(which requires T4). `max_queue_age_days=14` is an arbitrary cap intended to
prevent an unbounded queue during a long weather-cancellation streak, not a
modeled service-level agreement.

Dispatch receives only bounded `DispatchSignal` values: estimated loss and
confidence are clipped to `[0, 1]` before thresholding. Ground-truth
contamination is used only by the observer to generate imperfect observations
and by reporting code to compute offline metrics such as false-positive
cleaning and missed contamination.

## What is *not* assumed

- No monetary values (labor cost, water cost, drone amortization, energy
  tariff) are assumed anywhere in T2. `OperationalQuantities.opex_cost` and
  `capex_cost` are always `0.0`; T4 owns valuation.
- The scenario does not assume the dispatch policy has access to anything
  beyond `DispatchSignal` (see ADR-011) -- this is enforced by the type
  system, not just documented as an assumption.
- The scenario does not assume CV/drone/dispatch configuration can be
  changed without affecting comparability with baseline: day-1 true-state
  events are asserted identical across configurations in
  `tests/unit/test_reactive_strategy.py`.

## Open issues for later review

- All CV observer, drone, and crew parameters above need T5 evidence.
- The dirty-cohort threshold needs an economic or physical derivation once
  T4 exists.
- `docs/adr/ADR-011-t2-reactive-cv-scenario.md` flags a pre-existing,
  core-owned date-labeling issue in `BaselineStrategy`'s carried-over
  `FarmState`, found while testing T2's rng isolation; it does not affect
  T2's own output but should be fixed by the T1/core owner.
