# T1 Parallel Development Checklist

## Shared Rules For T2, T3, And T4

- Use `ScenarioContext` as read-only input.
- Consume `ExogenousEventTape`; do not regenerate dust, bird, or cohort variation events.
- Implement `MitigationStrategy` for new scenario behavior.
- Return `DailyScenarioResult` from each daily step.
- Store scenario-specific fields in `extensions`; do not add required common fields for one scenario only.
- Use `OperationalQuantities` for inspections, cleaning, drone hours, coating counts, water, energy, and cost placeholders.
- Keep annual iteration inside `ScenarioSimulationEngine`.
- Do not add scenario-name conditionals to the shared engine.
- Preserve common energy invariants: actual energy is non-negative and cannot exceed clean energy.

## T2 Reactive CV Developer

- Own future modules under a reactive/CV-specific package.
- Implement `ReactiveCVStrategy` later against `MitigationStrategy`.
- Add reactive-specific config in a new section rather than editing baseline soiling config.
- Use `cohort_id` to target inspections or cleaning when T2 behavior is approved.
- Do not implement economics or dashboard behavior in T2.

## T3 Coating And Economics Developer

- Implement coating behavior as `CoatingStrategy` later.
- Keep coating physics and degradation assumptions in coating-owned config.
- Put economics aggregation downstream of `AnnualScenarioResult`.
- Do not change weather, clean PV, event tape, or baseline contracts for coating-specific needs.

## T4 Analytics And Dashboard Developer

- Treat `AnnualScenarioResult.summary()`, `to_daily_frame()`, and scenario output files as input contracts.
- Ignore unknown `extension_` columns unless a feature explicitly needs them.
- Do not import NASA, pvlib, or strategy internals into dashboard code.
- Do not mutate scenario context, event tape, or result dataclasses.

## Four-Person Branch Ownership

| Area | Primary Owner | Allowed Files |
| --- | --- | --- |
| Core contracts and baseline compatibility | T1/core owner | `src/solarclean/domain/scenario`, `src/solarclean/domain/simulation`, contract docs |
| Reactive CV | T2 owner | future reactive package, reactive tests, reactive docs |
| Coating/economics | T3 owner | future coating/economics packages, economic tests, assumptions docs |
| Analytics/dashboard | T4 owner | future analytics/dashboard package, output consumers, visual docs |

Cross-owner changes to frozen contracts require an ADR update and contract-test changes.

