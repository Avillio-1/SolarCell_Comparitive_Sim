# Phase 1-3 Assumptions

## PV System

- Default site is Riyadh: latitude `24.7136`, longitude `46.6753`, timezone `Asia/Riyadh`.
- Default system is 10,000 panels at 400 W DC each, approximately 4 MW DC.
- Fixed tilt defaults to 25 degrees and azimuth defaults to 180 degrees.
- The clean model uses explicit pvlib PVWatts functions with configurable inverter efficiency, DC/AC ratio, temperature coefficient, and module temperature model. The adapter does not expose raw pvlib objects to domain or application callers.

## Soiling

- The Kimber-style soiling model is empirical and configuration-driven.
- Default daily soiling, heavy dust event probability, event loss ranges, and rainfall cleaning thresholds are provisional.
- Defaults are not claimed as validated Saudi calibration values.

## Rainfall Cleaning

- Rainfall can produce no effective cleaning, partial cleaning, or strong cleaning.
- Cleaning restores a fraction of the gap between the current dirty state and the configured clean state.
- Rainfall cannot make panels cleaner than the clean state.

## Bird Droppings

- Bird-dropping events are sparse, stochastic, localized at cohort level, and configuration-driven.
- Coverage and associated energy-loss fraction are tracked separately.
- The current model is not a detailed per-cell or bypass-diode electrical model.

## Weather

- NASA POWER retrieval depends on internet access and API availability.
- Fixture weather is deterministic and test-only.
- CSV weather is intended for future measured Riyadh station data.
