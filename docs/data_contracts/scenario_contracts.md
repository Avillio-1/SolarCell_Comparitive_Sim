# T1 Scenario Contract Data Dictionary

T1 freezes shared scenario contracts for baseline, reactive CV, coating, economics, analytics, and dashboard work. These contracts live in `solarclean.domain.scenario.contracts`.

## Ownership

| Contract | Owner | Consumers |
| --- | --- | --- |
| `ScenarioContext` | Core/contracts owner | T2 reactive, T3 coating/economics, T4 analytics/dashboard |
| `MitigationStrategy` | Core/contracts owner | Scenario developers |
| `DailyScenarioResult` | Core/contracts owner | Persistence, analytics, comparison, dashboard |
| `AnnualScenarioResult` | Core/contracts owner | Persistence, analytics, economics, dashboard |
| `ScenarioComparisonInput` | Analytics/comparison owner after T1 | Scenario runners and economics |
| `ScenarioOutputBundle` | Persistence owner | CLI, analytics, dashboard |

## ScenarioContext

| Field | Type | Unit | Owner | Notes |
| --- | --- | --- | --- | --- |
| `weather` | `FrozenWeatherInput` | canonical weather units | Weather/application | Exposes copy-protected hourly weather. |
| `clean_energy` | `FrozenCleanEnergyInput` | kWh and W columns | PV/application | Exposes copy-protected clean PV tables. |
| `event_tape` | `ExogenousEventTape | None` | event-specific | Core/contracts | Immutable stochastic dust, bird, and cohort inputs. |
| `farm_config` | `FarmConfig | None` | panels, W | Configuration owner | Shared panel/cohort structure. |
| `metadata` | immutable mapping | mixed | Application | Run tags, checksums, provenance. |

## DailyScenarioInput

| Field | Type | Unit | Owner |
| --- | --- | --- | --- |
| `date` | `datetime.date` | local site date | Shared engine |
| `clean_energy_kwh` | `float` | kWh/day | Shared engine |
| `clean_energy_per_panel_kwh` | `float` | kWh/panel/day | Shared engine |
| `environment` | `DailyEnvironment` | mm, percent | Shared engine |
| `event_inputs` | `DailyEventInputs | None` | event-specific | Event tape |
| `day_index` | `int` | zero-based day | Shared engine |

## MitigationStrategy

Strategies implement:

- `name: str`
- `initial_state(context, rng) -> object`
- `simulate_day(day_input, state, context, rng) -> StrategyStep`

The strategy owns only day-level intervention behavior and opaque state. The shared engine owns annual iteration.

## DailyScenarioResult

| Field | Type | Unit | Owner |
| --- | --- | --- | --- |
| `date` | `datetime.date` | local site date | Strategy |
| `scenario_name` | `str` | none | Strategy |
| `clean_energy_kwh` | `float` | kWh/day | Shared engine/strategy echo |
| `actual_energy_kwh` | `float` | kWh/day | Strategy |
| `energy_loss_kwh` | derived `float` | kWh/day | Contract |
| `soiling_ratio` | derived `float` | fraction | Contract |
| `operational` | `OperationalQuantities` | mixed | Strategy |
| `events` | tuple of `DomainEvent` | event-specific | Strategy |
| `extensions` | immutable mapping | scenario-specific | Strategy |

`actual_energy_kwh` must not exceed `clean_energy_kwh`.

## OperationalQuantities

| Field | Type | Unit |
| --- | --- | --- |
| `inspections_count` | `int` | count/day |
| `cleaning_actions_count` | `int` | count/day |
| `coated_panel_count` | `int` | panels |
| `crew_hours` | `float` | hours/day |
| `drone_flight_hours` | `float` | hours/day |
| `water_liters` | `float` | liters/day |
| `energy_used_kwh` | `float` | kWh/day |
| `opex_cost` | `float` | configured currency/day |
| `capex_cost` | `float` | configured currency/day |

Baseline uses zeros. T2/T3/T4 may fill relevant fields without changing common aggregation.

## DomainEvent

| Field | Type | Unit |
| --- | --- | --- |
| `date` | `datetime.date` | local site date |
| `scenario_name` | `str` | none |
| `event_type` | `str` | none |
| `magnitude` | `float` | event-specific |
| `description` | `str` | none |
| `cohort_id` | `int | None` | cohort identifier |
| `metadata` | immutable mapping | event-specific |

## AnnualScenarioResult

| Field | Type | Unit |
| --- | --- | --- |
| `scenario_name` | `str` | none |
| `daily_results` | tuple of `DailyScenarioResult` | days |
| `events` | tuple of `DomainEvent` | events |
| `annual_clean_energy_kwh` | derived `float` | kWh/year |
| `annual_actual_energy_kwh` | derived `float` | kWh/year |
| `annual_energy_loss_kwh` | derived `float` | kWh/year |
| `annual_energy_loss_percent` | derived `float` | percent |
| `extensions` | immutable mapping | scenario-specific |

Common consumers should use `summary()` and `to_daily_frame()` and ignore unknown extension keys.

## Extension Rules

- Extension keys must be stable strings.
- Common result handling preserves unknown extension keys with an `extension_` column prefix.
- Extensions may contain JSON-safe scalars or structured values.
- Extensions must not be required for common annual energy comparison.

