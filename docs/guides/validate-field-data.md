# Validate against measured production

The field-validation harness compares simulated daily AC energy with measured plant production
using a tuning/holdout split.

## Prepare measured production

The measured CSV accepts hourly or daily rows:

| Column | Required | Meaning |
| --- | --- | --- |
| `timestamp` | Yes | ISO 8601 timestamp with a UTC offset |
| `measured_ac_energy_kwh` | Yes | Non-negative interval AC energy in kWh |
| `cleaning_event` | No | `1` if any manual cleaning occurred in the interval |

Weather is a separate input selected by the project configuration. At least 30 local calendar days
must overlap.

Do not encode logger, meter, or inverter outages as zero production. Omit those days unless the
simulation explicitly models the corresponding availability loss. The dataset converter can
exclude days with irradiance but no positive AC energy:

```powershell
python scripts/convert_field_dataset.py --help
```

## Freeze the protocol

Before examining holdout results:

1. Define the tuning period and a later holdout start date.
2. Record data-quality exclusions mechanically.
3. Freeze system metadata and any parameters fitted on tuning data.
4. Set acceptance gates.
5. Run the holdout once and report all metrics, including failures.

Using holdout data to select parameters invalidates the holdout.

## Run the harness

```powershell
python -m solarclean.cli.main validate-field `
  --config configs/pvdaq34_field_validation.yaml `
  --measured-csv data/external/pvdaq_system_34_2019_h1_measured.csv `
  --holdout-start 2019-05-01
```

The command writes `field_validation_report.json` and `field_validation_report.md` under the
configured output directory. These field configurations use NASA POWER and may require network
access when their caches are absent.

The included three-site results, protocol, and limitations are summarized in
[field-validation results](../validation/field-results.md). Reproduction commands are in
[reproduce validation](../validation/reproducibility.md).
