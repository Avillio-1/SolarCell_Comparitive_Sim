# Contribute safely

Use this guide when changing the simulator or its documentation.

## Install development dependencies

```powershell
python -m pip install -e ".[dev,dashboard]"
```

## Preserve boundaries

| Area | Responsibility |
| --- | --- |
| `domain` | Pure contracts, states, physics, strategies, and deterministic simulation |
| `application` | Use-case orchestration and comparisons |
| `infrastructure` | NASA/CSV/fixture weather, pvlib, persistence, and plots |
| `config` | YAML loading and validated Pydantic boundaries |
| `cli` and `dashboard` | User interfaces over application use cases |

Do not import HTTP, persistence, plotting, pvlib, CLI, or dashboard code into the domain. Add
scenario behavior through `MitigationStrategy`; do not create another annual loop.

## Run quality checks

```powershell
python -m pytest -q
python -m pytest --cov=solarclean --cov-report=term-missing
python -m ruff format --check .
python -m ruff check .
python -m mypy src
```

Live NASA tests are opt-in:

```powershell
$env:SOLARCLEAN_RUN_NETWORK_TESTS = "1"
python -m pytest tests/integration/test_nasa_power_live.py -q
```

## Update documentation

- Use `configs/offline_fixture_full_year.yaml` in network-free examples.
- Put procedures in `guides`, exact behavior in `reference`, rationale in `concepts`, and evidence
  in `validation`.
- Add an ADR only when a decision constrains several modules or future implementations.
- Update the relevant contract page when an output schema or CLI option changes.
- Do not copy parameter values out of the canonical config or calibration registry unless the
  value is needed for interpretation.
- Test commands and relative links before submitting the change.
