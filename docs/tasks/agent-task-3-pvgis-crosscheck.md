# Task 3: Independent irradiance cross-check against PVGIS (script only)

## Project context

- You are working in the repo `SolarCell_Comparitive_Sim` (Windows). It contains a Python
  3.11+ package named `solarclean` under `src/`, installed editable via pip.
- SolarClean-DT simulates a 10,000-panel PV farm in Riyadh (lat 24.7136, lon 46.6753).
  Its only weather source is NASA POWER (satellite/reanalysis-derived). Its clean-energy
  model is pvlib PVWatts in
  `src/solarclean/infrastructure/pvlib_adapter/pvwatts.py`. Read `README.md` first.

## The problem you are fixing

All energy results rest on NASA POWER irradiance, which is model-derived and has known
regional biases, especially in dusty regions. Nobody has checked it against an
independent source. Your job: fetch the European Commission PVGIS TMY (typical
meteorological year) dataset for the same coordinates — a free, no-key public API built
from a different satellite database (SARAH) — run the project's own PVWatts model on it,
and report how far NASA-based irradiance and yield deviate from PVGIS-based values.
This turns "we trust the weather input" from a guess into a measured number.

This is a **diagnostic script + report only**. Do NOT build a new weather provider, do
NOT modify anything under `src/`.

## Before you start, read these files

1. `src/solarclean/domain/environment/weather.py` — the `WeatherDataset` contract
   (constructor, required hourly columns, metadata fields).
2. `src/solarclean/infrastructure/weather/nasa_power.py` — how a normalized
   `WeatherDataset` is constructed after fetching (mirror this construction), and what
   `metadata["coordinates"]` must contain (the PVWatts adapter reads
   `latitude`, `longitude`, `elevation_m` from it).
3. `src/solarclean/infrastructure/pvlib_adapter/pvwatts.py` — the `PVWattsPowerModel`
   API you will call (`calculate_hourly(weather, system)`).
4. `src/solarclean/application/use_cases.py` and `src/solarclean/config/loader.py` —
   how a config is loaded and how the run-clean flow obtains weather, so you can load
   the NASA dataset through the project's own provider path (with
   `weather.cache_enabled: true` and the existing cache under `data/cache/weather`,
   this needs no network).
5. `configs/default.yaml` — site coordinates and `pv_system` parameters.

## Steps

1. Create `scripts/crosscheck_pvgis_irradiance.py`. Structure it as importable
   functions plus a `main()` under `if __name__ == "__main__":` (functions will be
   unit tested). The script does the following:
2. **Fetch PVGIS TMY** for the site coordinates from
   `https://re.jrc.ec.europa.eu/api/v5_3/tmy?lat=24.7136&lon=46.6753&outputformat=json`
   (if v5_3 returns an error, fall back to the same path with `v5_2`). Use `httpx`
   (already a dependency). Cache the raw JSON to
   `data/cache/weather_crosscheck/pvgis_tmy_24.7136_46.6753.json` and skip the fetch
   when the file exists. Read coordinates from the loaded config — do not hardcode them
   anywhere except the fallback default.
3. **Normalize** the TMY hourly records into a pandas DataFrame with the project's
   canonical columns. The PVGIS TMY hourly fields are expected to be named
   `G(h)` (global horizontal W/m²), `Gb(n)` (direct normal W/m²), `Gd(h)` (diffuse
   horizontal W/m²), `T2m` (°C), `WS10m` (m/s), `RH` (%). VERIFY the actual key names
   from the response before mapping; if they differ, adapt and note it in your report.
   Map them to: `ghi_w_m2`, `dni_w_m2`, `dhi_w_m2`, `temp_air_c`, `wind_speed_m_s`,
   `relative_humidity_pct`. Add a `precipitation_mm` column of zeros ONLY if
   `WeatherDataset` requires it (TMY has no precipitation; this script never runs the
   soiling model, so zeros are acceptable here and must be documented in the report).
   PVGIS TMY timestamps are UTC hours drawn from different historical years per month:
   build a synthetic hourly index for one nominal year (use 2025), localized to UTC then
   converted to `Asia/Riyadh`, matching record order month by month.
4. **Build a `WeatherDataset`** from that DataFrame the same way `nasa_power.py` does,
   with `metadata["coordinates"]` populated and a metadata note
   `"source": "pvgis_tmy_v5"`.
5. **Load the NASA dataset** for 2025 through the project's own config + provider path
   (cache makes this offline). Do not parse the cache files by hand.
6. **Run `PVWattsPowerModel.calculate_hourly`** on both datasets with the
   `pv_system` config from `configs/default.yaml`.
7. **Write the comparison report** to `outputs/pvgis_crosscheck/` (create the dir):
   - `pvgis_crosscheck.json` and `pvgis_crosscheck.md` containing:
     - Monthly GHI sums in kWh/m² for both sources, and percent difference per month.
     - Annual GHI kWh/m² both sources + percent difference.
     - Annual clean AC energy (kWh) and specific yield (kWh per kWp, i.e. annual energy
       / 4000 kWp) for both, + percent difference.
     - An interpretation block stating, verbatim in substance: PVGIS TMY is a
       climatological typical year while the NASA dataset is the actual year 2025, so
       monthly differences up to ~±10% are expected from weather alone; annual
       differences beyond ~7% suggest a systematic irradiance bias worth investigating;
       this comparison bounds weather-input uncertainty but is not a ground-truth
       validation (neither source is a ground station).
8. **Unit test** `tests/unit/test_pvgis_crosscheck_script.py`: embed a tiny synthetic
   PVGIS-style JSON (6–24 hourly records) as a Python dict in the test, load the script
   module via `importlib.util.spec_from_file_location`, and assert the normalization
   function produces the canonical columns with correct values and a tz-aware index.
   No network in tests. If you add a live-fetch test, gate it behind env var
   `SOLARCLEAN_RUN_NETWORK_TESTS=1` (existing pattern, see README) and mark it with the
   existing `integration` pytest marker.

## Constraints

- Do NOT modify anything under `src/`. This task is a script + test + generated report.
- Do NOT add a `pvgis` option to the weather config or provider factory — that is
  intentionally out of scope (no precipitation data → it must not be usable for soiling
  runs).
- Do not change golden regression data. If existing tests fail, your change is wrong.
- Keep the script ruff-clean (ruff checks the whole repo).
- If anything in this brief contradicts what you find in the code, STOP and report the
  discrepancy instead of guessing.
- Do not commit or push. Do not create accounts or API keys (PVGIS needs no key).

## Files you may create or modify

- `scripts/crosscheck_pvgis_irradiance.py` (new)
- `tests/unit/test_pvgis_crosscheck_script.py` (new)
- Generated artifacts under `outputs/pvgis_crosscheck/` and
  `data/cache/weather_crosscheck/` (do not add these to git)

## Verification (all must pass before you finish)

```
python -m pytest -q
python -m ruff format <only the files you changed>
python -m ruff check .
python -m mypy src
```

If `import solarclean` fails, first run: `python -m pip install -e ".[dev]"`

Then, if network is available, run the script once end-to-end:
`python scripts/crosscheck_pvgis_irradiance.py` and confirm both report files appear.
If network is unavailable, the deliverable stands on the offline unit test; say so.

## Final report

List: files changed; whether the live PVGIS fetch worked; the annual GHI % difference
and specific-yield % difference (if run); the month with the largest deviation;
test/lint/type results; anything you could not complete.
