# T3 Coating Scenario Data Contract

The coating scenario is a T1 `MitigationStrategy` named `coating`. It runs through
`ScenarioSimulationEngine` and writes scenario-specific values through
`DailyScenarioResult.extensions`.

Persisted CSV columns use the generic `extension_` prefix from
`OutputWriter.write_scenario_result()`.

| Key | Unit | Meaning |
| --- | --- | --- |
| `clean_reference_energy_kwh` | kWh/day | Unmodified clean PV reference energy. |
| `optical_effect_kwh` | kWh/day | Realized energy effect of relative coated-versus-uncoated PV optical performance. |
| `temperature_effect_kwh` | kWh/day | Realized energy effect of coated-surface cooling after optical and cleanliness effects. |
| `cleanliness_effect_kwh` | kWh/day | Realized energy effect of dust and bird contamination after optical effect. |
| `final_coated_energy_kwh` | kWh/day | Final scenario energy after realized mechanisms. |
| `condensed_water_liters` | L/day | Total condensed water over the whole simulated coated farm. |
| `potentially_collectable_water_liters` | L/day | Whole-farm condensed water after collection hardware efficiency. |
| `actually_collected_water_liters` | L/day | Whole-farm collected water after actual collection efficiency. |
| `coating_age_days` | days | Age of the active coating state. |
| `coating_effectiveness_fraction` | fraction | Panel-count weighted coating effectiveness. |
| `average_dust_soiling_ratio` | fraction | Panel-count weighted dust ratio. |
| `average_bird_loss_fraction` | fraction | Panel-count weighted bird-dropping loss. |
| `coated_area_m2` | m2 | Total coated module area. |
| `coating_cost_basis` | JSON object | T4-ready cost quantities without annualization or revenue. |
| `event_tape_checksum` | SHA-256 string | Shared exogenous event tape checksum. |

The coating comparison summary keeps legacy `annual_*` keys for compatibility,
but also reports `period_*` aliases plus period start, end, day count, and
whether the simulated period is a full calendar year. A one-day paper fixture is
therefore a one-day period total, not an annualized Riyadh result.

The coating scenario reports condensed water, potentially collectable water, and
actually collected water separately as whole-farm totals and normalized
liters/m2 period yields. The water chain is sequential: gross condensation,
then physically collectable water, then actually harvested water. It does not
value collected water as revenue. T4 owns monetary valuation and annualization.

The clean energy reference is the clean uncoated PVWatts AC output at the normal
modeled operating temperature. Baseline and cleaning-only scenarios remain
bounded by that clean reference. Coating scenarios may opt into above-reference
output when relative optical or thermal physics justify a genuine coated-module
gain; contamination recovery itself remains bounded by cleanliness ratio <= 1.

The active optical multiplier is relative coated-versus-uncoated PV performance.
Absolute material transmittance, such as the prompt-quoted 91.3% coated-glass
value, is source metadata and not a direct PV energy multiplier.
