# SolarClean-DT

SolarClean-DT is a comparative digital-twin simulator for evaluating photovoltaic dust-mitigation strategies for a 10,000-panel utility solar farm operating in Saudi Arabia.

It compares no intervention, reactive computer-vision drone inspection with human cleaning, and a proactive KAUST-inspired self-cleaning coating under the same weather and contamination conditions.
The current implementation is limited to:

- Phase 1: clean PV production using Riyadh-compatible hourly weather.
- Phase 2: no-intervention baseline soiling with rainfall cleaning.
- Phase 3: cohort-based representation of exactly 10,000 panels.
- Phase 3.5: validation, reproducibility, event-tape, calibration-preset, golden-regression, and profiling infrastructure.
- T1: frozen shared scenario contracts for future parallel reactive, coating, economics, analytics, and dashboard development.
- T2: provisional reactive CV inspection and targeted cleaning strategy.
- T3: provisional self-cleaning coating strategy and cost basis.
- T4/T5: common economics engine backed by the calibration parameter registry.
- T6: three-scenario comparison, reconciliation, ranking, recommendation, and export package.
- T7: Monte Carlo, one-way/two-way sensitivity, and break-even analysis.
- T8/T9: web dashboard over the T6/T7 use cases (run/deploy instructions in `docs/dashboard_user_guide.md`).

Not implemented yet: optimization, databases, Docker, and managed cloud deployment. The local
dashboard supports optional single-token HTTP Basic authentication; see
`docs/dashboard_user_guide.md` before exposing it beyond localhost.

Calibration status: soiling, dust, rainfall, coating, CV, and economics parameters are anchored to named published sources in `data/calibration/parameter_registry.yaml` (see `docs/calibration/source_bibliography.md`), and the simulation framework has passed real-data holdout validation at three NREL PVDAQ sites spanning three climates — system 34 (Las Vegas, hot desert: MAE 8.4%, MBE −5.4%), system 1429 (Albuquerque, semi-arid: MAE 9.0%, MBE −6.6%, zero fitted parameters), and system 1403 (Cocoa FL, humid subtropical: MAE 9.4%, MBE +2.8%) — all against pre-registered acceptance gates (see `docs/audits/pvdaq34_field_validation_2026-07-18.md` and `docs/audits/rtc_multi_site_field_validation.md`). Riyadh-specific values remain provisional until the target farm's own measurements exist, so rankings should be read together with the sensitivity and evidence-quality outputs.

## Architecture Summary

SolarClean-DT is a modular monolith using clean/hexagonal boundaries:

```text
CLI
  -> application use cases
    -> domain and simulation engine
      <- infrastructure adapters
```

Domain code defines provider-independent weather, PV, contamination, farm, and simulation contracts. NASA POWER, CSV weather, fixture weather, pvlib PVWatts, output writing, and plotting live in infrastructure adapters.

T1 adds a frozen `MitigationStrategy` contract and `ScenarioSimulationEngine` so future baseline, reactive CV, and coating strategies can share one annual daily loop. Shared outputs use `DailyScenarioResult`, `AnnualScenarioResult`, `DomainEvent`, and `OperationalQuantities`. Scenario-specific fields must be stored under result `extensions`.

## Windows PowerShell Installation

```powershell
cd C:\path\to\SolarCell_Comparitive_Sim
python -m pip install -e ".[dev,dashboard]"
```

## macOS/Linux Installation

```bash
cd /path/to/SolarCell_Comparitive_Sim
python3 -m pip install -e ".[dev,dashboard]"
```

## CLI Commands

Fetch and normalize weather:

```powershell
solarclean fetch-weather --config configs/default.yaml
```

Run clean PV production:

```powershell
solarclean run-clean --config configs/default.yaml
```

Run the no-intervention baseline with cohort farm output:

```powershell
solarclean run-baseline --config configs/default.yaml
```

Run the reconciled baseline/reactive/coating comparison:

```powershell
solarclean compare-all-scenarios --config configs/default.yaml
```

Validate weather only:

```powershell
solarclean validate-weather --config configs/default.yaml
```

Run Phase 3.5 validation and reports:

```powershell
solarclean validate-phase-3-5 --config configs/default.yaml
```

Profile a full-year run:

```powershell
solarclean profile-full-year --config configs/default.yaml
```

## NASA POWER Weather

`configs/default.yaml` is the sole runtime configuration and uses NASA POWER by default for Riyadh:

```yaml
weather:
  provider: nasa_power
  cache_enabled: true
  cache_directory: data/cache/weather
```

The adapter requests UTC hourly data and converts timestamps to `Asia/Riyadh`. It caches raw JSON and normalized canonical CSV/metadata files under `data/cache/weather`, so repeated runs can use cached data without additional API calls. The cache key includes a normalization-schema version so unit-conversion fixes cannot reuse stale normalized data.

## Cached Data Runs

