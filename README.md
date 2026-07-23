# SolarClean-DT

SolarClean-DT is a Python research simulator for comparing photovoltaic dust-mitigation
strategies. It evaluates no intervention, reactive CV-guided inspection and cleaning, and a
self-cleaning coating against shared weather and contamination inputs.

The framework has passed held-out field comparisons at three public NREL PVDAQ sites. Riyadh
parameters and mitigation economics remain literature-calibrated and provisional; the included
offline weather is synthetic and is not validation evidence.

## Quick start

Requires Python 3.11 or newer.

```powershell
python -m pip install -e ".[dev]"
python -m solarclean.cli.main compare-all-scenarios `
  --config configs/offline_fixture_full_year.yaml
```

The command writes a timestamped package under `outputs/`. Check
`reconciliation_report.json` before using its ranking or recommendation.

## Documentation

| Need | Start here |
| --- | --- |
| Install and run the offline example | [Getting started](docs/getting-started/first-run.md) |
| Run and interpret a comparison | [Comparison guide](docs/guides/run-a-comparison.md) |
| Use fixture, NASA POWER, or CSV weather | [Weather guide](docs/guides/use-weather-data.md) |
| Find a command or output file | [Reference](docs/index.md#reference) |
| Understand the model and architecture | [Concepts](docs/index.md#concepts) |
| Assess scientific evidence and limitations | [Validation](docs/index.md#validation) |
| Review major design decisions | [ADRs](docs/adr/README.md) |

The documentation uses `configs/offline_fixture_full_year.yaml` as its canonical,
network-free configuration. Use `configs/default.yaml` only when live NASA POWER weather is
required.

## Development checks

```powershell
python -m pytest -q
python -m ruff format --check .
python -m ruff check .
python -m mypy src
```

See the [contributor guide](docs/guides/contributing.md) for repository boundaries and the full
quality workflow.
