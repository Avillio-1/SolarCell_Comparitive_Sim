# Scenario comparability

A fair comparison changes mitigation behavior while holding exogenous conditions fixed.

## Shared inputs

Every comparison uses one:

- resolved configuration;
- normalized weather dataset;
- clean PV profile;
- immutable exogenous event tape;
- farm definition.

The event tape contains daily dust variation, heavy dust events, bird additions, and cohort
variation. Baseline, reactive, and coating strategies consume the same tape; they cannot regenerate
or mutate it.

## Random streams

`numpy.random.SeedSequence` separates exogenous randomness from scenario-local behavior. Changing a
CV setting may alter reactive decisions, but it must not alter baseline dust or bird events.

A stored seed and event-tape checksum make a run reproducible. Exact reproduction also requires the
resolved configuration, code version, parameter-registry version, and weather checksum.

## Shared engine

`ScenarioSimulationEngine` owns the daily loop and validates each strategy result. Strategies own
only intervention state and day-level decisions. This prevents a scenario from gaining a different
calendar, weather aggregation, or clean-energy reference through a separate loop.

## Reconciliation

Before ranking, the comparison checks:

- identical weather and event-tape checksums;
- annual energy against summed daily energy;
- operational totals against daily records and events;
- cost components against economic totals;
- baseline-relative gains against AC energy;
- ranking uniqueness and ordering.

Failure withholds the ranking. Evidence warnings are reported separately: a run can be
arithmetically reconciled yet remain exploratory because weather or parameters are provisional.

## Robustness analyses

Monte Carlo, sensitivity, winner maps, and break-even searches call the same comparison use case as
a black box. Parameter ranges come from the calibration registry, and unsupported mappings are
reported rather than guessed.
