# Field-validation results

The framework was compared with held-out production from three NREL PVDAQ systems spanning arid,
semi-arid, and humid climates.

| PVDAQ system | Location and climate | Holdout | Days | MAE | MBE | R² | Fitted parameters |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 34 | Las Vegas, hot desert | 2019-05-01 to 2019-06-30 | 61 | 8.42% | −5.41% | 0.388 | 1 |
| 1429 | Albuquerque, semi-arid | 2017-05-01 to 2017-06-30 | 58 | 9.03% | −6.63% | 0.383 | 0 |
| 1403 | Cocoa, humid subtropical | 2016-05-01 to 2016-06-30 | 59 | 9.43% | +2.80% | 0.766 | 1 |

All met the pre-registered gates of MAE below 15%, absolute MBE below 10%, and R² above zero.

## Site models

- System 34: 611 × 240 W modules, 146.64 kW DC, fixed 11.2° tilt, 135 kW inverter. The dry
  soiling rate was fitted to `0.0033/day` on January–April data.
- Systems 1403 and 1429: nominally identical 5.94 kW RTC systems, 22 × 270 W modules, fixed 35°
  tilt. System 1403 fitted `0.0015/day`; system 1429 retained the literature value
  `0.0005/day`.
- Stochastic dust storms and bird events were disabled so the holdouts tested clean PV,
  deterministic soiling, and rain recovery.

The fitted rates remained within the registry's published arid-site range.

## Data quality

The original system-34 demonstration failed because a dead meter was represented as zero
production while the irradiance sensor recorded full sun. The corrected protocol treats these
days as missing availability data. RTC data also exclude short partial-logging days and require all
requested inverter channels before summing site power.

These rules were applied mechanically by `scripts/convert_field_dataset.py` and recorded before
the holdouts were examined.

## Interpretation

The two dry-season holdouts have modest R² because daily measured production varies little under
clear skies, making satellite-weather noise dominant after variance normalization. Their MAE and
MBE remain within the gates. The humid-site holdout has more daily weather variation and a higher
R².

For system 34, the full-period simulated-to-measured dry-spell decline-slope ratio was `1.0002`.
Other full-period slope diagnostics were affected by snow or non-soiling transients and are
reported as diagnostics rather than acceptance gates.

## Limits

- Each site covers one half-year.
- Two systems are small research arrays.
- NASA POWER rather than on-site irradiance drives the simulations.
- Maintenance logs were unavailable.
- The Albuquerque model has no snow physics.
- None of the sites measures Riyadh or the intended target farm.

The tracked configurations and processed data are listed in
[reproduce validation](reproducibility.md).
