# External field-validation data

This directory keeps only the compact, processed daily CSV inputs needed to
reproduce the documented field-validation analyses offline. Raw PVDAQ downloads,
NASA POWER caches, and generated validation-output directories are intentionally
excluded from Git.

## Sources and attribution

- NREL PVDAQ public datasets: Open Energy Data Initiative (OEDI), DOI
  [10.25984/1846021](https://doi.org/10.25984/1846021). Cite the dataset as
  described on its [OEDI catalog page](https://data.openei.org/submissions/4568).
- NASA POWER weather data: obtained from the NASA Langley Research Center POWER
  project. Follow the [POWER referencing guide](https://power.larc.nasa.gov/docs/referencing/)
  and record the service version and access date when regenerating a cache.

The processed CSVs are derived from the public PVDAQ data. They are not original
project measurements.

## Tracked processed inputs

| File | SHA-256 |
| --- | --- |
| `pvdaq_system_34_2019_jan_feb_measured.csv` | `1a2a2b68f2b3b047a1b0878469478c1cadbd86d0955f5b91e56e87a83ac90664` |
| `pvdaq_system_34_2019_h1_measured.csv` | `9f8984fe5e653496b6ebe2b01c3a18387570d9982839f62995a97525dcd64cb9` |
| `pvdaq_system_34_2019_tuning_janapr.csv` | `18cd554536468f8e2dd611930439d397bfe01f56b5b1644853fbc6e66aedb599` |
| `pvdaq_system_1403_2016_h1_measured.csv` | `17fe9974d580833bc685fdfbec2b46d001e6d2c83c2b687cf15e9523cbe48ed7` |
| `pvdaq_system_1403_2016_tuning_janapr.csv` | `063eda646a2d13b15cdfd6656d175a3bc395366129581077f4f6673cf046979f` |
| `pvdaq_system_1429_2017_h1_measured.csv` | `ecc547dc55731bbeb6e1d7634e9112378e21553ec3c57c7a7d861a1599349a85` |
| `pvdaq_system_1429_2017_tuning_janapr.csv` | `8ec0fbb620ab443e213c2a8783d711ff4e25c64b125442e7191a5a3abca62b8d` |

## Reproduction

Use `scripts/download_pvdaq_days.py` to fetch raw PVDAQ day files and
`scripts/convert_field_dataset.py` to recreate the processed daily inputs. The
site-specific commands and validation protocol are documented in:

- `docs/audits/pvdaq34_field_validation_2026-07-18.md`
- `docs/audits/rtc_multi_site_field_validation.md`

Running `validate-field` recreates the ignored `*_nasa_cache/` and
`*_validation_outputs/` directories. Preserve release-grade results outside the
source repository (for example, in a GitHub Release or research-data archive)
and record their checksums in the corresponding audit document.
