# CLI reference

Run commands from the repository root:

```powershell
python -m solarclean.cli.main COMMAND --help
```

Use an explicit `--config` even where a command has a default.

## Simulation commands

| Command | Purpose | Main options |
| --- | --- | --- |
| `fetch-weather` | Load and persist normalized weather | `--config PATH` |
| `run-clean` | Calculate clean hourly and daily PV energy | `--config PATH` |
| `run-baseline` | Run no-intervention contamination | `--config PATH` |
| `run-reactive` | Run reactive CV inspection and cleaning | `--config PATH` |
| `run-coating` | Run the coating scenario | `--config PATH` |
| `compare-all-scenarios` | Compare baseline, reactive, and coating scenarios | `--config PATH` |

Canonical example:

```powershell
python -m solarclean.cli.main compare-all-scenarios `
  --config configs/offline_fixture_full_year.yaml
```

## Robustness commands

| Command | Purpose | Main options |
| --- | --- | --- |
| `compare-multi-year` | Repeat comparison across weather years | `--config`, `--start-year`, `--end-year` |
| `monte-carlo` | Repeat comparisons across event seeds and optional parameter samples | `--config`, `--trials`, `--base-seed`, `--uncertainty-mode` |
| `sensitivity-oneway` | Sweep registered parameters independently | `--config`, repeatable `--parameter`, `--steps` |
| `sensitivity-winner-map` | Sweep two parameters on a grid | `--config`, `--parameter-a`, `--parameter-b`, `--grid-steps` |
| `break-even` | Find a parameter value where two scenarios tie | `--config`, `--parameter`, `--scenario-a`, `--scenario-b`, `--max-evaluations` |

`monte-carlo --uncertainty-mode` accepts `stochastic_seed_only` or
`parameters_and_seed`. Parameter names come from `data/calibration/parameter_registry.yaml`, but
only the supported override catalog is executable.

## Validation commands

| Command | Purpose | Main options |
| --- | --- | --- |
| `validate-weather` | Check hourly coverage, units, ranges, and suspicious values | `--config PATH` |
| `validate-phase-3-5` | Validate weather, energy, farm equivalence, event tape, and performance | `--config PATH` |
| `profile-full-year` | Run the same full validation with performance reporting | `--config PATH` |
| `validate-field` | Compare simulated and measured daily production | `--config`, `--measured-csv`, `--holdout-start YYYY-MM-DD` |

Offline validation:

```powershell
python -m solarclean.cli.main validate-phase-3-5 `
  --config configs/offline_fixture_full_year.yaml
```

See [output files](outputs.md) for artifacts and [validation method](../validation/method.md) for
what each check establishes.
