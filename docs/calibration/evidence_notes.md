# Calibration Evidence Notes

## Evidence Grading

- `quoted` means a value is copied or directly bounded from a named source, such as a manufacturer specification or public tariff page.
- `measured` is reserved for direct measured data from the target or a documented comparable site. No registry entry currently uses it.
- `calculated` means a value is mathematically derived from another registry value.
- `inferred` means literature supports the direction or order of magnitude, but the value is adapted to the SolarClean model.
- `assumed` means no reliable source was found and the value is intentionally a sensitivity placeholder.

## Current Production Config

The current strict model accepts the following calibrated sections:

- `soiling`
- `rainfall_cleaning`
- `bird_droppings`
- `farm`

The low, central, and high overlays are internally consistent and should validate against
`configs/riyadh_2025.yaml`. They do not introduce future-owner sections.

## Soiling And Dust

The central dry-weather soiling rate keeps the existing Phase 3.5 value. Low and high bounds are
wide because literature values vary strongly with module tilt, rainfall, local dust sources, and
cleaning history. Seasonal multipliers are spring-focused because Saudi/Gulf dust evidence supports
stronger spring dust activity, but the values are not measured Riyadh deposition rates.

Dust-event frequency and severity are event-tape inputs, not meteorological forecasts. They
represent localized heavy soiling shocks and must be calibrated against dust-event observations,
visibility/PM records, or measured power residuals.

## Rain Cleaning

The rainfall cleaning thresholds and efficiencies preserve the current empirical model structure.
The low preset makes rain easier and more effective; the high-impact preset requires more rain and
cleans less. This is a sensitivity design, not a claim that Saudi rain reliably cleans modules.

## Bird Droppings

No reliable Saudi utility-scale bird-dropping source was found. Current values are retained as
sparse cohort-level placeholders. The registry adds a blocked `persistence_days_without_rain`
target because the present model has rain removal but no explicit dry decay/persistence parameter.

## CV, Drone, Coating, And Economics

These values are intentionally blocked where their configuration paths do not yet exist. They are
included so future teams can use common names and uncertainty bounds, but the executable behavior
belongs to T2 and T3.

Conflicting or weak evidence was handled by widening bounds rather than selecting a convenient
single value. T2/T3 should narrow the bounds only after selecting hardware, detector model, coating
technology, cleaning method, and economic assumptions.

## Unit Handling

The registry records values in the units expected by SolarClean configuration paths. Currency values
are in SAR. Water cleaning is listed as liters per panel for operations and SAR per cubic meter for
economics. Coating cost is SAR per square meter because coating quotations usually scale by module
area rather than by panel count.
