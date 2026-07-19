# Calibration Open Issues

## Field Validation Status (2026-07-18)

The simulation framework passed its first real-data holdout at an arid reference site
(NREL PVDAQ 34, Las Vegas: holdout MAE 8.4%, |MBE| 5.4%, dry-spell decline slope ratio
1.0002; see `docs/audits/pvdaq34_field_validation_2026-07-18.md`). This validates the
model framework at a documented comparable site — it does not measure Riyadh's soiling
rate, so the Riyadh runtime values below remain provisional.

## Partially Resolved By The 2026-07-18 Literature Pass

- Dry accumulation, seasonal multipliers, rainfall thresholds, dust-event frequency, and the
  soiling floor are now anchored to published measured campaigns near Riyadh (Rumah/K.A.CARE),
  Dhahran long-exposure data, and Saudi dust climatology (see `source_bibliography.md`). They
  remain `provisional` because published campaigns at analogous sites are not this farm's own
  soiling station.
- The electricity tariff envelope now includes quoted Saudi PPA benchmarks (0.039-0.070 SAR/kWh)
  alongside the retail tariff; sensitivity sweeps span both offtake worlds.
- Water cost is now anchored to the quoted commercial/industrial tariff structure (6-9 SAR/m3
  plus delivery overhead).

## High Priority (Still Open)

- Obtain this site's own measured soiling-ratio data (reference cell, soiling station, or
  production regression) to move soiling parameters from `provisional` to `validated`.
- Decide the actual offtake structure (PPA vs. netting vs. industrial tariff). Under PPA pricing
  the central 0.18 SAR/kWh retail valuation overstates avoided-soiling value by roughly 3-4x,
  which can change the mitigation ranking.
- Replace bird-dropping frequency, coverage, persistence, and loss mapping with site observations,
  imagery labels, or maintenance records (no reliable published source exists).
- Confirm delivered water cost and cleaning method for the actual site logistics.

## T2 Reactive CV

- Provide the selected CV model, image source, confusion matrix, severity-error metric, and test
  geography.
- Define inspection route assumptions: altitude, overlap, camera, flight speed, panels per image,
  battery swaps, and heat derating.
- Define a cleaning action size so labor hours, water, and crew throughput can be tied to actual
  scenario behavior.

## T3 Coating And Economics

- Select the coating technology or product before applying coating effectiveness, optical penalty,
  degradation, cooling, dew, or water-collection values.
- Provide coating capex, application labor, warranty, maintenance, and recoating schedule.
- Provide finance assumptions: WACC or discount rate, equipment useful lives, tax/subsidy treatment,
  and residual value if used.

## T4 Analytics

- Decide how blocked/provisional/unsourced parameters should appear in dashboards and comparison
  reports.
- Preserve unknown registry fields when presenting sensitivity analysis so evidence quality remains
  visible to users.

## Current Blocked Paths

The blocked paths are listed in `docs/calibration/interface_requests.md`. They must not be added to
`SolarCleanConfig` by T5 unless the owning team agrees to the interface.
