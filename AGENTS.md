# Agent Guide For SolarClean-DT

## Repository Structure

- `src/solarclean/domain`: pure domain contracts, states, and simulation logic. Do not import CLI, persistence, HTTP, NASA, pvlib, plotting, databases, or dashboard code here.
- `src/solarclean/domain/events`: immutable exogenous event tape models shared by baseline and future scenarios.
- `src/solarclean/domain/scenario`: T1 frozen shared scenario contracts, strategy protocol, common result models, operational quantities, and comparison/persistence input contracts.
- `src/solarclean/domain/random`: deterministic RNG stream allocation.
- `src/solarclean/domain/calibration`: provisional calibration preset registry.
- `src/solarclean/domain/validation`: validation report value objects.
- `src/solarclean/application`: use cases and orchestration. This layer wires domain contracts to infrastructure adapters.
- `src/solarclean/infrastructure`: adapters for NASA POWER, CSV/fixture weather, pvlib PVWatts, output persistence, and plotting.
- `src/solarclean/cli`: Typer command wrappers only.
- `src/solarclean/config`: YAML loading and validated configuration models.
- `configs`: runnable YAML examples.
- `data/fixtures`: deterministic test-only weather and regression fixtures.
- `data/local_weather`: example measured-weather CSV import files.
- `outputs`: generated run directories; do not commit generated outputs if git is later initialized.
- `docs`: architecture, data contracts, assumptions, and ADRs.
- `tests`: offline unit/regression tests plus explicitly marked optional integration tests.

## Coding Standards

- Python 3.11 or newer.
- Type hints throughout.
- Use dataclasses for domain value/result types and Pydantic for configuration boundaries.
- Use `pathlib.Path` rather than stringly typed paths.
- Use timezone-aware datetimes; aggregate days in the configured site timezone.
- Use `numpy.random.Generator` and `SeedSequence` for reproducible stochastic behavior.
- Use the Phase 3.5 exogenous event tape when scenario comparability matters. Future scenario-specific RNG streams must not mutate or regenerate the shared tape.
- Use the T1 `MitigationStrategy` contract for future scenario behavior. Do not create a second annual simulation loop for reactive CV, coating, economics, analytics, or dashboard work.
- Store scenario-specific output fields in `DailyScenarioResult.extensions` or `AnnualScenarioResult.extensions`; common consumers must tolerate unknown extension keys.
- Keep NASA-specific field names and HTTP behavior inside `solarclean.infrastructure.weather.nasa_power`.
- Keep pvlib-specific objects inside `solarclean.infrastructure.pvlib_adapter`.
- Do not put plotting, file writing, network calls, or CLI parsing into domain objects.
- Do not implement drone, coating, economics, optimization, dashboard, database, or dispatch behavior in Phases 1-3.

## Commands

Install in editable development mode:

```powershell
python -m pip install -e ".[dev]"
```

Run tests:

```powershell
python -m pytest -q
python -m pytest --cov=solarclean --cov-report=term-missing
```

Format and lint:

```powershell
python -m ruff format .
python -m ruff format --check .
python -m ruff check .
```

Type check:

```powershell
python -m mypy src
```

Run the offline commands:

```powershell
solarclean fetch-weather --config configs/offline_fixture.yaml
solarclean run-clean --config configs/offline_fixture.yaml
solarclean run-baseline --config configs/offline_fixture.yaml
```

Run the Riyadh NASA POWER configuration when internet access is available:

```powershell
solarclean fetch-weather --config configs/riyadh_2025.yaml
solarclean run-clean --config configs/riyadh_2025.yaml
solarclean run-baseline --config configs/riyadh_2025.yaml
solarclean validate-weather --config configs/riyadh_2025.yaml
solarclean validate-phase-3-5 --config configs/riyadh_2025.yaml
solarclean profile-full-year --config configs/riyadh_2025.yaml
```

## Architectural Boundaries

- Simulation code accepts `WeatherDataset`, clean energy profiles, farm representations, and soiling models through explicit contracts.
- Changing `weather.provider` from `nasa_power` to `csv` or `fixture` must not require changes in domain or PV simulation code.
- Cohort IDs and cohort-level state are extension points for future inspections and cleaning, but those future controllers must not be added in this phase.
- The event tape is the next clean Phase 4 extension point. New scenarios may consume it but must not change its generated exogenous events.
- The frozen T1 scenario contracts are the shared boundary for parallel work. Cross-team changes require updated contract tests and an ADR.
- Scientific constants belong in validated configuration, not hidden domain literals.

## T1 Parallel Ownership

- Core/contracts owner: `src/solarclean/domain/scenario`, shared simulation engine, baseline compatibility, and contract docs.
- T2 reactive CV owner: future reactive/CV package and tests, implemented as a `MitigationStrategy`.
- T3 coating/economics owner: future coating/economics packages and tests, consuming `AnnualScenarioResult`.
- T4 analytics/dashboard owner: future output consumers and dashboard code, consuming scenario summaries/frames without mutating inputs.
