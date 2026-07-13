# Task 1: Add balance-of-system losses to the PV model

## Project context

- You are working in the repo `SolarCell_Comparitive_Sim` (Windows). It contains a Python
  3.11+ package named `solarclean` under `src/`, installed editable via pip.
- SolarClean-DT simulates a 10,000-panel PV farm in Riyadh and compares three
  dust-mitigation scenarios (baseline / reactive cleaning / coating) using NASA POWER
  weather, a pvlib PVWatts energy model, and an economics layer. Read `README.md` first.

## The problem you are fixing

The PV model in `src/solarclean/infrastructure/pvlib_adapter/pvwatts.py` computes:
solar position → plane-of-array irradiance → cell temperature → PVWatts DC power →
inverter efficiency and clipping. It applies **no balance-of-system losses at all** —
no wiring, mismatch, connections, nameplate, light-induced degradation (LID), or
availability losses. The PVWatts method (NREL, Dobos 2014, "PVWatts Version 5 Manual")
normally applies a lumped ~14% loss; this project models soiling separately and has no
shading or snow, but the remaining non-soiling losses (~9–10%) are missing. Every
absolute energy and revenue number in the project is therefore biased high by roughly
that amount. Your job is to add these losses as configurable parameters.

## Before you start, read these files

1. `src/solarclean/config/models.py` — find the `PVSystemConfig` pydantic model.
2. `src/solarclean/infrastructure/pvlib_adapter/pvwatts.py` — the whole file (~120 lines).
3. `configs/default.yaml` — the `pv_system:` block.
4. `data/calibration/parameter_registry.yaml` — read the first 2–3 parameter entries to
   learn the exact entry schema (field names and style). You will add entries in the
   same schema.
5. `tests/regression/` — skim to learn how golden regression tests store expected values,
   because you will need to update them.

## Steps

1. In `PVSystemConfig` (in `src/solarclean/config/models.py`), add six new float fields,
   each with `ge=0, le=0.2` validation and these exact names and defaults:
   - `loss_wiring_fraction` default `0.02`
   - `loss_mismatch_fraction` default `0.02`
   - `loss_connections_fraction` default `0.005`
   - `loss_nameplate_fraction` default `0.01`
   - `loss_lid_fraction` default `0.015`
   - `loss_availability_fraction` default `0.03`
2. Add a computed property on `PVSystemConfig` named `combined_system_loss_multiplier`
   that returns the product of `(1 - loss)` over all six fields. With the defaults this
   is 0.98 × 0.98 × 0.995 × 0.99 × 0.985 × 0.97 ≈ **0.9039**. Match the typing and
   docstring style of the existing model code (mypy runs in strict mode on `src/`).
3. In `pvwatts.py`, multiply the DC power by this multiplier **after** the
   `pvlib.pvsystem.pvwatts_dc(...)` call and **before** the
   `pvlib.inverter.pvwatts(...)` call. Placement matters: losses must reduce DC power
   before inverter clipping so that clipping behaves correctly with the 1.15 DC/AC
   ratio. Do not apply the multiplier anywhere else (it must not be applied twice).
4. Add the six values plus the combined multiplier to the model `metadata` dict that
   `pvwatts.py` already builds (follow the existing key naming style).
5. In `configs/default.yaml`, add the six fields with the same default values under the
   `pv_system:` block, with a one-line comment stating they are PVWatts-style
   non-soiling losses (soiling is modeled separately; shading/snow assumed zero).
6. In `data/calibration/parameter_registry.yaml`, append six new parameter entries, one
   per loss, copying the existing entry schema exactly (same field names:
   `name`, `configuration_path`, `category`, `central_value`, `low_value`, `high_value`,
   `unit`, `source`, `evidence_type`, `source_geography_and_climate`,
   `applicability_to_saudi_conditions`, `confidence`, `status`, `rationale`,
   `limitations`, `responsible_module_or_owner`). Use:
   - category: `pv_system`
   - low/high ranges: wiring 0.01–0.03, mismatch 0.01–0.03, connections 0.003–0.01,
     nameplate 0.0–0.02, lid 0.005–0.03, availability 0.01–0.06
   - unit: `fraction`
   - source: `NREL PVWatts Version 5 Manual (Dobos 2014), https://www.nrel.gov/docs/fy14osti/62641.pdf`
   - evidence_type: `literature`, confidence: `medium`, status: `provisional`
   - rationale/limitations: brief, in the style of neighboring entries; note that
     soiling, shading, and snow are intentionally excluded from these losses.
7. Record the before/after effect: run
   `solarclean run-clean --config configs/default.yaml` (or the equivalent pytest-level
   entry if the CLI needs network and no weather cache is present — a cache exists under
   `data/cache/weather`, so this should run offline). Note annual clean energy before
   your change (from the most recent `outputs/default-riyadh-*` run:
   7,458,701 kWh) and after (expected ≈ 6.74M kWh, i.e. old × ~0.904).
8. Run the full test suite. Golden regression tests and any test asserting absolute
   energy values will fail — that is expected. Update the golden/expected values
   following whatever update mechanism `tests/regression/` already uses (look for a
   documented regeneration flow or fixture files before editing numbers by hand).
   Do NOT loosen tolerances to make tests pass; update expected values.
9. Add a new unit test file `tests/unit/test_system_losses.py` covering:
   - `combined_system_loss_multiplier` equals the expected product for the defaults.
   - Setting all six losses to 0 reproduces the previous (no-loss) DC power exactly.
   - The multiplier is applied before the inverter (e.g., with losses, high-irradiance
     hours that previously clipped produce less clipping or equal AC ≤ previous AC).
10. Create a short ADR at `docs/adr/ADR-012-pv-system-losses.md` (check `docs/adr/` first;
    if ADR-012 exists, use the next free number) in the style of the existing ADRs:
    context (losses were absent), decision (six explicit multiplicative losses, applied
    pre-inverter), consequences (all absolute outputs drop ~10%; registry-driven
    sensitivity now covers them).
11. Update the `## Limitations And Provisional Assumptions` bullet in `README.md` that
    describes the PV model so it mentions the configurable non-soiling loss chain.

## Constraints

- Touch ONLY the files listed below. No refactors, renames, or reformatting of
  unrelated code.
- Keep new config fields optional-with-defaults so `tests/config_factory.py` and any
  existing YAML keep working unchanged.
- If anything in this brief contradicts what you find in the code, STOP and report the
  discrepancy in your final message instead of guessing.
- Do not commit or push. Leave changes in the working tree.
- Do not create accounts or sign up for API keys.

## Files you may create or modify

- `src/solarclean/config/models.py` (PVSystemConfig only)
- `src/solarclean/infrastructure/pvlib_adapter/pvwatts.py`
- `configs/default.yaml` (pv_system block only)
- `data/calibration/parameter_registry.yaml` (append entries only)
- `tests/unit/test_system_losses.py` (new)
- Golden/expected data under `tests/` that your change legitimately invalidates
- `docs/adr/ADR-012-pv-system-losses.md` (new), `README.md` (one bullet)

## Verification (all must pass before you finish)

```
python -m pytest -q
python -m ruff format <only the files you changed>
python -m ruff check .
python -m mypy src
```

If `import solarclean` fails, first run: `python -m pip install -e ".[dev]"`

## Final report

List: files changed; annual clean energy before vs after (exact numbers) and the
percentage drop; which golden values you regenerated and how; test/lint/type results;
anything you could not complete.
