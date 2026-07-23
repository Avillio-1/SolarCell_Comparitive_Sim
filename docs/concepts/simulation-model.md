# Simulation model

The model combines hourly clean PV production with daily contamination and intervention state.

## Clean PV

The pvlib adapter calculates solar position, plane-of-array irradiance, cell temperature, PVWatts
DC power, explicit non-soiling system losses, inverter efficiency, and clipping. It produces an
hourly clean AC reference.

The system-loss multiplier is the product of the complements of wiring, mismatch, connection,
nameplate, light-induced degradation, and availability losses. Soiling is excluded from this chain
and applied by the scenario model.

The current clean model does not represent snow or explicit shading.

## Daily state order

For each site-local day:

1. The shared engine supplies clean energy, aggregated weather, and event-tape inputs.
2. Dust accumulation, optional dew cementation, heavy dust, and bird events form the state used for
   that day's energy.
3. The strategy calculates actual energy and records operations.
4. Rain, crew cleaning, and nighttime coating mechanisms update the state used by the next day.
5. Events record both their occurrence date and effective energy date.

This order prevents a cleaning action late in a day from improving energy already generated.

## Farm representation

The canonical model uses 100 cohorts of 100 panels. Cohorts retain local dust and bird state and
provide targets for inspection or cleaning. Energy is calculated per cohort and summed exactly
once.

The representative-panel mode is a lower-detail alternative. With homogeneous state, it should
match cohort aggregation within numerical tolerance.

## Baseline

The baseline applies a configuration-driven Kimber-style empirical soiling process:

- daily and seasonal dust accumulation;
- seed-controlled heavy dust events;
- a minimum soiling-ratio floor;
- threshold-based partial or full rainfall restoration;
- sparse cohort-level bird contamination;
- optional humidity-driven cementation.

The model is empirical. Its parameters require site calibration for decision use.

## Reactive cleaning

The reactive strategy rotates inspections through cohorts, observes them through a statistical CV
model, applies weather and flight-capacity limits, dispatches from estimated loss and confidence,
and cleans within crew capacity. Dispatch receives estimates, not ground-truth contamination.

Inspections and cleanings are recorded as operations and events. Cleaning changes the next day's
physical state.

## Coating

The coating strategy can represent:

- altered dust retention and passive shedding;
- coating degradation;
- relative optical effects;
- surface-temperature effects;
- dew-gated condensation and a staged water collection chain;
- bounded bird-removal behavior.

The clean reference is an uncoated PVWatts result. Only configured optical or thermal physics may
raise coating output above it. Contamination recovery remains bounded by a cleanliness ratio of
one.

The canonical coating case is a paper-anchored research extrapolation, not demonstrated field
performance for a Riyadh farm.

## Economics

Economics consume annual scenario energy and operations after simulation. Common farm costs are
outside the mitigation comparison. Calibration sources, uncertainty ranges, and status are read
from the parameter registry.
