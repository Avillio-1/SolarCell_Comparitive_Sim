# Scenario contract reference

All scenarios implement `MitigationStrategy` and run through
`ScenarioSimulationEngine`. The contracts live in `solarclean.domain.scenario.contracts`.

## Shared flow

| Contract | Responsibility |
| --- | --- |
| `ScenarioContext` | Copy-protected weather and clean energy, immutable event tape, farm config, provenance |
| `DailyScenarioInput` | Site-local date, clean energy, daily environment, event inputs, day index |
| `MitigationStrategy` | Initialize scenario state and simulate one day |
| `DailyScenarioResult` | Energy, operations, events, and scenario extensions for one day |
| `AnnualScenarioResult` | Immutable daily results plus derived period totals |

A strategy result must echo the input date, strategy name, and shared clean-energy value. The
engine rejects mismatches.

## Strategy protocol

```python
class MitigationStrategy(Protocol):
    name: str

    def initial_state(
        self, context: ScenarioContext, rng: numpy.random.Generator
    ) -> object: ...

    def simulate_day(
        self,
        day_input: DailyScenarioInput,
        state: object,
        context: ScenarioContext,
        rng: numpy.random.Generator,
    ) -> StrategyStep: ...
```

Strategies own intervention state and day-level decisions. The engine owns iteration and input
construction.

## Common daily result

| Field | Unit | Rule |
| --- | --- | --- |
| `clean_energy_kwh` | kWh/day | Shared clean reference |
| `actual_energy_kwh` | kWh/day | Finite and non-negative |
| `energy_loss_kwh` | kWh/day | Derived as clean minus actual |
| `soiling_ratio` | fraction | Derived as actual divided by clean |
| `operational` | mixed | Shared non-negative quantities |
| `events` | event-specific | Ordered immutable events |
| `extensions` | scenario-specific | JSON-safe values |

Actual energy cannot exceed clean energy unless a strategy explicitly allows a physical
above-reference effect. The coating strategy may do this for configured optical or thermal gains;
cleaning alone may not.

## Operational quantities

| Field | Unit |
| --- | --- |
| `inspections_count` | count/day |
| `cleaning_actions_count` | count/day |
| `coated_panel_count` | panels |
| `crew_hours` | hours/day |
| `drone_flight_hours` | hours/day |
| `water_liters` | L/day |
| `energy_used_kwh` | kWh/day |
| `opex_cost`, `capex_cost` | SAR/day |

Scenario physics report physical operations. The downstream economics layer values them.

## Events

Events include their recorded date, modeled phase, sequence within the day, and
`effective_for_energy_date`. Dust and bird additions affect current-day energy. Rain, crew
cleaning, and nighttime coating actions normally affect the next day's energy state.

## Extensions

- Use stable string keys.
- Persist daily keys with an `extension_` prefix.
- Keep common energy comparison independent of extensions.
- Preserve or ignore unknown keys in generic consumers.
- Store structured values as JSON-safe mappings or sequences.

Reactive extensions include inspection outcomes, backlogs, queue state, flights, and detection
diagnostics. Coating extensions include optical, temperature, cleanliness, coating-state, and
water-chain diagnostics.
