# Reproduce validation

Reproduction requires the resolved configuration, code revision, parameter registry, input data,
weather checksum, and random seed.

## Deterministic internal validation

```powershell
python -m solarclean.cli.main validate-weather `
  --config configs/offline_fixture_full_year.yaml
python -m solarclean.cli.main validate-phase-3-5 `
  --config configs/offline_fixture_full_year.yaml
python -m pytest -q
```

These commands require no network. The fixture validates software behavior, not field accuracy.

## Re-run the three holdouts

The processed production CSVs are tracked under `data/external/`. NASA POWER weather may require
network access when its cache is absent.

```powershell
python -m solarclean.cli.main validate-field `
  --config configs/pvdaq34_field_validation.yaml `
  --measured-csv data/external/pvdaq_system_34_2019_h1_measured.csv `
  --holdout-start 2019-05-01

python -m solarclean.cli.main validate-field `
  --config configs/pvdaq1429_field_validation.yaml `
  --measured-csv data/external/pvdaq_system_1429_2017_h1_measured.csv `
  --holdout-start 2017-05-01

python -m solarclean.cli.main validate-field `
  --config configs/pvdaq1403_field_validation.yaml `
  --measured-csv data/external/pvdaq_system_1403_2016_h1_measured.csv `
  --holdout-start 2016-05-01
```

The original acceptance decision is based on the frozen metrics in
[field-validation results](field-results.md), not on repeatedly tuning and rerunning the same
holdout.

## Rebuild processed RTC inputs

Raw NREL PVDAQ files are not committed. Download them from the public OEDI bucket:

```powershell
python scripts/download_pvdaq_days.py --system-id 1403 --year 2016 --months 1-6 `
  --output data/external/pvdaq_system_1403_2016_h1_raw
python scripts/download_pvdaq_days.py --system-id 1429 --year 2017 --months 1-6 `
  --output data/external/pvdaq_system_1429_2017_h1_raw
```

Convert every month directory with the recorded channels. Example for system 1403:

```powershell
python scripts/convert_field_dataset.py `
  data/external/pvdaq_system_1403_2016_h1_raw/month=01 `
  data/external/pvdaq_system_1403_2016_h1_raw/month=02 `
  data/external/pvdaq_system_1403_2016_h1_raw/month=03 `
  data/external/pvdaq_system_1403_2016_h1_raw/month=04 `
  data/external/pvdaq_system_1403_2016_h1_raw/month=05 `
  data/external/pvdaq_system_1403_2016_h1_raw/month=06 `
  --output data/external/pvdaq_system_1403_2016_h1_measured.csv `
  --timezone America/New_York `
  --power-column inv1_ac_power__4207 `
  --power-column inv2_ac_power__4213 `
  --irradiance-column poa_irradiance__4214 `
  --minimum-coverage-hours 18
```

System 1429 uses `America/Denver`, power channels `inv1_ac_power__4917` and
`inv2_ac_power__4923`, and irradiance channel `poa_irradiance__4924`.

Checksums and attribution for tracked inputs are in `data/external/README.md`. Store release-grade
generated reports in an external research archive and record their checksums.
