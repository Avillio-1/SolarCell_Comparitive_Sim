# Assumptions and limitations

Results are research estimates unless a study supplies measured site inputs and replaces
provisional assumptions.

| Area | Current basis | Main limitation |
| --- | --- | --- |
| Weather | Fixture, NASA POWER, or user CSV | Fixture is synthetic; satellite weather adds daily error |
| Clean PV | pvlib PVWatts with explicit loss chain | No snow or explicit shading; site metadata may be uncertain |
| Soiling and rain | Kimber-style empirical model with Saudi/literature ranges | No target-farm soiling station |
| Dust events | Seeded statistical events | Not a meteorological dust forecast |
| Bird contamination | Sparse cohort model | Frequency and electrical loss are assumed |
| Reactive CV | Statistical observer, capacity, queue, and crew model | No selected field detector, route study, or time-and-motion data |
| Coating | Paper-anchored optical, cooling, shedding, and dew mechanisms | Field application, lifetime, and Riyadh performance are unproven |
| Economics | Registry-backed tariffs and cost components | Offtake, logistics, quotes, financing, and lifetime remain provisional |

## Canonical fixture

`configs/offline_fixture_full_year.yaml` is the canonical documentation configuration because it
is deterministic and network-free. It must not be used as evidence of Riyadh weather, annual
yield, rain frequency, or strategy performance.

## Riyadh calibration

Published Rumah and Dhahran studies and Saudi dust climatology inform parameter ranges, but they
are not measurements from the target farm. Target-site reference-cell or production data are
required before soiling parameters can be called validated.

The energy value is especially decision-sensitive: a retail-offset tariff and a utility PPA value
can differ by several times. Rankings should be tested across the registered range.

## Reactive scenario

The observer's recall, false-positive rate, missed images, and severity error are generic
field-derated assumptions. Drone throughput, weather limits, crew throughput, water, and dispatch
thresholds require a selected operating design. Detection metrics use ground truth only for
offline evaluation; dispatch itself cannot access it.

## Coating scenario

The coating case draws on a KAUST-inspired research paper and treats optical performance as
relative coated-versus-uncoated behavior. Dew collection is weather-gated and reported as gross,
collectable, and actually collected water. A favorable-night result is not annualized across all
nights.

The modeled 400 °C treatment supports factory-preinstallation research, not field reapplication.
Collection infrastructure cost and water revenue are excluded unless explicitly supplied.

## Decision use

A reconciled run proves comparable inputs and consistent arithmetic. It does not prove that weak
parameters are correct. Before an operational decision:

- replace weather and soiling assumptions with site measurements;
- select and test the CV/drone/cleaning system;
- select a coating product and obtain field and cost evidence;
- define the offtake tariff, water logistics, finance, and project lifetime;
- rerun sensitivity and holdout validation.
