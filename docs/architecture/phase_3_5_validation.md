# Phase 3.5 Validation Architecture

Phase 3.5 adds validation and reproducibility infrastructure without implementing Phase 4 scenarios.

## Responsibilities

- Validate a complete hourly weather dataset without interpolation or silent repair.
- Run clean PV and no-intervention baseline simulations using a shared exogenous event tape.
- Report annual and monthly energy, specific yield, capacity factor, clipping, soiling loss, contamination events, rainfall events, farm-equivalence invariants, and performance.
- Provide provisional Riyadh low/medium/high soiling presets through a calibration registry.

## Event Tape

`ExogenousEventTape` is immutable and JSON-serializable. It contains all stochastic dust, heavy dust, bird, and cohort-variation values needed by baseline and future scenarios. Future scenario-specific randomness uses its own deterministic stream and must not change event-tape contents.

## Reports

`Phase35Validator` writes:

- `phase35_weather_report.json`
- `phase35_energy_report.json`
- `phase35_farm_equivalence_report.json`
- `phase35_event_tape.json`
- `phase35_performance_report.json`
- `phase35_summary.json`

These reports are local files under the generated run directory. They are not API responses and do not require a database.

## Non-Goals

Phase 3.5 does not implement drones, CV, manual cleaning, coating behavior, economics, sensitivity analysis, APIs, dashboards, or optimization.

