# Calibration Interface Requests

T5 records future configuration paths but does not implement T2, T3, or T4 behavior.

## T2 Reactive CV

Requested paths:

- `reactive_cv.detector.true_positive_rate`
- `reactive_cv.detector.false_positive_rate`
- `reactive_cv.detector.false_negative_rate`
- `reactive_cv.detector.severity_mae_fraction`
- `reactive_cv.operations.inspection_panels_per_flight_hour`
- `reactive_cv.operations.drone_flight_duration_minutes`
- `reactive_cv.operations.battery_sets_per_drone`
- `reactive_cv.cleaning.panels_per_worker_hour`
- `reactive_cv.cleaning.water_liters_per_panel`
- `reactive_cv.cleaning.labour_hours_per_action`

Expected interface: a T2-owned strict config model consumed by `ReactiveCVStrategy`, with daily
outputs recorded in `DailyScenarioResult.operational` and reactive-specific details in
`DailyScenarioResult.extensions`.

## T1/Core Baseline

Requested path:

- `bird_droppings.persistence_days_without_rain`

Expected interface: optional future baseline config if the core owner decides bird-dropping
persistence should be modeled separately from rainfall removal.

## T3 Coating And Economics

Requested paths:

- `coating.cost.capex_sar_per_m2`
- `coating.performance.dust_adhesion_reduction_fraction`
- `coating.performance.cell_temperature_reduction_c`
- `coating.performance.dew_soiling_multiplier`
- `coating.performance.annual_degradation_fraction`
- `coating.performance.optical_penalty_fraction`
- `coating.performance.water_collection_l_per_m2_day`
- `economics.tariff.sar_per_kwh`
- `economics.costs.labour_sar_per_hour`
- `economics.costs.water_sar_per_m3`
- `economics.capex.drone_equipment_sar`
- `economics.finance.discount_rate_fraction`
- `economics.finance.useful_life_years`

Expected interface: T3-owned coating and economics config models. Coating behavior should be a
`MitigationStrategy`; economics should consume `AnnualScenarioResult` rather than changing the
shared daily simulation loop.
