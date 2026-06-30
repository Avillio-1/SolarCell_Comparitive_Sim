# SolarClean-DT T3 Coating Scenario Design

## Purpose

T3 adds Scenario 3: a KAUST-inspired proactive radiative-cooling coating scenario for SolarClean-DT. The scenario must model coating physics, passive cleaning, water production, and cost-ready deployment quantities while using the frozen T1 `MitigationStrategy` contract and the shared `ScenarioSimulationEngine`.

The coating scenario is a Phase 4 consumer of the Phase 1-3.5 foundation. It must not duplicate the annual simulation loop, mutate the shared exogenous event tape, replace T4 economics, or invent T5 calibration data that is not available in the repository.

## Source Boundary

The prompt names the paper `Closing the Loop in Agrivoltaics: A Radiative Cooling Coating for Synergistic Self-Cleaning and Water Harvesting`, but no PDF or extracted paper text is present in the current attachment set or repository. The design therefore treats only the prompt-provided paper facts as available calibration evidence:

- solar transmittance approximately 91.3%;
- atmospheric-window emissivity approximately 0.90 across 8-13 um;
- contact angle approximately 167 degrees and sliding angle approximately 3 degrees;
- outdoor six-month coated-panel power loss about 1.5%, compared with about 28% uncoated;
- outdoor water yield about 128 g/m^2 per night under the tested conditions;
- tested nighttime humidity approximately 72-92%;
- durability evidence from natural-soiling, UV-aging, and thermal-aging tests;
- 400 C, 30 minute thermal treatment, with direct field application to installed PV modules not demonstrated.

These values are calibration targets and assumptions, not universal Riyadh constants. The Riyadh run must remain weather-dependent.

## Recommended Architecture

Add a coating-owned domain package under `src/solarclean/domain/coating`. The package implements physical submodels and a `CoatingStrategy` that plugs into `ScenarioSimulationEngine`. Scenario-specific daily and annual fields stay in `DailyScenarioResult.extensions` and `AnnualScenarioResult.extensions`; common T1 contracts remain unchanged.

Configuration adds a `coating` section to `SolarCleanConfig`, with nested validated Pydantic models for physical behavior, water collection, cost basis, deployment mode, and low/central/high presets. The defaults are conservative provisional values, with explicit source/status fields where the prompt-supplied paper targets or provisional assumptions are used.

Application code adds a `RunCoatingSimulation` use case and a `solarclean run-coating` CLI command. The use case builds weather, clean PV, farm, event tape, and context the same way baseline does, then runs `ScenarioSimulationEngine(CoatingStrategy(...))`.

## Components

### Coating Configuration

`CoatingConfig` owns all coating assumptions:

- `enabled`: whether the coating strategy starts with applied coating.
- `preset`: weak, central, strong, or paper-calibration.
- `deployment_mode`: factory_preinstall or retrofit.
- `area_per_panel_m2` or equivalent area derivation from configured PV capacity.
- optical transmittance multiplier.
- emissivity and cooling coefficients.
- dust adhesion or accumulation multiplier.
- passive dew-cleaning efficiency parameters.
- bird-dropping removal limit and efficiency.
- degradation rate, useful life, and reapplication interval.
- condensate collection efficiency and actually collected fraction.
- material loading, material cost, surface preparation, application labor, process energy, fixed setup/equipment, inspection, and maintenance quantities.

Pydantic validation enforces bounded fractions, non-negative costs and quantities, and internally consistent useful life and reapplication intervals.

### Physical Models

`physics.py` contains pure functions and small dataclasses:

- dew point from air temperature and relative humidity, using a Magnus-style approximation;
- coated surface temperature from air temperature, humidity, wind, irradiance, emissivity, and configurable radiative-cooling coefficients;
- condensation eligibility only when coated surface temperature is below dew point;
- condensed water from dew-point depression, humidity, nighttime exposure, and a calibrated water-yield coefficient;
- passive cleaning from condensate amount, panel tilt, contamination type, coating age, and coating effectiveness;
- separately bounded bird-dropping removal;
- optical energy multiplier from transmittance;
- temperature/cooling energy adjustment using the PV temperature coefficient from `pv_system.gamma_pdc_per_c` without adding a paper total-gain shortcut.

