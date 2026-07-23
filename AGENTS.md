# Contributor guide for SolarClean-DT

## Repository map

- `src/solarclean/domain`: pure contracts, state, physics, strategies, economics, and simulation.
- `src/solarclean/application`: use cases, comparisons, validation, and robustness studies.
- `src/solarclean/infrastructure`: weather, pvlib, persistence, report, and plot adapters.
- `src/solarclean/config`: YAML loading and strict Pydantic models.
- `src/solarclean/cli` and `src/solarclean/dashboard`: interfaces over application use cases.
- `configs/offline_fixture_full_year.yaml`: canonical network-free documentation configuration.
- `configs/default.yaml`: live NASA POWER and dashboard-default configuration.
- `data/calibration/parameter_registry.yaml`: calibration evidence and uncertainty ranges.
- `data/external`: tracked processed field-validation inputs.
- `docs`: concise Diátaxis documentation, scientific validation, and selective ADRs.
- `tests`: offline tests plus explicitly marked network integrations.

## Engineering rules

- Use Python 3.11 or newer and type hints throughout.
- Use dataclasses for domain values and Pydantic at configuration boundaries.
- Use `pathlib.Path`, timezone-aware datetimes, and site-local daily aggregation.
- Use `numpy.random.Generator` and `SeedSequence` for deterministic random streams.
- Keep HTTP, files, plotting, pvlib objects, CLI parsing, and dashboard behavior out of domain code.
- Keep NASA-specific fields and HTTP behavior in `infrastructure.weather.nasa_power`.
- Keep pvlib-specific objects in `infrastructure.pvlib_adapter`.
- Use the immutable exogenous event tape for comparable scenarios.
- Add scenario behavior through `MitigationStrategy`; do not add a second annual loop.
- Put scenario-specific fields in result extensions. Common consumers must tolerate unknown keys.
- Keep scientific constants in validated configuration or the calibration registry.

## Commands

```powershell
python -m pip install -e ".[dev,dashboard]"
python -m pytest -q
python -m ruff format --check .
python -m ruff check .
python -m mypy src
```

Run the canonical comparison:

```powershell
python -m solarclean.cli.main compare-all-scenarios `
  --config configs/offline_fixture_full_year.yaml
```

## Documentation

- Use `configs/offline_fixture_full_year.yaml` for network-free examples.
- Put procedures in `docs/guides`, contracts in `docs/reference`, rationale in `docs/concepts`,
  and evidence in `docs/validation`.
- Add an ADR only for a decision that constrains multiple modules or future work.
- Link to canonical pages instead of repeating them.
