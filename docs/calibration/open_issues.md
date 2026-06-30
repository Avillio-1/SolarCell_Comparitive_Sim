# Calibration Open Issues

## High Priority

- Obtain measured Riyadh or Saudi arid-site soiling-ratio data for dry accumulation, seasonal
  multipliers, rainfall recovery, and dust-event severity.
- Replace bird-dropping frequency, coverage, persistence, and loss mapping with site observations,
  imagery labels, or maintenance records.
- Confirm the electricity tariff class for the simulated farm. The registry uses a provisional Saudi
  tariff envelope, but real project economics may use a PPA, netting rule, or industrial tariff.
- Confirm delivered water cost and cleaning method. NWC tariff pages may not represent water
  delivered to a utility PV farm.

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