The model reports mechanisms separately so output consumers can distinguish optical penalty, thermal gain, and cleanliness gain.

### Coating State

`state.py` defines per-cohort coating state:

- applied flag;
- age in days;
- effectiveness fraction;
- degradation fraction;
- dust soiling ratio;
- bird coverage and bird loss;
- cumulative condensed, collectable, and actually collected water;
- cumulative inspection or maintenance counters.

The state is advanced one day at a time by the strategy. Degradation is bounded so effectiveness never becomes negative and never exceeds the configured initial effectiveness.

### Cost Basis

`costs.py` defines `CoatingCostBasis`, a dataclass containing cost-ready quantities for T4:

- total coated area;
- material loading per m^2;
- total material mass or volume;
- material cost per m^2;
- surface preparation cost per m^2;
- application labor hours and cost basis;
- process-energy kWh;
- fixed equipment/setup cost;
- inspection or maintenance quantities;
- useful life and reapplication interval;
- deployment mode;
- optional water-collection infrastructure quantity;
- source/status metadata for low, central, and high assumptions.

The coating physics classes do not contain SAR values, annualization formulas, discounted cash flow, electricity tariffs, or water revenue. If a T4 economics engine is later available, the application layer can pass `CoatingCostBasis` into it. Until then, `AnnualScenarioResult.extensions["coating_cost_basis"]` exposes the complete contract.

### Strategy

`strategy.py` implements `CoatingStrategy`:

- `initial_state(context, rng)` initializes one coating state per cohort using `context.farm_config`.
- `simulate_day(day_input, state, context, rng)` consumes the shared daily clean energy, daily environment, hourly weather for the date from `context.weather.hourly`, and `day_input.event_inputs`.
- Dust and bird exogenous events come only from the shared event tape or existing RNG fallback path; the coating strategy does not regenerate the tape.
- Natural rainfall cleaning uses behavior consistent with the shared contamination/farm model.
- Passive dew cleaning is applied after condensation eligibility is computed.
- Energy is calculated with separate clean reference, optical, thermal, and cleanliness terms, and then clamped to a physically justified maximum no greater than clean reference energy unless the configured cooling model justifies a small cooling recovery before the T1 result cap. The final `DailyScenarioResult.actual_energy_kwh` must satisfy the T1 invariant and cannot exceed `clean_energy_kwh`.

Daily extensions include:

- clean reference energy;
- optical effect kWh and multiplier;
- thermal/cooling effect kWh and multiplier;
- cleanliness effect kWh and ratio;
- final coated energy;
- condensed water liters;
- potentially collectable water liters;
- actually collected water liters;
- coating age and effectiveness;
- average dust soiling ratio;
- average bird loss fraction;
- coated panel count;
- coated area;
- daily cost-basis quantities;
- event-tape checksum if available.

Annual extensions include summed water quantities, aggregate energy mechanism totals, final cost basis, deployment limitations, calibration source notes, and open interface requests for T4/T5.

### Event Logs

The strategy emits `DomainEvent` records for:

- initial coating application;
- daily dew condensation when water is produced;
- passive dust cleaning;
- limited bird-dropping removal;
- effective rainfall cleaning;
- reapplication or maintenance when the configured interval is reached.

Event metadata records cohort id when relevant, mechanism, water quantity, removal fraction, coating age, and calibration source status.

## Data Flow

1. The application loads `SolarCleanConfig`.
2. Weather and clean PV are generated through existing providers and PVWatts.
3. The application generates or reuses the same `ExogenousEventTape` used by baseline for the same config, dates, and seed.
4. `ScenarioContext.from_inputs()` freezes weather, clean energy, event tape, farm config, and metadata.
5. `ScenarioSimulationEngine(CoatingStrategy(...)).run(context, seed)` runs the single shared annual loop.
6. The strategy computes per-day coating physics and returns `DailyScenarioResult`.
7. `OutputWriter.write_scenario_result()` persists generic scenario outputs with extension columns.
8. The coating use case writes a comparison summary that includes baseline-versus-coating annual energy, event tape checksum, water quantities, and cost-basis availability.

