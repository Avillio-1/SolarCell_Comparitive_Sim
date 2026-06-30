# T3 Coating Scenario Data Contract

The coating scenario is a T1 `MitigationStrategy` named `coating`. It runs through
`ScenarioSimulationEngine` and writes scenario-specific values through
`DailyScenarioResult.extensions`.

Persisted CSV columns use the generic `extension_` prefix from
`OutputWriter.write_scenario_result()`.

| Key | Unit | Meaning |
| --- | --- | --- |
| `clean_reference_energy_kwh` | kWh/day | Unmodified clean PV reference energy. |
| `optical_effect_kwh` | kWh/day | Energy effect of coating optical transmittance. |
| `temperature_effect_kwh` | kWh/day | Energy effect of coated-surface cooling. |
| `cleanliness_effect_kwh` | kWh/day | Energy effect of dust and bird contamination. |
| `final_coated_energy_kwh` | kWh/day | Final scenario energy after separated mechanisms. |
| `condensed_water_liters` | L/day | Total condensed water. |
| `potentially_collectable_water_liters` | L/day | Condensed water after collection hardware efficiency. |
| `actually_collected_water_liters` | L/day | Collected water after actual collection efficiency. |
| `coating_age_days` | days | Age of the active coating state. |
| `coating_effectiveness_fraction` | fraction | Panel-count weighted coating effectiveness. |
| `average_dust_soiling_ratio` | fraction | Panel-count weighted dust ratio. |
| `average_bird_loss_fraction` | fraction | Panel-count weighted bird-dropping loss. |
| `coated_area_m2` | m2 | Total coated module area. |
| `coating_cost_basis` | JSON object | T4-ready cost quantities without annualization or revenue. |
| `event_tape_checksum` | SHA-256 string | Shared exogenous event tape checksum. |

The coating scenario reports condensed water, potentially collectable water, and
actually collected water separately. It does not value collected water as revenue.
T4 owns monetary valuation and annualization.
