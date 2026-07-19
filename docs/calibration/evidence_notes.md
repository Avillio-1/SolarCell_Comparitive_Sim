# Calibration Evidence Notes

## Evidence Grading

- `quoted` means a value is copied or directly bounded from a named source, such as a manufacturer specification or public tariff page.
- `measured` is reserved for direct measured data from the target or a documented comparable site. No registry entry currently uses it.
- `literature` means the value and its bounds are taken from a named published study or standard reference (used by the PVWatts loss-chain parameters).
- `calculated` means a value is mathematically derived from another registry value.
- `inferred` means literature supports the direction or order of magnitude, but the value is adapted to the SolarClean model.
- `assumed` means no reliable source was found and the value is intentionally a sensitivity placeholder.

## Literature-v3 Refresh (2026-07-18)

The 2026-07-18 pass replaced generic "provisional preset" sources with named, verifiable
publications wherever they exist, without changing any central runtime value:

- Dry soiling rate, soiling floor, seasonal multipliers, dust-event probability, and rain
  thresholds are now anchored to measured near-Riyadh (Rumah) campaigns, a measured Dhahran
  long-exposure endpoint, Saudi dust-storm climatology, and the multi-site Bessa et al. 2021
  threshold survey; their confidence rose from low to medium where the published envelope
  brackets the central value.
- The high bound of the dry soiling rate widened (0.0022 -> 0.006/day) to cover the worst
  measured technology at Rumah (18%/30 days), and the tariff low bound widened
  (0.18 -> 0.04 SAR/kWh) to cover Saudi PPA-priced energy. Sensitivity and Monte Carlo studies
  therefore now explore the full published envelope.
- CV detector recall/false-positive centrals are unchanged but are now explicitly framed as
  field-deratings of named curated-benchmark results (95-100% recall in publications).
- Coating dust-adhesion reduction, useful life, and optical penalty are anchored to the
  Materials 2022 desert anti-soiling coating review; coating capex stays provisional because
  that review publishes no per-m2 cost data.
- Bird-dropping parameters, stochastic daily variation, and operational placeholders
  (crew throughput, flight-hour costs, overhead) remain `assumed`: no reliable published
  source was found, and pretending otherwise would degrade the registry's honesty.

## Current Production Config

The current strict model accepts the following calibrated sections:

- `soiling`
- `rainfall_cleaning`
- `bird_droppings`
- `farm`

The low, central, and high overlays are internally consistent and should validate against
`configs/default.yaml`. They do not introduce future-owner sections.

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