After a successful NASA fetch, keep `weather.cache_enabled: true` and rerun any CLI command. The provider checks the request checksum and loads the normalized cache when it matches the requested site, time range, variables, and provider.

## Offline Tests

Tests derive deterministic fixture configurations programmatically from the immutable packaged
Riyadh factory preset through `tests/config_factory.py`. They do not inherit dashboard edits to
`configs/default.yaml`; the fixtures are test-only and are not scientifically representative data.

## Local Riyadh CSV Replacement

To replace NASA POWER with measured station data, edit the `weather` section in `configs/default.yaml`:

```yaml
weather:
  provider: csv
  local_csv_path: data/local_weather/riyadh_weather_example.csv
  timestamp_column: timestamp
  column_mapping:
    ghi: ghi_w_m2
    dni: dni_w_m2
    dhi: dhi_w_m2
    temp_c: temp_air_c
    wind_m_s: wind_speed_m_s
    rh_pct: relative_humidity_pct
    precip_mm: precipitation_mm
```

CSV timestamps must include timezone offsets. The normalized output must provide `ghi_w_m2`, `dni_w_m2`, `dhi_w_m2`, `temp_air_c`, `wind_speed_m_s`, `relative_humidity_pct`, and `precipitation_mm`.

## Outputs

Each command creates `outputs/<run_id>/` containing some or all of:

- `config_resolved.yaml`
- `metadata.json`
- `weather_hourly.csv`
- `clean_energy_hourly.csv`
- `daily_clean_energy.csv`
- `daily_results.csv`
- `cohort_daily_results.csv`
- `events.csv`
- `summary.json`
- `summary.txt`
- `diagnostic_plot.png`
- `phase35_weather_report.json`
- `phase35_energy_report.json`
- `phase35_farm_equivalence_report.json`
- `phase35_event_tape.json`
- `phase35_performance_report.json`
- `phase35_summary.json`
- `scenario_daily_results.csv`
- `scenario_events.csv`
- `scenario_summary.json`
- `event_tape.json`
- `comparison_metadata.json`
- `scenario_daily_summary.csv`
- `scenario_annual_summary.csv`
- `scenario_cost_summary.csv`
- `scenario_ranking.json`
- `recommendation.json`
- `reconciliation_report.json`
- `comparison_daily_energy.png`
- `comparison_cumulative_energy.png`
- `comparison_annual_kpi_breakdown.png`

Column names include units where practical. CSV is used instead of Parquet to keep Phase 1-3 dependencies lean.

The T6 comparison package is documented in `docs/data_contracts/t6_comparison.md`.

## Testing And Quality

```powershell
python -m pytest -q
python -m pytest --cov=solarclean --cov-report=term-missing
python -m ruff format --check .
python -m ruff check .
python -m mypy src
```

Live NASA POWER tests are skipped by default. Enable them explicitly:

```powershell
$env:SOLARCLEAN_RUN_NETWORK_TESTS = "1"
python -m pytest tests/integration/test_nasa_power_live.py -q
```

### Continuous Integration

Every push to `main` and every pull request runs the same quality gate in GitHub Actions
(`.github/workflows/ci.yml`): `ruff format --check`, `ruff check`, `mypy src`, and the
offline pytest suite, on Ubuntu (Python 3.11 and 3.12) and Windows (Python 3.12). CI also builds
a wheel and verifies that the dashboard templates, scripts, styles, fonts, and bundled default
configuration are present, preventing an install that starts without its web assets.
A pull request should not be merged with a red check; run the commands above locally to
reproduce any CI failure.

## Limitations And Provisional Assumptions

- Soiling rates, rainfall thresholds, dust-event distributions, bird-dropping rates, and loss mapping are provisional assumptions awaiting site calibration.
- Low, medium, and high Riyadh soiling presets are clearly labelled provisional and must not be treated as validated Saudi measurements.
- The PV model uses an initial pvlib PVWatts path with configurable fixed tilt, azimuth, inverter efficiency, DC/AC ratio, temperature coefficient, and a multiplicative non-soiling loss chain.
- The bird-dropping model is sparse, stochastic, and cohort-level only. It is not a detailed bypass-diode or per-cell electrical model.
- The offline fixture is deterministic test data.
- Real NASA POWER retrieval depends on network access and API availability.

## Phase 3.5 Event Tape

Phase 3.5 uses an immutable exogenous event tape for dust variation, heavy dust events, bird events, and cohort variation. The tape is generated from deterministic RNG streams and serialized as JSON so future scenarios can share the same environmental/contamination events.

## T1 Shared Scenario Contracts

The frozen T1 contracts are documented in:

- `docs/data_contracts/scenario_contracts.md`
- `docs/architecture/t1_shared_interfaces.md`
- `docs/integration/t1_parallel_development.md`
- `docs/adr/ADR-009-t1-shared-contract-freeze.md`

Future scenario modules must implement `MitigationStrategy` and run through `ScenarioSimulationEngine`; they must not duplicate the annual loop or add scenario-name conditionals to the shared engine.
