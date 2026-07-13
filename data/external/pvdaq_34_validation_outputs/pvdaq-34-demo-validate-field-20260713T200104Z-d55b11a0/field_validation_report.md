# Field Validation Report

Site: PVDAQ 34 - Andre Agassi Preparatory Academy Building A  
Period: 2019-01-01 through 2019-02-28  
Holdout starts: 2019-02-15

| Stage | Days | MAE (kWh) | MAE (%) | RMSE (kWh) | RMSE (%) | MBE (kWh) | MBE (%) | R² |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Overall | 59 | 217.831171 | 73.779927 | 322.846375 | 109.348822 | 202.834127 | 68.700393 | -1.185997 |
| Clean days (event day through +2) | 16 | 246.289765 | 178.379957 | 367.070367 | 265.857562 | 222.329349 | 161.026179 | -5.346376 |
| Holdout | 14 | 625.778001 | n/a | 638.798011 | n/a | 625.778001 | n/a | 0.000000 |

## Decline slopes

Dry spells: 2; days used: 28; simulated mean PI slope/day: -0.000870; measured: -0.023420; ratio: 0.037136.

## Recovery

Events used: 6; simulated mean step: -239.169150 kWh; measured mean step: -190.825000 kWh.

## Interpretation warning

Metrics on the tuning period are not evidence of predictive accuracy. Only metrics for the untouched holdout period assess predictive performance.
