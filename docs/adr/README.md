# Architecture decision records

ADRs are reserved for decisions that constrain multiple modules or future implementations.
Configuration values, validation findings, and local implementation details belong elsewhere.

| ADR | Decision |
| --- | --- |
| [0001](0001-modular-monolith.md) | Use a modular monolith with inward dependencies |
| [0002](0002-weather-provider-boundary.md) | Normalize all weather behind one provider contract |
| [0003](0003-multiscale-cohort-simulation.md) | Combine hourly PV with daily cohort contamination |
| [0004](0004-deterministic-event-tape.md) | Share immutable exogenous events and separate RNG streams |
| [0005](0005-shared-scenario-engine.md) | Run mitigation strategies through one daily engine |
| [0006](0006-analysis-reuses-comparison.md) | Reuse the reconciled comparison for robustness studies |

Statuses are `Accepted`, `Superseded`, or `Deprecated`. Amend an ADR only to clarify its recorded
decision; create a new ADR to replace it.
