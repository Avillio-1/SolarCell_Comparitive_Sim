# Configuration reference

SolarClean-DT loads one YAML file into a strict Pydantic model. Unknown fields, invalid ranges, and
cross-section inconsistencies fail before a run starts.

## Canonical configuration

`configs/offline_fixture_full_year.yaml` is the canonical documentation and reproducibility
configuration.

| Setting | Canonical value |
| --- | --- |
| Period | 2025-01-01 00:00 through 2025-12-31 23:00 |
| Timezone | `Asia/Riyadh` |
| Weather | `fixture / riyadh_synthetic` |
| PV system | 10,000 × 400 W panels |
| Farm | 100 cohorts × 100 panels |
| Random seed | 42 |
| Calibration set | `riyadh_central_v2` |

The file declares all model defaults explicitly so a change to code defaults does not silently
change the documented study. Its weather is synthetic.

## Other maintained configurations

| File | Use |
| --- | --- |
| `configs/default.yaml` | Riyadh with live NASA POWER weather; also the dashboard's editable default |
| `configs/riyadh_dry_desert.yaml` | Live-weather dry-desert comparison |
| `configs/dammam_humid_desert.yaml` | Live-weather humid-desert comparison |
| `configs/pvdaq*_field_validation.yaml` | Frozen external field-validation site models |

## Sections

| Section | Controls |
| --- | --- |
| `simulation` | Inclusive time range, site timezone, run ID prefix |
| `site` | Name, coordinates, timezone, optional elevation |
| `weather` | Provider, fixture profile, cache, CSV mapping, missing-data policy |
| `pv_system` | Capacity, geometry, temperature model, inverter, DC/AC ratio, system losses |
| `farm` | Representative or cohort model and fleet size |
| `soiling` | Daily accumulation, dust events, floor, seed, optional dew cementation |
| `rainfall_cleaning` | Partial/full thresholds and restoration efficiencies |
| `bird_droppings` | Cohort event and loss assumptions |
| `reactive_cv` | Inspection, drone, observer, dispatch, and crew behavior |
| `coating` | Physics, water, deployment, and cost basis |
| `calibration` | Assumption-set label and parameter registry |
| `output`, `logging` | Artifact location, CSV precision, log level |

Field definitions and numeric constraints are enforced by `solarclean.config.models`; the YAML
files are the source for study values.

## Cross-section constraints

- `site.timezone` must equal `simulation.target_timezone`.
- The UTC offsets on `simulation.start` and `simulation.end` must match that timezone.
- `pv_system.panel_count` must equal `farm.total_panels`.
- `pv_system.panel_capacity_w` must equal `farm.panel_capacity_w`.
- In cohort mode, `cohort_count × panels_per_cohort` must equal `total_panels`.
- Coating deployment and cost lifecycle values must match.
- A retrofit requires demonstrated field application.

## Make a study configuration

Copy the canonical file, give it a distinct `run_id_prefix`, and change only the assumptions needed
for the study:

```powershell
Copy-Item configs/offline_fixture_full_year.yaml configs/my-study.yaml
python -m solarclean.cli.main validate-weather --config configs/my-study.yaml
```

Every run writes the fully resolved model as `config_resolved.yaml`. Archive that file with results.