## Calibration Fixtures And Presets

Add weak, central, and strong coating presets. The central preset uses the prompt-supplied paper targets as calibration anchors but keeps weather-dependent Riyadh calculations. The weak and strong presets widen assumptions around dust adhesion, passive cleaning, cooling, degradation, and collectable water.

Add a dedicated paper-calibration fixture that is not the Riyadh annual run. It uses controlled nighttime humidity in the 72-92% range and enough nighttime exposure to reproduce the documented water-yield target within a stated tolerance. It also checks that a six-month calibration sequence can keep coated soiling loss near the prompt-supplied 1.5% target while an uncoated comparison can approach the 28% reference under the fixture assumptions.

The fixture documents that these are reproduction targets for the prompt-provided paper facts, not field-validated Riyadh predictions.

## Error Handling And Invariants

- Invalid fractions, negative costs, negative water, or inconsistent useful-life inputs fail config validation.
- Missing hourly weather columns fail clearly before simulation.
- Condensation is zero when relative humidity, dew point, or surface temperature conditions fail.
- Passive dew cleaning cannot make dust or bird contamination cleaner than physically clean.
- Bird-dropping removal is separately limited and cannot silently reuse dust-cleaning efficiency.
- Actual collected water cannot exceed potentially collectable water, and potentially collectable water cannot exceed condensed water.
- Coating effectiveness remains in the 0-1 range.
- The event tape checksum for coating and baseline remains identical when using the same context.
- Coating energy mechanisms are reported separately and the paper total improvement is not added as a fourth gain.
- `DailyScenarioResult.actual_energy_kwh` respects the T1 non-negative and no-greater-than-clean-energy invariant.

## Testing Strategy

Write tests before production code:

- dew-point and condensation eligibility;
- no passive dew cleaning when dew conditions fail;
- degradation and effectiveness bounds;
- limited bird-dropping removal independent of dust removal;
- condensed, potentially collectable, and actually collected water accounting;
- optical and cooling effects reported separately without double counting;
- identical event-tape checksum as baseline for the same config and seed;
- reproducibility for repeated coating runs;
- paper-calibration water and six-month power-loss targets within documented tolerances;
- energy never exceeds the T1 invariant;
- cost-basis area and quantities scale correctly for 10,000 panels;
- generic output writer preserves coating extension fields.

Full verification must run:

- `python -m pytest -q`
- `python -m pytest --cov=solarclean --cov-report=term-missing`
- `python -m ruff format --check .`
- `python -m ruff check .`
- `python -m mypy src`
- `solarclean run-coating --config configs/offline_fixture.yaml`

## Documentation Updates

Update `PROGRESS.md` with:

- T3 implementation status;
- paper-source limitation;
- paper-calibration fixture targets and tolerances;
- Riyadh weather-dependent behavior;
- deployment limitation from the 400 C, 30 minute treatment and lack of demonstrated direct field retrofit;
- no free coating assumption;
- no automatic water-revenue assumption;
- cost-data gaps and provisional status;
- inputs still required from T4 economics and T5 calibration.

Add or update architecture, data-contract, assumptions, and ADR docs so future T4/T5 work knows which extension keys and cost-basis fields are available.

## Non-Goals

T3 does not implement a full economic engine, annualization formulas, water revenue, tariffs, discount rates, dashboard analytics, optimization, coating manufacturing scale-up validation, or a new stochastic event generator.

## Acceptance Evidence

- `CoatingStrategy` runs through `ScenarioSimulationEngine`.
- The same event tape checksum is reported for baseline and coating comparison.
- Daily and annual outputs separate clean reference, optical effect, cooling effect, cleanliness effect, final energy, water quantities, coating state, and cost basis.
- Weak, central, strong, and paper-calibration presets load through config.
- Paper-derived targets are reproduced only in the dedicated calibration fixture and documented as prompt-derived.
- Riyadh outputs use actual weather inputs instead of hard-coded paper totals.
- Cost basis is complete enough for T4 while monetary valuation remains outside coating physics.
- Existing and new tests, Ruff, and mypy pass.
