# T2 Reactive CV Scenario Data Contract

The reactive scenario is a T1 `MitigationStrategy` named `reactive_cv` (or
`reactive_cv_perfect_information` for the zero-CV-error benchmark instance).
It runs through `ScenarioSimulationEngine` and writes scenario-specific
values through `DailyScenarioResult.extensions` and
`DailyScenarioResult.operational`.

## `OperationalQuantities` fields used by T2

| Field | Unit | Meaning |
| --- | --- | --- |
| `inspections_count` | cohorts/day | Cohorts actually imaged by the drone that day (after capacity and weather limits). |
| `cleaning_actions_count` | cohorts/day | Cohorts the crew actually cleaned that day (after crew daily capacity). |
| `crew_hours` | hours/day | Setup + cleaning time for all cohorts cleaned that day. |
| `drone_flight_hours` | hours/day | Flight time for all flights flown that day. |
| `water_liters` | L/day | Water used by the crew for all cleanings that day. |
| `energy_used_kwh` | kWh/day | Drone flight energy + CV compute energy for that day's images. |
| `opex_cost` / `capex_cost` | -- | Always `0.0`. T2 does not implement economics; T4 owns cost valuation. |

`coated_panel_count` is unused by T2 (always `0`; it belongs to T3).

## `extensions` keys

Persisted CSV columns use the generic `extension_` prefix from
`OutputWriter.write_scenario_result()`.

| Key | Unit | Meaning |
| --- | --- | --- |
| `average_dust_soiling_ratio` | fraction | Panel-count weighted true dust ratio after that day's cleaning. |
| `queue_length` | cohorts | Cleaning queue size remaining after that day's dispatch/crew pass. |
| `weather_cancelled_flight` | bool | Whether wind or precipitation cancelled all drone flights that day. |
| `flights_flown` | count | Number of drone flights flown that day (0 if cancelled or nothing due). |
| `inspection_true_positive_count` | count | Inspected cohorts that were truly dirty and were detected as dirty. |
| `inspection_false_positive_count` | count | Inspected cohorts that were truly clean but were detected as dirty. |
| `inspection_false_negative_count` | count | Inspected cohorts that were truly dirty but were not detected. |
| `inspection_true_negative_count` | count | Inspected cohorts that were truly clean and were correctly not detected. |
| `inspection_missed_image_count` | count | Inspections where no usable image was captured at all. |
| `event_tape_checksum` | SHA-256 string | Shared exogenous event tape checksum, for cross-scenario fairness verification. |

The confusion-matrix counters (`inspection_*_count`) are recorded **only**
for offline evaluation via `solarclean.domain.reactive_cv.metrics
.summarize_detection_performance()`, which aggregates them into realized
precision/recall/F1 across the run. They are not read by
`ThresholdDispatchPolicy`; dispatch only ever sees `DispatchSignal` values,
which structurally cannot carry the ground-truth label used to compute these
counters (see ADR-011).

## Events

`DomainEvent`s are recorded per cohort with `scenario_name="reactive_cv"` (or
the perfect-information benchmark's name):

- `reactive_inspection` -- one per cohort actually imaged that day.
- `reactive_cleaning_action` -- one per cohort actually cleaned that day.

True-state events (`dust_accumulation`, `heavy_dust_event`,
`full_rain_cleaning`, `partial_rain_cleaning`, `bird_dropping_event`) are the
same event types `BaselineStrategy` and `CoatingStrategy` emit, since all
three consume the same soiling model and farm representation.

## Comparison summary (`RunReactiveSimulation`)

`_reactive_summary()` in `application/use_cases.py` reports annual/period
energy versus baseline, operational totals, `detection_performance` (from
`metrics.py`), and -- when `reactive_cv.perfect_information_benchmark` is
enabled -- `cv_error_energy_cost_kwh`, computed as the perfect-information
benchmark's annual actual energy minus the primary run's annual actual
energy. This isolates the energy cost attributable to CV error specifically
(recall, false positives, missed images) from the cost of the
scheduling/capacity/crew constraints, which are identical between the two
runs.

`cost_basis_available` is always `false` and `economics_owner` is `"T4"`:
T2 intentionally reports no monetary values.
