# SolarClean-DT T5 Parameter Registry

`data/calibration/parameter_registry.yaml` is the authoritative T5 calibration data source.
It covers current baseline parameters and future T2/T3/T4 calibration inputs without changing
the frozen T1 scenario contracts.

## Schema

Each parameter record contains:

- `name`: unique registry key.
- `configuration_path`: intended YAML/config path.
- `category`: one of the calibration topic groups.
- `central_value`, `low_value`, `high_value`: ordered numeric sensitivity values.
- `unit`: original or normalized unit used by SolarClean.
- `source`: short source trail.
- `evidence_type`: `measured`, `calculated`, `inferred`, `quoted`, or `assumed`.
- `source_geography_and_climate`: where the evidence came from.
- `applicability_to_saudi_conditions`: why it is or is not suitable for Riyadh.
- `confidence`: `high`, `medium`, or `low`.
- `status`: `validated`, `provisional`, `blocked`, or `unsourced`.
- `rationale`, `limitations`, and `responsible_module_or_owner`.

## Current Presets

The strict production model currently accepts only existing sections such as `soiling`,
`rainfall_cleaning`, `bird_droppings`, and `farm`. The accepted overlays are:

- `configs/calibration/low.yaml`
- `configs/calibration/central.yaml`
- `configs/calibration/high.yaml`

These overlays are intentionally valid `SolarCleanConfig` overrides. They do not include
future `reactive_cv`, `coating`, or `economics` sections because those models do not exist yet.

## Future Paths

Future configuration paths are still recorded in the registry so T2, T3, and T4 can consume the
same names and evidence. Missing paths are listed in
`docs/calibration/interface_requests.md` and carry `blocked` status where executable use depends
on another owner.

## Usage

Python consumers can load the registry with:

```python
from pathlib import Path

from solarclean.domain.calibration.registry import ParameterRegistry

registry = ParameterRegistry.from_yaml(Path("data/calibration/parameter_registry.yaml"))
soiling = registry.get("soiling.base_daily_loss_fraction")
```

T4 economics can map an already-loaded registry into runtime economics objects without making
`EconomicEngine` read YAML:

```python
from solarclean.domain.economics.calibration import build_economics_from_parameter_registry

calibration = build_economics_from_parameter_registry(registry)
economic_config = calibration.config
reactive_rates = calibration.reactive_cost_rates
equipment_components = calibration.equipment_cost_components
```

The default economics bridge permits blocked or provisional values for research and sensitivity
runs, returning warnings that name each registry key and status. Use
`status_policy="require_validated"` when decision workflows must reject blocked, provisional, or
unsourced values. `economics.drone_equipment_cost_sar` is exposed as a traceable capex component,
not converted into a flight-hour rate, because the registry does not define utilization or
allocation assumptions.

To exercise current presets through production models, run:

```powershell
python scripts/calibration/run_preset_sensitivity.py --base-config configs/offline_fixture.yaml --preset-dir configs/calibration --dry-run
```

Remove `--dry-run` to call `solarclean.application.phase35.Phase35Validator`.
