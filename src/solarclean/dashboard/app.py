"""T8 dashboard: a thin web layer over the existing application use cases.

Design rule (see docs/dashboard_user_guide.md): this module may load configs,
start use cases, and read artifact files. It must not calculate energy, cost,
or statistics. If a screen needs a number that no use case writes, the fix is
a backend change, not a formula here. The only transformations allowed are
reshaping stored values (picking columns, grouping rows) and display
formatting (rounding, thousands separators, best-of-row highlighting, and the
display-only delta between two already-stored run values). Display deltas are
never persisted or fed back into simulation, economics, or ranking.

Daily detection and coating extensions are charted exactly as stored. In
particular, this layer must not sum daily TP/FP/FN/TN fields into annual
confusion totals; annual detection facts require explicit backend annual
columns first. Coating service-life views likewise select stored age,
effectiveness, energy-effect, temperature, and water columns without adding
new scientific calculations.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import math
import os
import re
import secrets
import shutil
import stat
import tempfile
import time
import zipfile
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime
from datetime import time as datetime_time
from functools import lru_cache
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, model_validator
from timezonefinder import TimezoneFinder

from solarclean.application.comparison import CompareAllScenarios
from solarclean.application.dew_simulator import simulate_nighttime_dew
from solarclean.application.monte_carlo import MonteCarloExperiment
from solarclean.application.sensitivity import (
    BreakEvenExperiment,
    OneWaySensitivityExperiment,
    TwoWaySensitivityExperiment,
)
from solarclean.config.loader import load_config
from solarclean.config.models import SolarCleanConfig
from solarclean.dashboard import artifacts
from solarclean.dashboard.jobs import JOB_KINDS, Job, JobRegistry
from solarclean.domain.calibration.parameter_overrides import build_parameter_catalog
from solarclean.domain.calibration.registry import ParameterRegistry
from solarclean.domain.environment.weather import CANONICAL_WEATHER_COLUMNS, WeatherRequest
from solarclean.infrastructure.weather.cache import WeatherCache

_PACKAGE_DIR = Path(__file__).parent
_RIYADH_DEFAULT_CONFIG_PATH = _PACKAGE_DIR / "defaults" / "riyadh_default.yaml"

DEFAULT_CONFIG_NAME = "default.yaml"
DEFAULT_CONFIG_LABEL = "Default"


def _directory_from_env(variable: str, default: Path) -> Path:
    """Resolve a data directory, overridable for deployments.

    The dashboard historically assumed it was started from the repository root.
    For web deployments the configs/outputs locations can be pinned explicitly
    so the process working directory no longer matters.
    """
    raw = os.environ.get(variable, "").strip()
    return Path(raw) if raw else default


_REPO_ROOT = _directory_from_env("SOLARCLEAN_ROOT", Path.cwd())
_CONFIGS_DIR = _directory_from_env("SOLARCLEAN_CONFIGS_DIR", _REPO_ROOT / "configs")
_OUTPUTS_DIR = _directory_from_env("SOLARCLEAN_OUTPUTS_DIR", _REPO_ROOT / "outputs")
_CONFIG_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+\.yaml$")
_RUNS_PER_PAGE = 24
_ARTIFACT_PREVIEW_ROWS = 50
_ARTIFACT_JSON_PREVIEW_BYTES = 200_000

app = FastAPI(title="SolarClean-DT dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=_PACKAGE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=_PACKAGE_DIR / "templates")
# Finished sessions persist next to the runs they produced, so the sessions
# table survives server restarts.
jobs = JobRegistry(history_path=_OUTPUTS_DIR / ".dashboard_jobs.json")


def _basic_auth_password(header: str) -> str | None:
    """Extract the password of an HTTP Basic Authorization header, if any."""
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    _, _, password = decoded.partition(":")
    return password


@app.middleware("http")
async def _require_access_token(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Optional shared-token gate for non-localhost deployments.

    When SOLARCLEAN_DASHBOARD_TOKEN is set, every request must carry it as the
    password of an HTTP Basic Authorization header (any username). Unset (the
    workstation default) the dashboard remains open, as before. Read per
    request so tests and process managers can set it without an app rebuild.
    """
    token = os.environ.get("SOLARCLEAN_DASHBOARD_TOKEN", "").strip()
    if token:
        supplied = _basic_auth_password(request.headers.get("Authorization", ""))
        if supplied is None or not secrets.compare_digest(supplied, token):
            return Response(
                status_code=401,
                content="Authentication required",
                headers={"WWW-Authenticate": 'Basic realm="SolarClean-DT dashboard"'},
            )
    return await call_next(request)


def _display_number(value: str) -> str:
    """Trim stored full-precision values for on-screen reading.

    Display formatting only -- exports keep the exact figures, and the KPI
    section links to the CSV for anyone who needs all the decimals.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return "–"  # a stored blank (e.g. baseline payback) reads as "no value"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(number):  # e.g. baseline payback_years
        return "–"
    if number == 0:
        return "0"  # exact stored zero; "0.0000" implied spurious precision
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    return f"{number:,.2f}" if abs(number) >= 1 else f"{number:.4f}"


def _format_sar(value: str | float) -> str:
    """Currency display: thousands separators, negligible decimals dropped."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number):
        return "–"
    if abs(number) >= 100:
        return f"{number:,.0f}"
    if abs(number) >= 1:
        return f"{number:,.2f}"
    if number == 0:
        return "0"
    return f"{number:.4f}"


def _format_rate(value: str | float) -> str:
    """Compact decimal-rate display without hiding meaningful precision."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number):
        return "–"
    return f"{number:,.4f}".rstrip("0").rstrip(".")


templates.env.filters["display_number"] = _display_number
templates.env.filters["sar"] = _format_sar
templates.env.filters["rate"] = _format_rate


def _config_path(name: str) -> Path:
    if not _CONFIG_NAME_PATTERN.match(name):
        raise HTTPException(status_code=400, detail="Config name must be <letters-digits-_->.yaml")
    path = _CONFIGS_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"No config named {name} in configs/")
    return path


def _config_names() -> list[str]:
    """Names of the YAML configurations available for new dashboard runs."""
    return sorted(path.name for path in _CONFIGS_DIR.glob("*.yaml"))


def _config_periods(config_names: list[str]) -> dict[str, dict[str, str]]:
    """Date defaults used to populate the launch form for each valid config."""
    periods: dict[str, dict[str, str]] = {}
    for name in config_names:
        try:
            simulation = load_config(_config_path(name)).simulation
        except Exception:
            continue
        periods[name] = {
            "start_date": simulation.start.date().isoformat(),
            "end_date": simulation.end.date().isoformat(),
            "timezone": simulation.target_timezone,
        }
    return periods


def _run_dir_or_404(run_id: str) -> Path:
    run_dir = artifacts.resolve_run_dir(_OUTPUTS_DIR, run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found under outputs/")
    return run_dir


# Annual KPI fields shown on the comparison page, in reading order. These are
# stored T4/T6 outputs -- selection and labelling only, values pass through
# exactly as written in scenario_annual_summary.csv. The third element states
# the metric direction used to highlight the best stored value per row:
# "higher" (revenue/gain/benefit/ROI), "lower" (loss/cost/payback/LCOE), or
# None for operational quantities where "best" would be a judgement call.
_KPI_FIELDS: tuple[tuple[str, str, str | None], ...] = (
    ("Annual AC energy (kWh)", "annual_actual_energy_kwh", "higher"),
    ("Energy loss vs clean (%)", "annual_energy_loss_percent", "lower"),
    ("Energy gain vs baseline (kWh)", "energy_gain_vs_baseline_kwh", "higher"),
    ("Annual revenue (SAR)", "annual_revenue_sar", "higher"),
    ("Annualized CAPEX (SAR)", "annualized_capex_sar", "lower"),
    ("Annual OPEX (SAR)", "annual_opex_sar", "lower"),
    ("Total annual cost (SAR)", "total_annual_cost_sar", "lower"),
    ("Net annual benefit (SAR)", "net_annual_benefit_sar", "higher"),
    ("Incremental ROI vs baseline", "incremental_roi_vs_baseline", "higher"),
    ("Incremental payback vs baseline (yr)", "incremental_payback_years_vs_baseline", "lower"),
    ("Effective LCOE (SAR/kWh)", "effective_lcoe_sar_per_kwh", "lower"),
    ("External cleaning water consumed (L)", "annual_operational_water_liters", None),
    ("Dew formed on coating (L)", "annual_condensed_water_liters", None),
    ("Dew harvested from coating (L)", "annual_collected_water_liters", None),
    ("Crew hours", "annual_operational_crew_hours", None),
    ("Drone flight hours", "annual_operational_drone_flight_hours", None),
)


def _parse_finite(value: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _best_flags(values: list[str], direction: str | None) -> list[bool]:
    """Flag the best stored value(s) in a row. Comparison of stored numbers only."""
    if direction is None:
        return [False] * len(values)
    parsed = [_parse_finite(value) for value in values]
    candidates = [number for number in parsed if number is not None]
    if not candidates:
        return [False] * len(values)
    best = max(candidates) if direction == "higher" else min(candidates)
    return [number is not None and number == best for number in parsed]


def _kpi_table(
    header: list[str],
    rows: list[list[str]],
    *,
    period_is_full_year: bool = True,
) -> dict[str, object]:
    """Transpose selected annual summary columns: scenarios across, KPIs down."""
    index = {name: position for position, name in enumerate(header)}
    scenario_col = index.get("scenario_name", index.get("scenario_id", 0))
    scenarios = [row[scenario_col] for row in rows]
    table_rows = []
    for label, column, direction in _KPI_FIELDS:
        if column not in index:
            continue
        values = [row[index[column]] for row in rows]
        table_rows.append(
            {
                "label": label,
                "column": column,
                "values": values,
                "direction": direction,
                "best": _best_flags(values, direction),
                "help": (
                    _KPI_GLOSSARY.get(column, "")
                    if period_is_full_year
                    else _KPI_CONFIGURED_PERIOD_GLOSSARY.get(column, _KPI_GLOSSARY.get(column, ""))
                ),
                "audit_sources": [
                    (
                        "scenario_annual_summary.csv · "
                        f"row scenario_name={scenario} · column {column}"
                    )
                    for scenario in scenarios
                ],
            }
        )
    return {"scenarios": scenarios, "rows": table_rows}


def _stored_kpi_table(run_dir: Path) -> dict[str, object] | None:
    """Selected annual KPIs already stored in a run's summary CSV."""
    annual_path = run_dir / "scenario_annual_summary.csv"
    if not annual_path.is_file():
        return None
    header, rows = artifacts.read_csv_rows(annual_path)
    return _kpi_table(header, rows)


def _water_balance_card(header: list[str], rows: list[list[str]]) -> dict[str, object] | None:
    """Select the stored per-strategy water ledger for presentation."""

    index = {name: position for position, name in enumerate(header)}
    scenario_column = "scenario_name" if "scenario_name" in index else "scenario_id"
    required = {
        scenario_column,
        "annual_operational_water_liters",
        "annual_collected_water_liters",
    }
    if not required <= index.keys():
        return None

    optional_columns = (
        "annual_cleaning_water_consumed_cubic_meters",
        "annual_collected_water_cubic_meters",
        "annual_net_water_position_liters",
        "annual_net_water_position_cubic_meters",
        "annual_collected_water_tank_equivalents",
        "annual_dew_eligible_nights",
    )
    card_rows: list[dict[str, object]] = []
    for row in rows:
        selected: dict[str, object] = {
            "scenario_id": row[index[scenario_column]],
            "consumed_liters": row[index["annual_operational_water_liters"]],
            "harvested_liters": row[index["annual_collected_water_liters"]],
        }
        for column in optional_columns:
            selected[column] = row[index[column]] if column in index else None
        net = (
            _parse_finite(str(selected["annual_net_water_position_liters"]))
            if selected["annual_net_water_position_liters"] is not None
            else None
        )
        if net is not None and net > 0:
            selected["net_tone"] = "positive"
        elif net is not None and net < 0:
            selected["net_tone"] = "negative"
        else:
            selected["net_tone"] = "neutral"
        selected["audit_source"] = (
            "scenario_annual_summary.csv · "
            f"row scenario_name={selected['scenario_id']} · stored annual water columns"
        )
        card_rows.append(selected)

    tank_basis = None
    if "water_storage_tank_basis_liters" in index and rows:
        tank_basis = rows[0][index["water_storage_tank_basis_liters"]]
    return {
        "rows": card_rows,
        "tank_basis_liters": tank_basis,
        "complete": all(column in index for column in optional_columns),
    }


def _daily_scenario_columns(
    run_dir: Path,
    scenario_id: str,
    columns: dict[str, str],
) -> dict[str, object] | None:
    """Align stored daily columns for one scenario without deriving new values."""

    dates: list[str] = []
    selected: dict[str, dict[str, float | None]] = {}
    for output_name, column in columns.items():
        reshaped = artifacts.daily_series(run_dir, column)
        if not reshaped:
            continue
        raw_dates = reshaped.get("dates")
        raw_series = reshaped.get("series")
        values = raw_series.get(scenario_id) if isinstance(raw_series, dict) else None
        if not isinstance(raw_dates, list) or not isinstance(values, list):
            continue
        date_values = {
            str(raw_date): cast("float | None", value)
            for raw_date, value in zip(raw_dates, values, strict=False)
        }
        selected[output_name] = date_values
        for raw_date in raw_dates:
            day = str(raw_date)
            if day not in dates:
                dates.append(day)

    if not dates or not selected:
        return None
    payload: dict[str, object] = {"dates": dates}
    has_stored_value = False
    for output_name in columns:
        values = [selected.get(output_name, {}).get(day) for day in dates]
        payload[output_name] = values
        has_stored_value = has_stored_value or any(value is not None for value in values)
    return payload if has_stored_value else None


def _detection_performance(run_dir: Path) -> dict[str, object] | None:
    """Stored reactive detection/dispatch facts and date-aligned daily tracks.

    In particular, the daily confusion counts are not summed here. Annual
    operational facts are selected only from explicit annual columns.
    """

    daily = _daily_scenario_columns(
        run_dir,
        "reactive",
        {
            "missed_kwh": "extension_missed_contamination_estimated_energy_impact_kwh",
            "recovered_kwh": "extension_recovered_loss_estimated_kwh",
            "queue_length": "extension_queue_length",
            "backlog_length": "extension_inspection_backlog_length",
            "weather_cancelled": "extension_weather_cancelled_flight",
        },
    )
    annual_rows: list[dict[str, str]] = []
    annual_path = run_dir / "scenario_annual_summary.csv"
    if annual_path.is_file():
        header, rows = artifacts.read_csv_rows(annual_path)
        index = {column: position for position, column in enumerate(header)}
        scenario_column = "scenario_name" if "scenario_name" in index else "scenario_id"
        columns = {
            "survey_count": "annual_operational_whole_farm_survey_count",
            "dispatch_count": "annual_operational_cleaning_dispatch_count",
            "panels_cleaned": "annual_operational_panels_cleaned",
        }
        if scenario_column in index and all(column in index for column in columns.values()):
            for row in rows:
                if row[index[scenario_column]] != "reactive":
                    continue
                annual_rows.append(
                    {
                        "scenario_id": "reactive",
                        **{key: row[index[column]] for key, column in columns.items()},
                        "audit_source": (
                            "scenario_annual_summary.csv · row scenario_name=reactive · "
                            "stored annual_operational_* detection/dispatch columns"
                        ),
                    }
                )
                break
    if daily is None and not annual_rows:
        return None
    return {
        "annual_rows": annual_rows,
        "daily": daily,
        "daily_audit_source": (
            "scenario_daily_summary.csv · row scenario_name=reactive · stored extension_* columns"
        ),
    }


def _coating_service_life(run_dir: Path) -> dict[str, object] | None:
    """Stored coating traces plus transparent display-only diagnostics."""

    payload = _daily_scenario_columns(
        run_dir,
        "coating",
        {
            "age_days": "extension_coating_age_days",
            "effectiveness_fraction": "extension_coating_effectiveness_fraction",
            "optical_effect_kwh": "extension_optical_effect_kwh",
            "temperature_effect_kwh": "extension_temperature_effect_kwh",
            "cleanliness_effect_kwh": "extension_cleanliness_effect_kwh",
            "dew_point_c": "extension_dew_point_c",
            "coated_surface_temperature_c": "extension_coated_surface_temperature_c",
            "actually_collected_water_liters": "extension_actually_collected_water_liters",
        },
    )
    if payload is None:
        return None
    dew_points = payload.get("dew_point_c")
    surface_temperatures = payload.get("coated_surface_temperature_c")
    if isinstance(dew_points, list) and isinstance(surface_temperatures, list):
        payload["dew_margin_c"] = [
            float(dew_point) - float(surface)
            if isinstance(dew_point, int | float) and isinstance(surface, int | float)
            else None
            for dew_point, surface in zip(dew_points, surface_temperatures, strict=False)
        ]
    else:
        payload["dew_margin_c"] = []

    coating = _resolved_config_section(run_dir, "coating")
    raw_physics = coating.get("physics")
    physics = raw_physics if isinstance(raw_physics, dict) else {}
    daytime_cooling = physics.get("daytime_cooling_fraction")
    payload["temperature_effect_inactive"] = daytime_cooling == 0
    payload["audit_source"] = (
        "scenario_daily_summary.csv · row scenario_name=coating · stored extension_* columns; "
        "dew margin is displayed as stored dew point minus stored coated-surface temperature"
    )
    return payload


# Cost component category order and labels for the redesigned cost table.
_COST_CATEGORY_LABELS = {
    "capex": "Capital costs (CAPEX)",
    "opex": "Operating costs (OPEX)",
}


def _reconciliation_lookup(
    reconciliation: dict[str, object] | None,
) -> dict[str, dict[str, object]]:
    checks = reconciliation.get("checks") if reconciliation else None
    if not isinstance(checks, list):
        return {}
    lookup: dict[str, dict[str, object]] = {}
    for number, raw in enumerate(checks, start=1):
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            continue
        lookup[str(raw["name"])] = {
            "number": number,
            "passed": bool(raw.get("passed")),
            "message": str(raw.get("message", "")),
        }
    return lookup


def _cost_audit(
    scenario_id: str,
    amount: str,
    unit: str,
    notes: str,
    row_number: int,
    reconciliation: dict[str, object] | None,
) -> dict[str, str]:
    """Explain a stored component row without recreating its economics."""

    pieces = [piece.strip() for piece in notes.split(";") if piece.strip()]
    quantity = next((piece for piece in pieces if "=" in piece), "")
    unit_rate = next((piece for piece in pieces if piece.startswith("unit_rate=")), "")
    if quantity and unit_rate:
        detail = (
            f"{quantity.replace('=', ' ')} × {unit_rate.removeprefix('unit_rate=')} "
            f"= {_format_sar(amount)} {unit or 'SAR'}"
        )
    else:
        detail = notes or f"Stored amount = {_format_sar(amount)} {unit or 'SAR'}"

    quantity_key = quantity.partition("=")[0]
    check_name = f"{scenario_id}_cost_{quantity_key}_reconciles" if quantity_key else ""
    check = _reconciliation_lookup(reconciliation).get(check_name)
    if check:
        mark = "✓" if check["passed"] else "✕"
        check_text = f"reconciliation check #{check['number']} {mark} · {check_name}"
    else:
        check_text = "No quantity-rate reconciliation check applies to this stored component."
    return {
        "source": f"scenario_cost_summary.csv · row {row_number}",
        "detail": detail,
        "check": check_text,
    }


def _cost_table(
    header: list[str],
    rows: list[list[str]],
    reconciliation: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """Group scenario_cost_summary.csv rows for reading.

    Reshaping and display formatting only: every amount, subtotal, and total
    below is a value stored in the CSV (component amount_sar, scenario-level
    total_capex_sar / annual_opex_sar / annualized_capex_sar /
    total_annual_cost_sar). Nothing is summed or derived here.
    """
    index = {name: position for position, name in enumerate(header)}

    def cell(row: list[str], column: str) -> str:
        position = index.get(column)
        if position is None or position >= len(row):
            return ""
        return row[position]

    scenario_order: list[str] = []
    components_by_scenario: dict[str, dict[str, list[dict[str, object]]]] = {}
    stored_totals: dict[str, dict[str, str]] = {}
    evidence_by_scenario: dict[str, list[dict[str, str]]] = {}
    first_row_by_scenario: dict[str, int] = {}
    for row_number, row in enumerate(rows, start=2):
        scenario_id = cell(row, "scenario_id")
        if not scenario_id:
            continue
        if scenario_id not in scenario_order:
            scenario_order.append(scenario_id)
            components_by_scenario[scenario_id] = {}
            evidence_by_scenario[scenario_id] = []
            first_row_by_scenario[scenario_id] = row_number
            stored_totals[scenario_id] = {
                "total_capex_sar": cell(row, "total_capex_sar"),
                "annualized_capex_sar": cell(row, "annualized_capex_sar"),
                "annual_opex_sar": cell(row, "annual_opex_sar"),
                "total_annual_cost_sar": cell(row, "total_annual_cost_sar"),
                "capital_recovery_life_years": cell(row, "capital_recovery_life_years"),
            }
        component_name = cell(row, "component_name")
        category = cell(row, "category")
        if not category or component_name in ("", "none"):
            continue  # scenario placeholder row without components (e.g. baseline)
        components_by_scenario[scenario_id].setdefault(category, []).append(
            {
                "name": component_name,
                "amount": cell(row, "amount_sar"),
                "unit": cell(row, "unit") or "SAR",
                "audit": _cost_audit(
                    scenario_id,
                    cell(row, "amount_sar"),
                    cell(row, "unit") or "SAR",
                    cell(row, "notes"),
                    row_number,
                    reconciliation,
                ),
            }
        )
        evidence_by_scenario[scenario_id].append(
            {
                "name": component_name,
                "evidence_status": cell(row, "source_status"),
                "source": cell(row, "source"),
                "notes": cell(row, "notes"),
            }
        )

    table: list[dict[str, object]] = []
    for scenario_id in scenario_order:
        stored = stored_totals[scenario_id]
        ordered_groups: list[dict[str, object]] = []
        for category in ("capex", "opex"):
            components = components_by_scenario[scenario_id].get(category)
            if not components:
                continue
            # Subtotals are the scenario-level figures the backend already
            # wrote next to every component row, not sums made here.
            subtotal_column = "total_capex_sar" if category == "capex" else "annual_opex_sar"
            subtotal_unit = "SAR" if category == "capex" else "SAR/year"
            ordered_groups.append(
                {
                    "category": category,
                    "label": _COST_CATEGORY_LABELS.get(category, category),
                    "components": components,
                    "subtotal_amount": stored.get(subtotal_column, ""),
                    "subtotal_unit": subtotal_unit,
                }
            )
        table.append(
            {
                "scenario": scenario_id,
                "groups": ordered_groups,
                "annualized_capex_sar": stored.get("annualized_capex_sar", ""),
                "annual_opex_sar": stored.get("annual_opex_sar", ""),
                "total_annual_cost_sar": stored.get("total_annual_cost_sar", ""),
                "capital_recovery_life_years": stored.get("capital_recovery_life_years", ""),
                "audit_source": (
                    "scenario_cost_summary.csv · "
                    f"row {first_row_by_scenario.get(scenario_id, 2)} · stored scenario totals"
                ),
                "evidence": evidence_by_scenario[scenario_id],
            }
        )
    return table


def _financial_ranking(
    header: list[str],
    rows: list[list[str]],
    ranking: dict[str, object] | None,
    metadata: dict[str, object] | None,
) -> dict[str, object] | None:
    """Join stored ranking order to the stored financial explanation fields.

    This is a display-only join. Every monetary and energy value is passed
    through from ``scenario_ranking.json``, ``scenario_annual_summary.csv``,
    or ``metadata.json``; no economics are recomputed here.
    """

    raw_ranking = ranking.get("ranking") if ranking else None
    if not isinstance(raw_ranking, list) or not raw_ranking:
        return None

    index = {name: position for position, name in enumerate(header)}
    scenario_col = index.get("scenario_name", index.get("scenario_id"))
    required = {
        "annual_actual_energy_kwh",
        "annual_revenue_sar",
        "annualized_capex_sar",
        "annual_opex_sar",
        "total_annual_cost_sar",
        "net_annual_benefit_sar",
        "incremental_revenue_vs_baseline_sar",
        "incremental_annual_cost_vs_baseline_sar",
        "incremental_net_annual_benefit_vs_baseline_sar",
    }
    if scenario_col is None or not required.issubset(index):
        return None

    stored_by_scenario = {
        row[scenario_col]: row for row in rows if scenario_col < len(row) and row[scenario_col]
    }

    def stored(row: list[str], column: str) -> str:
        position = index.get(column)
        return row[position] if position is not None and position < len(row) else ""

    display_rows: list[dict[str, object]] = []
    for raw_entry in raw_ranking:
        if not isinstance(raw_entry, dict):
            return None
        scenario_id = raw_entry.get("scenario_id")
        if not isinstance(scenario_id, str) or scenario_id not in stored_by_scenario:
            return None
        annual_row = stored_by_scenario[scenario_id]
        display_rows.append(
            {
                "rank": raw_entry.get("rank"),
                "tied_with_previous": bool(raw_entry.get("tied_with_previous")),
                "scenario_id": scenario_id,
                "annual_actual_energy_kwh": stored(annual_row, "annual_actual_energy_kwh"),
                "annual_revenue_sar": stored(annual_row, "annual_revenue_sar"),
                "annualized_capex_sar": stored(annual_row, "annualized_capex_sar"),
                "annual_opex_sar": stored(annual_row, "annual_opex_sar"),
                "total_annual_cost_sar": stored(annual_row, "total_annual_cost_sar"),
                "net_annual_benefit_sar": raw_entry.get("net_annual_benefit_sar"),
                "incremental_revenue_sar": stored(
                    annual_row, "incremental_revenue_vs_baseline_sar"
                ),
                "incremental_annual_cost_sar": stored(
                    annual_row, "incremental_annual_cost_vs_baseline_sar"
                ),
                "incremental_net_annual_benefit_sar": stored(
                    annual_row, "incremental_net_annual_benefit_vs_baseline_sar"
                ),
                "total_capex_sar": stored(annual_row, "total_capex_sar"),
                "capital_recovery_life_years": stored(annual_row, "capital_recovery_life_years"),
                "annual_audit_source": (
                    f"scenario_annual_summary.csv · row scenario_name={scenario_id}"
                ),
            }
        )

    economics = metadata.get("economics_config") if metadata else None
    economics = economics if isinstance(economics, dict) else {}
    annualization_method = economics.get("annualization_method")
    return {
        "rows": display_rows,
        "tariff_sar_per_kwh": economics.get("tariff_sar_per_kwh"),
        "annualization_method": (
            str(annualization_method).replace("_", " ") if annualization_method else None
        ),
    }


def _registry_path(config_path: Path) -> Path:
    """Resolve the registry selected by a dashboard configuration.

    Absolute paths are deployment-friendly. Relative paths first follow the
    config file (useful with ``SOLARCLEAN_CONFIGS_DIR``), then retain the
    repository-root semantics used by the bundled configurations.
    """
    configured = load_config(config_path).calibration.parameter_registry_path
    if configured.is_absolute():
        return configured
    beside_config = config_path.parent / configured
    if beside_config.is_file():
        return beside_config
    return _REPO_ROOT / configured


def _parameter_catalog(config_path: Path | None = None) -> list[dict[str, object]]:
    """T7-supported sensitivity parameters for the launch-form dropdowns.

    Listing only: names and registry ranges pass through so users pick from a
    menu instead of hand-typing registry keys. Empty on any load failure — the
    launch endpoint will then produce the real error.
    """
    try:
        selected_config = config_path or _config_path(DEFAULT_CONFIG_NAME)
        registry_path = _registry_path(selected_config)
        supported, _ = build_parameter_catalog(ParameterRegistry.from_yaml(registry_path))
    except Exception:
        return []
    return [
        {
            "name": spec.name,
            "unit": spec.unit,
            "low": spec.low_value,
            "central": spec.central_value,
            "high": spec.high_value,
        }
        for spec in supported
    ]


# Plain-English definitions for the KPI table. Keyed by CSV column name;
# wording only — no numbers are produced here.
_KPI_GLOSSARY: dict[str, str] = {
    "annual_energy_loss_percent": (
        "Energy lost to soiling and contamination, as a share of what perfectly "
        "clean panels would have produced over the year."
    ),
    "annualized_capex_sar": (
        "Upfront equipment/installation spend spread over its useful life, so a "
        "one-off purchase can be compared against yearly costs."
    ),
    "annual_opex_sar": "Recurring yearly operating spend: labour, water, energy, maintenance.",
    "total_annual_cost_sar": "Annualized CAPEX plus annual OPEX — the full yearly cost.",
    "net_annual_benefit_sar": (
        "Annual electricity revenue minus total annual cost. The ranking metric: "
        "higher means the strategy pays off better."
    ),
    "incremental_roi_vs_baseline": (
        "Return on investment of the mitigation relative to doing nothing: extra "
        "net benefit per SAR of extra cost. Above 0 means the added spend pays back "
        "more than it costs each year."
    ),
    "incremental_payback_years_vs_baseline": (
        "Years until the extra revenue (vs doing nothing) has repaid the upfront "
        "investment. Blank for baseline — there is nothing to pay back."
    ),
    "effective_lcoe_sar_per_kwh": (
        "Levelized cost of energy: the strategy's annual cost divided by the energy "
        "delivered — SAR spent per kWh produced. Lower is cheaper energy."
    ),
    "annual_operational_water_liters": (
        "External water consumed by active cleaning operations. Coating dew is reported "
        "separately, so a zero here for the passive coating scenario is expected."
    ),
    "annual_condensed_water_liters": (
        "Weather-gated dew formed across the coated panel area. The paper-anchored "
        "configuration calibrates favorable conditions to 0.128 L/m² per night; drier "
        "modeled nights contribute zero. Uncoated scenarios stay at zero."
    ),
    "annual_collected_water_liters": (
        "Paper-equivalent harvested dew routed to storage for reuse (e.g. irrigation). "
        "The volume is weather- and coated-area-adjusted; it is not a blanket 365-night "
        "projection. Collection cost and water revenue are not included in the economics."
    ),
}

_KPI_CONFIGURED_PERIOD_GLOSSARY: dict[str, str] = {
    "annual_energy_loss_percent": (
        "Energy lost to soiling and contamination, as a share of what perfectly "
        "clean panels would have produced over the configured period."
    ),
    "annualized_capex_sar": (
        "Upfront equipment and installation spend allocated using the stored service-life "
        "assumptions for this configured-period comparison."
    ),
    "annual_opex_sar": "Recurring operating spend recorded for the configured period.",
    "total_annual_cost_sar": (
        "The stored CAPEX allocation plus operating spend for the configured period."
    ),
    "net_annual_benefit_sar": (
        "Electricity revenue over the configured period minus its stored total cost. "
        "The ranking metric: higher means the strategy pays off better."
    ),
    "incremental_roi_vs_baseline": (
        "Return on investment of the mitigation relative to doing nothing over the configured "
        "period: extra net benefit per SAR of extra cost."
    ),
    "effective_lcoe_sar_per_kwh": (
        "Levelized cost of energy for the configured period: stored cost divided by delivered "
        "energy. Lower is cheaper energy."
    ),
}


def _mc_trials_series(header: list[str], rows: list[list[str]]) -> dict[str, object] | None:
    """Per-trial net benefit per scenario from monte_carlo_trials.csv (column picks)."""
    index = {name: position for position, name in enumerate(header)}
    scenario_columns = [
        (column.removesuffix("_net_annual_benefit_sar"), column)
        for column in header
        if column.endswith("_net_annual_benefit_sar")
    ]
    if not scenario_columns or "reconciled" not in index:
        return None
    series: dict[str, list[float]] = {scenario: [] for scenario, _ in scenario_columns}
    for row in rows:
        if row[index["reconciled"]].strip().lower() != "true":
            continue  # unreconciled trials are excluded from statistics upstream too
        for scenario, column in scenario_columns:
            value = _parse_finite(row[index[column]])
            if value is not None:
                series[scenario].append(value)
    if not any(series.values()):
        return None
    return {"series": series}


def _oneway_tornado(summary: dict[str, object] | None) -> dict[str, object] | None:
    """Tornado-chart data from sensitivity_oneway_summary.json (stored swings)."""
    if not summary:
        return None
    raw_results = summary.get("parameter_results")
    if not isinstance(raw_results, list) or not raw_results:
        return None
    entries = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        swings = raw.get("swing_sar")
        if not isinstance(swings, dict):
            continue
        numeric = [float(v) for v in swings.values() if isinstance(v, int | float)]
        entries.append(
            {
                "parameter": str(raw.get("parameter_name", "")),
                "unit": str(raw.get("unit", "")),
                # Backend-stored swing per scenario; the bar shows the largest,
                # mirroring OneWaySensitivityResult.ranked_by_swing().
                "swing_sar": max(numeric, default=0.0),
                "winner_changed": bool(raw.get("winner_changed", False)),
            }
        )
    entries.sort(key=lambda entry: float(str(entry["swing_sar"])), reverse=True)
    return {"entries": entries} if entries else None


def _twoway_grid(summary: dict[str, object] | None) -> dict[str, object] | None:
    """Reshape the winner-map grid records into axes + cell matrix for rendering."""
    if not summary:
        return None
    parameter_a = summary.get("parameter_a")
    parameter_b = summary.get("parameter_b")
    grid = summary.get("grid")
    if not isinstance(parameter_a, str) or not isinstance(parameter_b, str):
        return None
    if not isinstance(grid, list) or not grid:
        return None
    key_a, key_b = f"{parameter_a}_value", f"{parameter_b}_value"
    values_a: list[float] = []
    values_b: list[float] = []
    cells: dict[tuple[float, float], dict[str, object]] = {}
    for raw in grid:
        if not isinstance(raw, dict):
            continue
        value_a, value_b = raw.get(key_a), raw.get(key_b)
        if not isinstance(value_a, int | float) or not isinstance(value_b, int | float):
            continue
        a, b = float(value_a), float(value_b)
        if a not in values_a:
            values_a.append(a)
        if b not in values_b:
            values_b.append(b)
        benefits = {
            key.removesuffix("_net_annual_benefit_sar"): value
            for key, value in raw.items()
            if key.endswith("_net_annual_benefit_sar") and isinstance(value, int | float)
        }
        tooltip = ", ".join(f"{sid}: {val:,.0f} SAR" for sid, val in sorted(benefits.items()))
        cells[(a, b)] = {
            "winner": raw.get("winner") if raw.get("reconciled") else None,
            "reconciled": bool(raw.get("reconciled")),
            "tooltip": tooltip,
        }
    if not cells:
        return None
    values_a.sort()
    values_b.sort()
    matrix = [[cells.get((a, b)) for a in values_a] for b in reversed(values_b)]
    return {
        "parameter_a": parameter_a,
        "parameter_b": parameter_b,
        "values_a": values_a,
        "values_b_desc": list(reversed(values_b)),
        "matrix": matrix,
    }


def _breakeven_chart(report: dict[str, object] | None) -> dict[str, object] | None:
    """Margin-vs-value points and crossings from breakeven_report.json."""
    if not report:
        return None
    evaluations = report.get("evaluations")
    if not isinstance(evaluations, list) or not evaluations:
        return None
    points = []
    for raw in evaluations:
        if not isinstance(raw, dict):
            continue
        value, margin = raw.get("value"), raw.get("margin_sar")
        if isinstance(value, int | float) and isinstance(margin, int | float):
            points.append({"x": float(value), "y": float(margin)})
    if not points:
        return None
    points.sort(key=lambda point: point["x"])
    raw_crossovers = report.get("crossover_values")
    crossovers = (
        [float(value) for value in raw_crossovers if isinstance(value, int | float)]
        if isinstance(raw_crossovers, list)
        else []
    )
    return {
        "points": points,
        "crossovers": crossovers,
        "parameter_name": report.get("parameter_name"),
        "scenario_a": report.get("scenario_a"),
        "scenario_b": report.get("scenario_b"),
    }


def _resolved_config(run_dir: Path) -> dict[str, object]:
    """The stored configuration document for a run, when available."""

    config_path = run_dir / "config_resolved.yaml"
    if not config_path.is_file():
        return {}
    try:
        resolved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return resolved if isinstance(resolved, dict) else {}


def _resolved_config_section(run_dir: Path, section: str) -> dict[str, object]:
    """One top-level section of the run's stored config_resolved.yaml."""

    raw = _resolved_config(run_dir).get(section)
    return raw if isinstance(raw, dict) else {}


def _comparison_period_context(run_dir: Path) -> dict[str, object]:
    """Conservative display semantics from the run's stored simulation period."""

    simulation = _resolved_config_section(run_dir, "simulation")
    try:
        start = datetime.fromisoformat(str(simulation["start"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(simulation["end"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        full_year = False
    else:
        # Keep this definition aligned with the comparison backend's
        # _simulation_period_is_full_year policy.
        full_year = (
            start.year == end.year
            and start.month == 1
            and start.day == 1
            and end.month == 12
            and end.day == 31
        )
    return {
        "period_is_full_year": full_year,
        "period_label": "Full-year totals" if full_year else "Configured-period totals",
    }


def _weather_cache_status(config: SolarCleanConfig) -> dict[str, str]:
    """Read-only readiness signal for the selected configuration cockpit."""

    provider = config.weather.provider
    if provider == "fixture":
        return {
            "state": "ready",
            "label": "✓ bundled fixture",
            "detail": config.weather.fixture_profile,
        }
    if provider == "csv":
        configured = config.weather.local_csv_path
        if configured is None:
            return {"state": "missing", "label": "needs file", "detail": "No local CSV configured"}
        path = configured if configured.is_absolute() else _REPO_ROOT / configured
        return {
            "state": "ready" if path.is_file() else "missing",
            "label": "✓ local file" if path.is_file() else "needs file",
            "detail": str(configured),
        }
    if not config.weather.cache_enabled:
        return {"state": "fetch", "label": "fetch each run", "detail": "Weather cache disabled"}

    cache_dir = config.weather.cache_directory
    cache_dir = cache_dir if cache_dir.is_absolute() else _REPO_ROOT / cache_dir
    if not cache_dir.is_dir():
        return {"state": "fetch", "label": "needs fetch", "detail": "NASA POWER cache not found"}
    request = WeatherRequest(
        latitude=config.site.latitude,
        longitude=config.site.longitude,
        elevation_m=config.site.elevation_m,
        start=config.simulation.start,
        end=config.simulation.end,
        target_timezone=config.simulation.target_timezone,
        variables=frozenset(CANONICAL_WEATHER_COLUMNS),
    )
    cache = WeatherCache(cache_dir)
    key = cache.key_for(request, "nasa_power")
    cached = (cache_dir / f"{key}.normalized.csv").is_file() and (
        cache_dir / f"{key}.metadata.json"
    ).is_file()
    return {
        "state": "ready" if cached else "fetch",
        "label": "✓ cached" if cached else "needs fetch",
        "detail": f"NASA POWER · key {key[:10]}",
    }


def _certified_winner(
    recommendation: dict[str, object] | None,
    reconciliation: dict[str, object] | None,
) -> str | None:
    """Return the sole winner only when every stored certification gate passes."""

    if recommendation is None or reconciliation is None:
        return None
    winner = recommendation.get("winner")
    tier = recommendation.get("recommendation_tier")
    normalized_winner = winner.strip() if isinstance(winner, str) else ""
    normalized_tier = tier.strip().lower() if isinstance(tier, str) else ""
    if (
        recommendation.get("valid") is not True
        or recommendation.get("calculation_valid") is not True
        or not normalized_tier
        or normalized_tier == "exploratory"
        or reconciliation.get("passed") is not True
        or not normalized_winner
    ):
        return None
    return normalized_winner


def _config_cockpits(
    config_names: list[str], run_entries: list[artifacts.RunEntry]
) -> dict[str, dict[str, object]]:
    """Instrument-cluster state for every selectable launch configuration."""

    cockpits: dict[str, dict[str, object]] = {}
    for name in config_names:
        try:
            config = load_config(_config_path(name))
        except Exception as exc:
            cockpits[name] = {"error": str(exc)}
            continue
        selected_study = _study_from_resolved_config(config.model_dump(mode="json"))
        if selected_study is not None:
            try:
                selected_study["registry_checksum"] = ParameterRegistry.from_yaml(
                    _registry_path(_config_path(name))
                ).checksum()
            except Exception:
                # Legacy/unavailable registries leave this input unknown. The
                # cockpit remains readable, but a known unequal checksum can
                # never be selected as the current finding.
                selected_study["registry_checksum"] = ""
        # A run-id prefix is a filename convention, not proof that the stored
        # inputs still match an edited configuration. Select by the same
        # immutable config fingerprint used by cross-run evidence joins.
        last: artifacts.RunEntry | None = None
        last_recommendation: dict[str, object] | None = None
        last_winner: str | None = None
        for entry in run_entries:
            if entry.kind != "compare-all-scenarios" or selected_study is None:
                continue
            entry_study = _run_study(entry.path)
            if entry_study is None or not _studies_compatible(entry_study, selected_study):
                continue
            recommendation = artifacts.load_json(entry.path / "recommendation.json")
            reconciliation = artifacts.load_json(entry.path / "reconciliation_report.json")
            winner = _certified_winner(recommendation, reconciliation)
            if winner is not None:
                last = entry
                last_recommendation = recommendation
                last_winner = winner
                break
        last_run: dict[str, object] | None = None
        if last is not None and last_recommendation is not None and last_winner is not None:
            margin = last_recommendation.get("decisive_margin_sar")
            last_run = {
                "run_id": last.run_id,
                "winner": last_winner,
                "margin_sar": (
                    _format_sar(margin)
                    if isinstance(margin, int | float) and math.isfinite(float(margin))
                    else None
                ),
                "valid": True,
            }
        cockpits[name] = {
            "site_name": config.site.name,
            "latitude": config.site.latitude,
            "longitude": config.site.longitude,
            "start_date": config.simulation.start.date().isoformat(),
            "end_date": config.simulation.end.date().isoformat(),
            "timezone": config.simulation.target_timezone,
            "weather_provider": config.weather.provider,
            "weather_status": _weather_cache_status(config),
            "assumption_set": config.calibration.assumption_set,
            "last_run": last_run,
        }
    return cockpits


def _provenance(run_dir: Path) -> dict[str, object] | None:
    """Weather/site provenance from the run's stored artifacts.

    Provider/checksum/creation time come from the traceability metadata that
    comparison runs write; the site block comes from config_resolved.yaml
    (present on every run kind, and stored as proper YAML — the metadata's
    config_metadata field is stringified and not machine-readable).
    """
    metadata = artifacts.load_json(run_dir / "metadata.json") or artifacts.load_json(
        run_dir / "comparison_metadata.json"
    )
    site = _resolved_config_section(run_dir, "site")
    weather_cfg = _resolved_config_section(run_dir, "weather")
    calibration = _resolved_config_section(run_dir, "calibration")
    simulation = _resolved_config_section(run_dir, "simulation")
    if metadata is None and not site and not weather_cfg:
        return None
    metadata = metadata or {}
    checksum = str(metadata.get("weather_checksum", ""))
    return {
        "provider": metadata.get("weather_provider") or weather_cfg.get("provider"),
        "site_name": site.get("name"),
        "latitude": site.get("latitude"),
        "longitude": site.get("longitude"),
        "weather_checksum": checksum or None,
        "weather_checksum_short": checksum[:12] if checksum else None,
        "created_at_utc": str(metadata.get("created_at_utc") or metadata.get("created_utc", ""))[
            :19
        ],
        "assumption_set": metadata.get("calibration_assumption_set")
        or calibration.get("assumption_set"),
        "start_date": str(simulation.get("start", ""))[:10],
        "end_date": str(simulation.get("end", ""))[:10],
    }


# --------------------------------------------------------------------------
# Studies: grouping runs by the stored identity that produced them
# --------------------------------------------------------------------------
# A "study" is one exact set of decision inputs read from a run's own
# config_resolved.yaml. The human label remains site/period/assumption-set,
# while grouping and cross-run evidence joins use a deterministic fingerprint
# of all decision-relevant configuration content.


# These settings can change how or where a run is executed or serialized, but
# cannot change its simulated or economic decision. Everything else is
# included by default so newly added scientific sections are safe without a
# dashboard allow-list update.
_NON_DECISION_CONFIG_PATHS = frozenset(
    {
        ("output",),
        ("logging",),
        ("simulation", "run_id_prefix"),
        ("weather", "cache_enabled"),
        ("weather", "cache_directory"),
        ("weather", "timeout_seconds"),
        ("farm", "store_cohort_daily_details"),
        ("calibration", "source_note"),
    }
)


def _canonical_decision_value(value: object, path: tuple[str, ...] = ()) -> object:
    """Return stable JSON-safe decision data with runtime-only fields removed."""

    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            child_path = (*path, key)
            if child_path in _NON_DECISION_CONFIG_PATHS:
                continue
            normalized[key] = _canonical_decision_value(item, child_path)
        return normalized
    if isinstance(value, list | tuple):
        return [_canonical_decision_value(item, path) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


def _decision_config_fingerprint(resolved: Mapping[str, object]) -> str:
    """Versioned SHA-256 identity for configuration that can affect a decision."""

    payload = _canonical_decision_value(resolved)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _study_from_resolved_config(resolved: Mapping[str, object]) -> dict[str, str] | None:
    """Build a fingerprint identity and readable label from one config snapshot."""

    raw_site = resolved.get("site")
    raw_simulation = resolved.get("simulation")
    raw_calibration = resolved.get("calibration")
    site = raw_site if isinstance(raw_site, Mapping) else {}
    simulation = raw_simulation if isinstance(raw_simulation, Mapping) else {}
    calibration = raw_calibration if isinstance(raw_calibration, Mapping) else {}

    name = str(site.get("name", ""))
    start = str(simulation.get("start", ""))[:10]
    end = str(simulation.get("end", ""))[:10]
    assumption_set = str(calibration.get("assumption_set", ""))
    if not name and not start:
        return None

    latitude, longitude = site.get("latitude"), site.get("longitude")
    coordinates = (
        f"{latitude}, {longitude}"
        if isinstance(latitude, int | float) and isinstance(longitude, int | float)
        else ""
    )
    fingerprint = _decision_config_fingerprint(resolved)
    label_parts = [name or "Unnamed site"]
    if coordinates:
        label_parts.append(coordinates)
    if start or end:
        label_parts.append(f"{start or '?'} — {end or '?'}")
    if assumption_set:
        label_parts.append(assumption_set)
    return {
        "key": f"config-v2-{fingerprint}",
        "fingerprint": fingerprint,
        "label": " · ".join(label_parts),
    }


@lru_cache(maxsize=1024)
def _study_info_cached(path_text: str, mtime_ns: int) -> tuple[str, str, str] | None:
    """Parse one immutable config snapshot into key, fingerprint, and label."""

    del mtime_ns  # cache key component; contents are read below
    try:
        resolved = yaml.safe_load(Path(path_text).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(resolved, dict):
        return None
    study = _study_from_resolved_config(resolved)
    if study is None:
        return None
    return study["key"], study["fingerprint"], study["label"]


def _run_study(run_dir: Path) -> dict[str, str] | None:
    """Study identity fields for one run, or None without a stored config."""

    config_path = run_dir / "config_resolved.yaml"
    try:
        mtime_ns = config_path.stat().st_mtime_ns
    except OSError:
        return None
    info = _study_info_cached(str(config_path.resolve()), mtime_ns)
    if info is None:
        return None
    key, fingerprint, label = info
    metadata = artifacts.load_json(run_dir / "metadata.json") or artifacts.load_json(
        run_dir / "comparison_metadata.json"
    )
    summary = artifacts.load_json(run_dir / "summary.json")
    metadata = metadata or {}
    summary = summary or {}
    return {
        "key": key,
        "fingerprint": fingerprint,
        "label": label,
        # Current comparison packages record both checksums. Legacy and
        # analysis packages may not; missing means unknown, never unequal.
        "weather_checksum": str(
            metadata.get("weather_checksum") or summary.get("weather_checksum") or ""
        ),
        "registry_checksum": str(metadata.get("parameter_registry_checksum") or ""),
    }


def _studies_compatible(first: Mapping[str, str], second: Mapping[str, str]) -> bool:
    """Whether two stored snapshots may safely contribute cross-run evidence."""

    if first.get("fingerprint") != second.get("fingerprint"):
        return False
    for checksum_field in ("weather_checksum", "registry_checksum"):
        first_checksum = first.get(checksum_field, "")
        second_checksum = second.get(checksum_field, "")
        if first_checksum and second_checksum and first_checksum != second_checksum:
            return False
    return True


_UNFILED_STUDY = {
    "key": "__unfiled__",
    "fingerprint": "",
    "label": "No stored configuration",
    "weather_checksum": "",
    "registry_checksum": "",
}


def _grouped_run_entries(
    run_entries: list[artifacts.RunEntry],
) -> list[tuple[artifacts.RunEntry, dict[str, str]]]:
    """Order runs as contiguous study blocks, studies by their newest run.

    The input is newest-first, so the first appearance order of study keys is
    already "most recently active study first"; within a study runs keep their
    newest-first order. Contiguous blocks keep pagination stable: an appended
    page can only continue the last block or start new ones.
    """

    blocks: dict[str, list[tuple[artifacts.RunEntry, dict[str, str]]]] = {}
    order: list[str] = []
    for entry in run_entries:
        study = _run_study(entry.path) or _UNFILED_STUDY
        if study["key"] not in blocks:
            blocks[study["key"]] = []
            order.append(study["key"])
        blocks[study["key"]].append((entry, study))
    grouped: list[tuple[artifacts.RunEntry, dict[str, str]]] = []
    for key in order:
        grouped.extend(blocks[key])
    return grouped


def _human_created(created: str, run_id: str) -> str:
    """Compact display timestamp for a run card (formatting only)."""

    raw = created
    if not raw:
        # Fall back to the timestamp embedded in the run id by OutputWriter.
        match = re.search(r"-(\d{8}T\d{6})Z-", run_id)
        if match:
            raw = (
                f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:8]}"
                f"T{match.group(1)[9:11]}:{match.group(1)[11:13]}"
            )
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:16] or "undated"
    return parsed.strftime("%b %d, %H:%M")


# One-line stored findings per analysis kind for cross-linking related runs.
_RUN_KIND_LABELS: dict[str, str] = {
    "compare-all-scenarios": "Comparison",
    "compare-multi-year": "Multi-year comparison",
    "monte-carlo": "Monte Carlo",
    "sensitivity-oneway": "One-way sensitivity",
    "sensitivity-winner-map": "Winner map",
    "break-even": "Break-even",
    "fetch-weather": "Weather retrieval",
    "run-clean": "Clean production run",
    "run-baseline": "Baseline run",
    "validate-weather": "Weather validation",
    "validate-phase-3-5": "Phase 3.5 validation",
    "validate-field": "Field validation",
    "profile-full-year": "Full-year profile",
}

_TECHNICAL_RUN_KINDS = {
    "fetch-weather",
    "validate-weather",
    "validate-phase-3-5",
    "validate-field",
    "profile-full-year",
}


def _comparison_summary_line(entry: artifacts.RunEntry) -> str:
    recommendation = artifacts.load_json(entry.path / "recommendation.json")
    reconciliation = artifacts.load_json(entry.path / "reconciliation_report.json")
    winner = _certified_winner(recommendation, reconciliation)
    if winner is None:
        return "no certified winner"
    text = f"winner {winner}"
    margin = recommendation.get("decisive_margin_sar") if recommendation else None
    if isinstance(margin, int | float) and math.isfinite(float(margin)):
        text += f" +{_format_sar(margin)} SAR"
    return text


def _mc_summary_line(entry: artifacts.RunEntry) -> str:
    if not entry.winner:
        return "no majority winner"
    text = f"majority winner {entry.winner}"
    if entry.win_probability is not None:
        text += f", wins {_format_sar(entry.win_probability * 100)}% of trials"
    return text


def _oneway_summary_line(entry: artifacts.RunEntry) -> str:
    tornado = _oneway_tornado(artifacts.load_json(entry.path / "sensitivity_oneway_summary.json"))
    entries = tornado.get("entries") if tornado else None
    if isinstance(entries, list) and entries and isinstance(entries[0], dict):
        return f"top driver {entries[0].get('parameter', 'unknown parameter')}"
    return "stored sweep"


def _twoway_summary_line(entry: artifacts.RunEntry) -> str:
    summary = artifacts.load_json(entry.path / "sensitivity_twoway_summary.json") or {}
    parameter_a, parameter_b = summary.get("parameter_a"), summary.get("parameter_b")
    if isinstance(parameter_a, str) and isinstance(parameter_b, str):
        return f"{parameter_a} × {parameter_b}"
    return "stored grid"


def _breakeven_summary_line(entry: artifacts.RunEntry) -> str:
    report = artifacts.load_json(entry.path / "breakeven_report.json") or {}
    parameter = report.get("parameter_name")
    if not isinstance(parameter, str):
        return "stored search"
    crossovers = report.get("crossover_values")
    if isinstance(crossovers, list) and crossovers:
        values = ", ".join(
            _display_number(str(value)) for value in crossovers if isinstance(value, int | float)
        )
        return f"{parameter} ties at {values}"
    return f"{parameter}: no crossing found"


_RELATED_SUMMARY_BUILDERS: dict[str, Callable[[artifacts.RunEntry], str]] = {
    "compare-all-scenarios": _comparison_summary_line,
    "compare-multi-year": _comparison_summary_line,
    "monte-carlo": _mc_summary_line,
    "sensitivity-oneway": _oneway_summary_line,
    "sensitivity-winner-map": _twoway_summary_line,
    "break-even": _breakeven_summary_line,
}


def _related_run_summary(entry: artifacts.RunEntry) -> str:
    """One sentence from a sibling run's stored summary artifacts."""

    builder = _RELATED_SUMMARY_BUILDERS.get(entry.kind)
    return builder(entry) if builder else "stored record"


def _related_runs(run_id: str, run_dir: Path) -> dict[str, object]:
    """Live archive siblings compatible with one immutable run snapshot."""

    study = _run_study(run_dir)
    siblings: list[dict[str, object]] = []
    comparables: list[dict[str, object]] = []
    for entry, entry_study in _grouped_run_entries(artifacts.list_runs(_OUTPUTS_DIR)):
        if entry.run_id == run_id:
            continue
        same_study = study is not None and _studies_compatible(entry_study, study)
        if same_study and len(siblings) < 8:
            siblings.append(
                {
                    "run_id": entry.run_id,
                    "kind": entry.kind,
                    "kind_label": _RUN_KIND_LABELS.get(entry.kind, entry.kind),
                    "summary": _related_run_summary(entry),
                    "created": _human_created(entry.created, entry.run_id),
                }
            )
        if entry.kind in ("compare-all-scenarios", "compare-multi-year"):
            comparables.append(
                {
                    "run_id": entry.run_id,
                    "same_study": same_study,
                    "label": (
                        f"{entry_study['label']} · {_human_created(entry.created, entry.run_id)}"
                    ),
                }
            )
    comparables.sort(key=lambda candidate: not candidate["same_study"])
    return {
        "study": study,
        "siblings": siblings,
        "comparables": comparables[:20],
        "context_source": "live_archive",
        "compatibility_basis": "decision_config_fingerprint_v2",
    }


def _sibling_mc_context(run_id: str, run_dir: Path) -> dict[str, object] | None:
    """Newest same-study Monte Carlo run's stored certainty figures."""

    study = _run_study(run_dir)
    if study is None:
        return None
    for entry in artifacts.list_runs(_OUTPUTS_DIR):
        if entry.kind != "monte-carlo" or entry.run_id == run_id:
            continue
        entry_study = _run_study(entry.path)
        if entry_study is None or not _studies_compatible(entry_study, study):
            continue
        summary = artifacts.load_json(entry.path / "monte_carlo_summary.json")
        if summary is None:
            continue
        scenario_summaries = summary.get("scenario_summaries")
        if not isinstance(scenario_summaries, dict):
            continue
        win_probability = {
            scenario_id: float(scenario["win_probability"])
            for scenario_id, scenario in scenario_summaries.items()
            if isinstance(scenario, dict)
            and isinstance(scenario.get("win_probability"), int | float)
        }
        if not win_probability:
            continue
        return {
            "run_id": entry.run_id,
            "trial_count": summary.get("trial_count"),
            "reconciled_trial_count": summary.get("reconciled_trial_count"),
            "majority_trial_winner": summary.get("majority_trial_winner"),
            "win_probability": win_probability,
        }
    return None


def _calibration_priority(
    run_id: str,
    run_dir: Path,
    validation_status: dict[str, object] | None,
) -> dict[str, object] | None:
    """Join weak-evidence parameters to the newest same-study stored swings."""

    uncertain = validation_status.get("key_uncertain_parameters") if validation_status else None
    if not isinstance(uncertain, list) or not uncertain:
        return None
    study = _run_study(run_dir)
    sensitivity_entry: artifacts.RunEntry | None = None
    sensitivity_summary: dict[str, object] | None = None
    if study is not None:
        for entry in artifacts.list_runs(_OUTPUTS_DIR):
            if entry.kind != "sensitivity-oneway" or entry.run_id == run_id:
                continue
            entry_study = _run_study(entry.path)
            if entry_study is None or not _studies_compatible(entry_study, study):
                continue
            summary = artifacts.load_json(entry.path / "sensitivity_oneway_summary.json")
            if summary is not None:
                sensitivity_entry = entry
                sensitivity_summary = summary
                break

    raw_results = sensitivity_summary.get("parameter_results") if sensitivity_summary else None
    results_by_name = (
        {
            str(result["parameter_name"]): result
            for result in raw_results
            if isinstance(result, dict) and result.get("parameter_name")
        }
        if isinstance(raw_results, list)
        else {}
    )
    rows: list[dict[str, object]] = []
    for evidence in uncertain:
        if not isinstance(evidence, dict) or not isinstance(evidence.get("name"), str):
            continue
        parameter_name = str(evidence["name"])
        sensitivity = results_by_name.get(parameter_name)
        swings = sensitivity.get("swing_sar") if sensitivity else None
        numeric_swings = (
            [float(value) for value in swings.values() if isinstance(value, int | float)]
            if isinstance(swings, dict)
            else []
        )
        if not numeric_swings:
            continue
        low, high = evidence.get("low_value"), evidence.get("high_value")
        status = str(evidence.get("status", "uncertain"))
        confidence = str(evidence.get("confidence", "unknown"))
        rows.append(
            {
                "parameter_name": parameter_name,
                "swing_sar": max(numeric_swings),
                "evidence_status": f"{status} · {confidence} confidence",
                "uncertainty_range": f"{low} — {high}",
                "audit_source": (
                    "recommendation.json · validation_status.key_uncertain_parameters"
                    f"[name={parameter_name}] + sensitivity_oneway_summary.json · "
                    f"parameter_results[name={parameter_name}].swing_sar"
                ),
            }
        )
    rows.sort(key=lambda row: float(cast(float, row["swing_sar"])), reverse=True)
    return {
        "rows": rows[:5],
        "run_id": sensitivity_entry.run_id if sensitivity_entry else None,
        "run_url": f"/run/{sensitivity_entry.run_id}" if sensitivity_entry else None,
        "missing_sensitivity": sensitivity_entry is None,
    }


def _decision_strip(
    financial_ranking: dict[str, object] | None,
    mc_context: dict[str, object] | None,
) -> dict[str, object] | None:
    """Diverging-bar view of the stored net change vs baseline per scenario.

    Bar lengths are the same purely visual |value|/max scaling the KPI
    micro-bars use; every number printed is the stored incremental value.
    """

    if not financial_ranking or not isinstance(financial_ranking.get("rows"), list):
        return None
    raw_rows = cast(list[dict[str, object]], financial_ranking["rows"])
    parsed: list[tuple[dict[str, object], float | None]] = [
        (row, _parse_finite(str(row.get("incremental_net_annual_benefit_sar", ""))))
        for row in raw_rows
    ]
    magnitudes = [abs(value) for _, value in parsed if value is not None]
    if not magnitudes:
        return None
    scale = max(magnitudes)
    mc_wins = cast(dict[str, float], mc_context.get("win_probability", {})) if mc_context else {}
    rows = []
    for row, value in parsed:
        scenario_id = str(row.get("scenario_id", ""))
        win = mc_wins.get(scenario_id)
        rows.append(
            {
                "scenario_id": scenario_id,
                "value": value,
                "display": (
                    _format_sar(value) if value is not None and scenario_id != "baseline" else "0"
                ),
                "is_reference": scenario_id == "baseline",
                "negative": value is not None and value < 0,
                "percent": (
                    round(abs(value) / scale * 100, 1) if value is not None and scale > 0 else 0.0
                ),
                "win_percent": (_format_sar(win * 100) if isinstance(win, int | float) else None),
                "audit_source": str(row.get("annual_audit_source", "")),
            }
        )
    return {"rows": rows, "mc": mc_context}


# Parameter-status warnings all share this backend phrasing; the certification
# panel groups them so eleven near-identical sentences read as one finding.
_STATUS_WARNING_PATTERN = re.compile(
    r"^(?P<parameter>\S+) has status (?P<status>blocked|provisional); (?P<rest>.+)$"
)


def _aggregate_warnings(warnings: object) -> dict[str, object]:
    """Group repeated parameter-status warnings; pass others through verbatim."""

    grouped: dict[str, list[str]] = {}
    grouped_rest = ""
    other: list[str] = []
    if isinstance(warnings, list):
        for warning in warnings:
            message = (
                str(warning.get("message"))
                if isinstance(warning, dict) and warning.get("message")
                else str(warning)
            )
            match = _STATUS_WARNING_PATTERN.match(message)
            if match:
                grouped.setdefault(match.group("status"), []).append(match.group("parameter"))
                grouped_rest = match.group("rest")
            else:
                other.append(message)
    grouped_total = sum(len(parameters) for parameters in grouped.values())
    summary = None
    if grouped_total:
        counts = " and ".join(
            f"{len(parameters)} {status}" for status, parameters in sorted(grouped.items())
        )
        summary = f"{grouped_total} parameters are {counts} — {grouped_rest}"
    return {
        "summary": summary,
        "groups": [
            {"status": status, "parameters": parameters}
            for status, parameters in sorted(grouped.items())
        ],
        "other": other,
        "total": grouped_total + len(other),
    }


def _certification(
    reconciliation: dict[str, object] | None,
    recommendation: dict[str, object] | None,
    validation_status: dict[str, object] | None,
) -> dict[str, object] | None:
    """One approval block joining the run's stored trust signals.

    Reads the reconciliation verdict, the recommendation tier, the parameter
    evidence counts, and the stored warnings. Pure reshaping: every field
    shown exists verbatim in an artifact.
    """

    if not reconciliation and not recommendation and not validation_status:
        return None
    checks = reconciliation.get("checks") if reconciliation else None
    checks = checks if isinstance(checks, list) else []
    recon = None
    if reconciliation is not None:
        recon = {
            "passed": bool(reconciliation.get("passed")),
            "total": len(checks),
            "passed_count": sum(
                1 for check in checks if isinstance(check, dict) and check.get("passed")
            ),
            "checks": [
                {
                    "name": str(check.get("name", "unnamed")),
                    "passed": bool(check.get("passed")),
                    "message": str(check.get("message", "")),
                }
                for check in checks
                if isinstance(check, dict)
            ],
        }

    evidence = None
    if validation_status:
        status_counts = validation_status.get("parameter_counts_by_status")
        status_counts = status_counts if isinstance(status_counts, dict) else {}
        blocked = int(status_counts.get("blocked", 0) or 0)
        provisional = int(status_counts.get("provisional", 0) or 0)
        if blocked:
            # Mirrors the stored warning wording: blocked parameters are
            # permitted for research/sensitivity use only.
            grade = "research/sensitivity use only"
        elif provisional:
            grade = "provisional evidence"
        else:
            grade = "validated evidence"
        evidence = {
            "grade": grade,
            "counts_by_status": status_counts,
            "counts_by_evidence_type": validation_status.get(
                "parameter_counts_by_evidence_type", {}
            ),
            "disclaimer": validation_status.get("disclaimer"),
            "key_uncertain_parameters": validation_status.get("key_uncertain_parameters", []),
        }

    tier = None
    if recommendation and recommendation.get("recommendation_tier"):
        tier = str(recommendation["recommendation_tier"]).replace("_", "-")

    warnings = _aggregate_warnings(recommendation.get("warnings") if recommendation else None)
    return {
        "reconciliation": recon,
        "evidence": evidence,
        "tier": tier,
        "warnings": warnings,
    }


def _chart_event_markers(run_dir: Path) -> list[dict[str, object]]:
    """Return only the action markers the explorer can usefully display.

    Daily dust loading is already represented by the cleanliness track. A
    marker for every scenario and day made the chart unreadable and bloated a
    full-year page with redundant data.
    """

    return [
        {
            "date": marker.get("date"),
            "scenario": marker.get("scenario"),
            "category": marker.get("category"),
            "count": marker.get("count"),
        }
        for marker in artifacts.daily_event_markers(run_dir)
        if marker.get("category") != "contamination"
    ]


def _first_message(items: object) -> str | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("message"):
            return str(item["message"])
        if isinstance(item, str) and item:
            return item
    return None


def _finding_statement(  # noqa: PLR0911, PLR0912
    recommendation: dict[str, object] | None,
    reconciliation: dict[str, object] | None,
    *,
    period_is_full_year: bool = True,
) -> dict[str, str] | None:
    """One plain-language conclusion composed only from stored result fields."""

    checks = reconciliation.get("checks") if reconciliation else None
    if isinstance(checks, list):
        failed = [check for check in checks if isinstance(check, dict) and not check.get("passed")]
        if failed:
            first = failed[0]
            message = str(first.get("message") or "Stored reconciliation check failed")
            return {
                "tone": "fail",
                "text": f"Run not certified — “{message}” ({first.get('name', 'unnamed check')}).",
            }
    if reconciliation is not None and reconciliation.get("passed") is False:
        return {
            "tone": "fail",
            "text": "Run not certified — the stored reconciliation report did not pass.",
        }

    calculation_valid = bool(recommendation and recommendation.get("calculation_valid") is True)
    if recommendation and calculation_valid:
        winner = recommendation.get("winner")
        tied_winners = recommendation.get("tied_winners")
        tied_names = (
            [str(name).capitalize() for name in tied_winners if isinstance(name, str) and name]
            if isinstance(tied_winners, list)
            else []
        )
        period_phrase = "this year" if period_is_full_year else "the configured period"
        if not isinstance(winner, str) or not winner:
            if tied_names:
                return {
                    "tone": "neutral",
                    "text": (
                        f"No single certified winner — {' and '.join(tied_names)} are tied for "
                        f"{period_phrase} within the configured ranking tolerance."
                    ),
                }
            warning = _first_message(recommendation.get("warnings"))
            text = "No certified winner — the stored recommendation has no sole winner."
            if warning:
                text += f" {warning}"
            return {"tone": "warn", "text": text}

        snapshot = recommendation.get("kpi_snapshot")
        winner_kpis = snapshot.get(winner) if isinstance(snapshot, dict) else None
        benefit = (
            winner_kpis.get("net_annual_benefit_sar") if isinstance(winner_kpis, dict) else None
        )
        margin = recommendation.get("decisive_margin_sar")
        raw_tier = recommendation.get("recommendation_tier")
        tier = raw_tier if isinstance(raw_tier, str) else ""
        certified_winner = _certified_winner(recommendation, reconciliation)
        if certified_winner is None:
            warning = _first_message(recommendation.get("warnings"))
            if reconciliation is None:
                text = (
                    f"No certified winner — {winner.capitalize()} ranks first for "
                    f"{period_phrase}, but the reconciliation report is missing or unreadable."
                )
            elif recommendation.get("valid") is False or tier.strip().lower() == "exploratory":
                text = (
                    f"Exploratory result only — {winner.capitalize()} ranks first for "
                    f"{period_phrase}, but no certified winner was accepted."
                )
            else:
                text = (
                    f"No certified winner — {winner.capitalize()} ranks first for "
                    f"{period_phrase}, but required certification fields are incomplete."
                )
            if warning:
                text += f" {warning}"
            return {"tone": "warn", "text": text}

        parts = [f"{certified_winner.capitalize()} wins {period_phrase}"]
        if isinstance(benefit, int | float) and math.isfinite(float(benefit)):
            parts.append(f"net benefit {_format_sar(benefit)} SAR")
        if isinstance(margin, int | float) and math.isfinite(float(margin)):
            parts.append(f"a {_format_sar(margin)} SAR margin over the runner-up")
        display_tier = tier.replace("_", "-")
        if display_tier:
            parts.append(display_tier)
        if isinstance(checks, list):
            parts.append(f"all {len(checks)} checks passed")
        return {"tone": "pass", "text": " — ".join([parts[0], ", ".join(parts[1:])]) + "."}

    warning = _first_message(recommendation.get("warnings") if recommendation else None)
    if warning:
        return {"tone": "warn", "text": f"No certified winner — “{warning}”"}
    if reconciliation and reconciliation.get("passed"):
        return {
            "tone": "neutral",
            "text": (
                "The stored calculations reconcile, but no ranking was accepted for this run's "
                "configured period."
            ),
        }
    return None


def _display_config_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return "[" + ", ".join(_display_config_value(item) for item in value) + "]"
    return str(value)


def _flatten_config(value: object, prefix: str = "") -> dict[str, str]:
    if not isinstance(value, dict):
        return {prefix: _display_config_value(value)} if prefix else {}
    flattened: dict[str, str] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, dict):
            flattened.update(_flatten_config(child, path))
        else:
            flattened[path] = _display_config_value(child)
    return flattened


def _config_diff(run_a: Path, run_b: Path) -> dict[str, object]:
    old = _flatten_config(_resolved_config(run_a))
    new = _flatten_config(_resolved_config(run_b))
    changes = []
    identical = 0
    for path in sorted(set(old) | set(new)):
        before, after = old.get(path, "<missing>"), new.get(path, "<missing>")
        if before == after:
            identical += 1
            continue
        changes.append({"path": path, "before": before, "after": after})
    return {"changes": changes, "identical_count": identical}


def _stored_kpi_values(run_dir: Path) -> dict[str, dict[str, str]]:
    path = run_dir / "scenario_annual_summary.csv"
    if not path.is_file():
        return {}
    header, rows = artifacts.read_csv_rows(path)
    index = {name: position for position, name in enumerate(header)}
    scenario_col = index.get("scenario_name", index.get("scenario_id"))
    if scenario_col is None:
        return {}
    return {
        row[scenario_col]: {
            column: row[position] for column, position in index.items() if position < len(row)
        }
        for row in rows
        if scenario_col < len(row)
    }


def _kpi_diff(run_a: Path, run_b: Path) -> dict[str, object]:
    old, new = _stored_kpi_values(run_a), _stored_kpi_values(run_b)
    preferred = ["baseline", "reactive", "coating"]
    scenarios = preferred + sorted((set(old) | set(new)) - set(preferred))
    rows: list[dict[str, object]] = []
    identical = 0
    for scenario in scenarios:
        if scenario not in old and scenario not in new:
            continue
        for label, column, direction in _KPI_FIELDS:
            before, after = old.get(scenario, {}).get(column), new.get(scenario, {}).get(column)
            before_number, after_number = _parse_finite(before or ""), _parse_finite(after or "")
            same = before == after or (
                before_number is not None
                and after_number is not None
                and before_number == after_number
            )
            if same:
                identical += 1
                continue
            delta = (
                after_number - before_number
                if before_number is not None and after_number is not None
                else None
            )
            if delta is None:
                delta_display, trend, outcome = "changed", "→", "neutral"
            else:
                trend = "↑" if delta > 0 else "↓" if delta < 0 else "→"
                delta_display = f"{'+' if delta > 0 else ''}{_display_number(str(delta))}"
                if direction is None or delta == 0:
                    outcome = "neutral"
                else:
                    improved = (direction == "higher" and delta > 0) or (
                        direction == "lower" and delta < 0
                    )
                    outcome = "better" if improved else "worse"
            rows.append(
                {
                    "scenario": scenario,
                    "label": label,
                    "column": column,
                    "before": _display_number(before) if before is not None else "–",
                    "after": _display_number(after) if after is not None else "–",
                    "delta": delta_display,
                    "trend": trend,
                    "outcome": outcome,
                    "direction": direction,
                }
            )
    return {"rows": rows, "identical_count": identical}


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------


_RUN_CARD_RESULT_ARTIFACTS = {
    "fetch-weather": "summary.json",
    "run-baseline": "summary.json",
    "run-clean": "summary.json",
    "compare-multi-year": "multi_year_summary.json",
    "monte-carlo": "monte_carlo_summary.json",
    "sensitivity-oneway": "sensitivity_oneway_summary.json",
    "sensitivity-winner-map": "sensitivity_twoway_summary.json",
    "break-even": "breakeven_report.json",
    "validate-weather": "phase35_weather_report.json",
    "validate-phase-3-5": "phase35_summary.json",
    "validate-field": "field_validation_report.json",
}


def _run_card_status(run: artifacts.RunEntry) -> dict[str, str]:  # noqa: PLR0911, PLR0912
    """Describe stored result state without confusing it with process failure.

    A completed comparison can be internally consistent yet intentionally
    decline to certify a winner.  That is a result state, not a crashed job.
    Only artifact evidence is used here; missing or malformed artifacts stay
    visibly incomplete/unknown instead of being promoted to success.
    """

    if run.kind == "compare-all-scenarios":
        recommendation = artifacts.load_json(run.path / "recommendation.json")
        if recommendation is None:
            return {
                "status_code": "incomplete",
                "status_label": "Incomplete",
                "status_detail": "Expected recommendation.json is missing or unreadable.",
            }

        reconciliation = artifacts.load_json(run.path / "reconciliation_report.json")
        raw_valid = recommendation.get("valid")
        raw_calculation_valid = recommendation.get("calculation_valid")
        winner = recommendation.get("winner")
        raw_tier = recommendation.get("recommendation_tier")
        tier = raw_tier.strip().lower() if isinstance(raw_tier, str) else ""

        if reconciliation is None:
            return {
                "status_code": "incomplete",
                "status_label": "Incomplete",
                "status_detail": "Expected reconciliation_report.json is missing or unreadable.",
            }
        if not isinstance(reconciliation.get("passed"), bool):
            return {
                "status_code": "incomplete",
                "status_label": "Incomplete",
                "status_detail": "The reconciliation report is missing its required verdict.",
            }

        failed_reconciliation = reconciliation.get("passed") is False
        explicitly_not_accepted = (
            raw_valid is False or raw_calculation_valid is False or tier == "exploratory"
        )
        if failed_reconciliation or explicitly_not_accepted:
            detail = _first_message(recommendation.get("warnings"))
            if failed_reconciliation:
                checks = reconciliation.get("checks") if reconciliation is not None else None
                first_failed = (
                    next(
                        (
                            check
                            for check in checks
                            if isinstance(check, dict) and check.get("passed") is False
                        ),
                        None,
                    )
                    if isinstance(checks, list)
                    else None
                )
                if first_failed is not None and first_failed.get("message"):
                    detail = str(first_failed["message"])
                detail = detail or "Stored reconciliation checks did not pass."
            else:
                detail = detail or "The stored recommendation was not accepted as decision-grade."
            return {
                "status_code": "not_certified",
                "status_label": "Not certified",
                "status_detail": detail,
            }

        evidence_complete = (
            isinstance(raw_valid, bool)
            and isinstance(raw_calculation_valid, bool)
            and isinstance(raw_tier, str)
            and bool(raw_tier.strip())
        )
        if not evidence_complete:
            return {
                "status_code": "incomplete",
                "status_label": "Incomplete",
                "status_detail": "The stored recommendation is missing required decision fields.",
            }
        if not isinstance(winner, str) or not winner:
            tied_winners = recommendation.get("tied_winners")
            if isinstance(tied_winners, list) and tied_winners:
                return {
                    "status_code": "not_certified",
                    "status_label": "No single winner",
                    "status_detail": (
                        "Top scenarios are tied within the configured ranking tolerance."
                    ),
                }
            return {
                "status_code": "incomplete",
                "status_label": "Incomplete",
                "status_detail": "The stored recommendation is missing its sole-winner field.",
            }
        if _certified_winner(recommendation, reconciliation) is not None:
            return {
                "status_code": "certified",
                "status_label": "Certified",
                "status_detail": "The stored recommendation was accepted as decision-grade.",
            }
        return {
            "status_code": "not_certified",
            "status_label": "Not certified",
            "status_detail": "The stored comparison did not produce a certified winner.",
        }

    expected_artifact = _RUN_CARD_RESULT_ARTIFACTS.get(run.kind)
    if expected_artifact is not None:
        if artifacts.load_json(run.path / expected_artifact) is not None:
            return {
                "status_code": "complete",
                "status_label": "Complete",
                "status_detail": f"Stored analysis result available in {expected_artifact}.",
            }
        return {
            "status_code": "incomplete",
            "status_label": "Incomplete",
            "status_detail": f"Expected {expected_artifact} is missing or unreadable.",
        }

    return {
        "status_code": "unknown",
        "status_label": "Status unknown",
        "status_detail": "This run type has no recognized result-status artifact.",
    }


def _run_cards(
    grouped: list[tuple[artifacts.RunEntry, dict[str, str]]],
    previous_study_key: str | None,
) -> list[dict[str, object]]:
    """Presentation data for one batch of study-grouped run cards.

    ``previous_study_key`` is the study of the card just before this batch in
    the full grouped order, so an appended page repeats no study header.
    """

    runs: list[dict[str, object]] = []
    last_key = previous_study_key
    for run, study in grouped:
        site = _resolved_config_section(run.path, "site").get("name")
        status = _run_card_status(run)
        fingerprint = study.get("fingerprint", "")
        runs.append(
            {
                "run_id": run.run_id,
                "created": run.created,
                "created_display": _human_created(run.created, run.run_id),
                "kind": run.kind,
                "kind_label": _RUN_KIND_LABELS.get(run.kind, run.kind.replace("-", " ")),
                "site": site if isinstance(site, str) else None,
                "winner": run.winner,
                "valid": run.valid,
                "margin_display": (
                    _format_sar(run.margin_sar)
                    if run.margin_sar is not None and math.isfinite(run.margin_sar)
                    else None
                ),
                "win_percent": (
                    _format_sar(run.win_probability * 100)
                    if run.win_probability is not None
                    else None
                ),
                "study_key": study["key"],
                "study_label": study["label"],
                "study_short_id": fingerprint[:8].upper() if fingerprint else "UNFILED",
                "new_study": study["key"] != last_key,
                "provenance": (
                    "test"
                    if run.kind in _TECHNICAL_RUN_KINDS
                    or run.run_id.lower().startswith(("test-", "fixture-", "offline-fixture-"))
                    else "study"
                ),
                **status,
                "fingerprint_url": f"/api/runs/{run.run_id}/fingerprint",
            }
        )
        last_key = study["key"]
    return runs


def _dossier_run_fields(entry: artifacts.RunEntry) -> dict[str, str]:
    return {
        "run_id": entry.run_id,
        "run_url": f"/run/{entry.run_id}",
        "created": _human_created(entry.created, entry.run_id),
    }


def _dossier_comparison(entry: artifacts.RunEntry | None) -> dict[str, object] | None:
    if entry is None:
        return None
    recommendation = artifacts.load_json(entry.path / "recommendation.json")
    if recommendation is None:
        return None
    reconciliation = artifacts.load_json(entry.path / "reconciliation_report.json")
    winner = _certified_winner(recommendation, reconciliation)
    return {
        **_dossier_run_fields(entry),
        "winner": winner,
        "margin_sar": recommendation.get("decisive_margin_sar") if winner else None,
        "recommendation_tier": recommendation.get("recommendation_tier"),
        "calculation_valid": bool(
            recommendation.get("calculation_valid") is True
            and reconciliation is not None
            and reconciliation.get("passed") is True
        ),
        "audit_source": "recommendation.json · stored winner and decisive_margin_sar",
    }


def _dossier_monte_carlo(entry: artifacts.RunEntry | None) -> dict[str, object] | None:
    if entry is None:
        return None
    summary = artifacts.load_json(entry.path / "monte_carlo_summary.json")
    scenario_summaries = summary.get("scenario_summaries") if summary else None
    if summary is None or not isinstance(scenario_summaries, dict):
        return None
    probabilities = [
        {
            "scenario_id": str(scenario_id),
            "win_probability": scenario.get("win_probability"),
            "audit_source": (
                f"monte_carlo_summary.json · scenario_summaries.{scenario_id}.win_probability"
            ),
        }
        for scenario_id, scenario in scenario_summaries.items()
        if isinstance(scenario, dict) and isinstance(scenario.get("win_probability"), int | float)
    ]
    return {
        **_dossier_run_fields(entry),
        "trial_count": summary.get("trial_count"),
        "reconciled_trial_count": summary.get("reconciled_trial_count"),
        "majority_trial_winner": summary.get("majority_trial_winner"),
        "probabilities": probabilities,
    }


def _dossier_oneway(entry: artifacts.RunEntry | None) -> dict[str, object] | None:
    if entry is None:
        return None
    tornado = _oneway_tornado(artifacts.load_json(entry.path / "sensitivity_oneway_summary.json"))
    if tornado is None:
        return None
    return {
        **_dossier_run_fields(entry),
        "top_drivers": cast(list[dict[str, object]], tornado["entries"])[:5],
        "audit_source": "sensitivity_oneway_summary.json · parameter_results[].swing_sar",
    }


def _dossier_breakeven(entry: artifacts.RunEntry | None) -> dict[str, object] | None:
    if entry is None:
        return None
    report = artifacts.load_json(entry.path / "breakeven_report.json")
    if report is None:
        return None
    crossovers = report.get("crossover_values")
    return {
        **_dossier_run_fields(entry),
        "parameter_name": report.get("parameter_name"),
        "scenario_a": report.get("scenario_a"),
        "scenario_b": report.get("scenario_b"),
        "crossovers": crossovers if isinstance(crossovers, list) else [],
        "message": report.get("message"),
        "audit_source": "breakeven_report.json · stored crossover_values",
    }


def _dossier_winner_map(entry: artifacts.RunEntry | None) -> dict[str, object] | None:
    if entry is None:
        return None
    summary = artifacts.load_json(entry.path / "sensitivity_twoway_summary.json")
    if summary is None:
        return None
    raw_grid = summary.get("grid")
    winners: list[str] = []
    if isinstance(raw_grid, list):
        for point in raw_grid:
            winner = point.get("winner") if isinstance(point, dict) else None
            if isinstance(winner, str) and winner not in winners:
                winners.append(winner)
    return {
        **_dossier_run_fields(entry),
        "parameter_a": summary.get("parameter_a"),
        "parameter_b": summary.get("parameter_b"),
        "grid_points": summary.get("grid_points"),
        "failed_grid_point_count": summary.get("failed_grid_point_count"),
        "winners": winners,
        "audit_source": "sensitivity_twoway_summary.json · stored grid identity and winners",
    }


def _study_dossier_context(key: str) -> dict[str, object]:
    """Latest stored evidence of each analysis kind for one study identity."""

    candidates: list[tuple[artifacts.RunEntry, dict[str, str]]] = []
    for entry in artifacts.list_runs(_OUTPUTS_DIR):
        entry_study = _run_study(entry.path)
        if entry_study is not None and entry_study["key"] == key:
            candidates.append((entry, entry_study))
    if not candidates:
        raise HTTPException(status_code=404, detail="Study not found")

    # The URL identifies the decision configuration. Starting with its newest
    # run, form one pairwise-compatible evidence set so a checksum-less legacy
    # record cannot bridge two known-different weather/economics snapshots.
    study = dict(candidates[0][1])
    compatible_candidates: list[tuple[artifacts.RunEntry, dict[str, str]]] = []
    for candidate in candidates:
        _, candidate_study = candidate
        if all(
            _studies_compatible(candidate_study, accepted_study)
            for _, accepted_study in compatible_candidates
        ):
            compatible_candidates.append(candidate)
    matching = [entry for entry, _ in compatible_candidates]

    by_kind: dict[str, artifacts.RunEntry] = {}
    expected_artifact = {
        "comparison": "recommendation.json",
        "monte-carlo": "monte_carlo_summary.json",
        "sensitivity-oneway": "sensitivity_oneway_summary.json",
        "break-even": "breakeven_report.json",
        "sensitivity-winner-map": "sensitivity_twoway_summary.json",
    }
    for entry in matching:
        dossier_kind = (
            "comparison"
            if entry.kind in ("compare-all-scenarios", "compare-multi-year")
            else entry.kind
        )
        artifact_name = expected_artifact.get(dossier_kind)
        if artifact_name is not None and (entry.path / artifact_name).is_file():
            by_kind.setdefault(dossier_kind, entry)
    evidence = {
        "comparison": _dossier_comparison(by_kind.get("comparison")),
        "monte_carlo": _dossier_monte_carlo(by_kind.get("monte-carlo")),
        "oneway": _dossier_oneway(by_kind.get("sensitivity-oneway")),
        "breakeven": _dossier_breakeven(by_kind.get("break-even")),
        "winner_map": _dossier_winner_map(by_kind.get("sensitivity-winner-map")),
    }
    records = [
        {
            **_dossier_run_fields(entry),
            "kind": entry.kind,
            "kind_label": _RUN_KIND_LABELS.get(entry.kind, entry.kind.replace("-", " ")),
            "summary": _related_run_summary(entry),
        }
        for entry in matching
    ]
    return {
        "study": study,
        **evidence,
        "records": records,
        "gaps": {name: value is None for name, value in evidence.items()},
        "context_flags": {
            "evidence_records": "immutable_run_snapshots",
            "evidence_selection": "live_archive_context",
            "compatibility_basis": "decision_config_fingerprint_v2",
        },
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    config_names = _config_names()
    run_entries = artifacts.list_runs(_OUTPUTS_DIR)
    grouped = _grouped_run_entries(run_entries)
    total_runs = len(grouped)
    total_pages = max(1, math.ceil(total_runs / _RUNS_PER_PAGE))
    runs = _run_cards(grouped[:_RUNS_PER_PAGE], previous_study_key=None)
    job_records = jobs.records()
    visible_jobs = [record for record in job_records if record.get("status") != "done"]
    job_history = [
        record
        for record in job_records
        if record.get("status") == "done" and isinstance(record.get("elapsed_seconds"), int | float)
    ]
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "default_config_name": DEFAULT_CONFIG_NAME,
            "default_config_label": DEFAULT_CONFIG_LABEL,
            "configs": config_names,
            "config_periods": _config_periods(config_names),
            "runs": runs,
            "run_total": total_runs,
            "run_total_pages": total_pages,
            "run_kinds": sorted({entry.kind for entry in run_entries}),
            "jobs": visible_jobs,
            "job_history": job_history,
            "parameters": _parameter_catalog(),
            "config_cockpits": _config_cockpits(config_names, run_entries),
        },
    )


@app.get("/study/{key:path}", response_class=HTMLResponse)
def study_dossier(request: Request, key: str) -> HTMLResponse:
    """One study's newest stored verdict from each sibling analysis kind."""

    context = _study_dossier_context(key)
    return templates.TemplateResponse(request, "study.html", context)


@app.get("/api/run-pages/{page}", response_class=HTMLResponse)
def run_page_fragment(request: Request, page: int) -> HTMLResponse:
    """Return one lightweight card batch for the scrolling run archive."""

    grouped = _grouped_run_entries(artifacts.list_runs(_OUTPUTS_DIR))
    total_pages = max(1, math.ceil(len(grouped) / _RUNS_PER_PAGE))
    if page < 1 or page > total_pages:
        raise HTTPException(status_code=404, detail="Run archive page not found")
    start = (page - 1) * _RUNS_PER_PAGE
    previous_study_key = grouped[start - 1][1]["key"] if start > 0 and grouped else None
    return templates.TemplateResponse(
        request,
        "_run_cards.html",
        {
            "runs": _run_cards(
                grouped[start : start + _RUNS_PER_PAGE],
                previous_study_key=previous_study_key,
            )
        },
        headers={"X-Run-Total-Pages": str(total_pages)},
    )


@app.get("/run/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: str) -> HTMLResponse:
    run_dir = _run_dir_or_404(run_id)
    kind = artifacts._detect_kind(run_id)
    provenance = _provenance(run_dir)
    artifact_files = artifacts.list_artifacts(run_dir)
    context: dict[str, object] = {
        "run_id": run_id,
        "kind": kind,
        "artifacts": artifact_files,
        "artifact_summary": {
            "count": len(artifact_files),
            "total_bytes": sum(cast(int, file["size_bytes"]) for file in artifact_files),
        },
        "artifact_preview_endpoint": f"/api/runs/{run_id}/artifact-preview",
        "plots": [f["name"] for f in artifact_files if str(f["name"]).endswith(".png")],
        "summary_text": artifacts.text_preview(run_dir / "summary.txt"),
        "provenance": provenance,
        "fingerprint": artifacts.run_fingerprint(run_dir),
        "rerun_supported": kind in _RERUNNABLE_KINDS,
        "document_status": "ANALYSIS RECORD",
        "related": _related_runs(run_id, run_dir),
        "context_flags": {
            "primary_run": "immutable_snapshot",
            "cross_run_joins": "live_archive_context",
            "compatibility_basis": "decision_config_fingerprint_v2",
        },
    }
    context.update(_comparison_period_context(run_dir))

    if kind == "compare-all-scenarios":
        ranking = artifacts.load_json(run_dir / "scenario_ranking.json")
        recommendation = artifacts.load_json(run_dir / "recommendation.json")
        reconciliation = artifacts.load_json(run_dir / "reconciliation_report.json")
        comparison_metadata = artifacts.load_json(run_dir / "metadata.json") or artifacts.load_json(
            run_dir / "comparison_metadata.json"
        )
        raw_validation_status = (
            recommendation.get("validation_status") if recommendation is not None else None
        )
        validation_status = (
            raw_validation_status if isinstance(raw_validation_status, dict) else None
        )
        certified_winner = _certified_winner(recommendation, reconciliation)
        context.update(
            {
                "ranking": ranking,
                "recommendation": recommendation,
                "validation_status": validation_status,
                "reconciliation": reconciliation,
                "certification": _certification(reconciliation, recommendation, validation_status),
                "calibration_priority": _calibration_priority(run_id, run_dir, validation_status),
                "headline": _headline_cards(
                    recommendation,
                    reconciliation,
                    period_is_full_year=bool(context["period_is_full_year"]),
                ),
                "finding": _finding_statement(
                    recommendation,
                    reconciliation,
                    period_is_full_year=bool(context["period_is_full_year"]),
                ),
                "result_certified": certified_winner is not None,
                "document_status": "VERIFIED" if certified_winner is not None else "HOLD",
                "daily_energy": artifacts.daily_energy_series(run_dir),
                "daily_clean_reference": artifacts.daily_clean_reference_series(run_dir),
                "daily_rainfall": artifacts.daily_rainfall_series(run_dir),
                "daily_humidity": artifacts.daily_relative_humidity_series(run_dir),
                "daily_weather": artifacts.daily_weather_diagnostics(run_dir),
                "daily_event_markers": _chart_event_markers(run_dir),
                "daily_loss": artifacts.daily_series(run_dir, "energy_loss_kwh"),
                "daily_soiling": artifacts.daily_cleanliness_series(run_dir),
                "daily_cumgain": artifacts.daily_series(
                    run_dir, "cumulative_energy_gain_vs_baseline_kwh"
                ),
                "daily_bird_loss": artifacts.daily_series(run_dir, "extension_bird_loss_fraction"),
                "daily_water_collected": artifacts.daily_series(
                    run_dir, "extension_actually_collected_water_liters"
                ),
                "daily_queue": artifacts.daily_series(run_dir, "extension_queue_length"),
                "detection_performance": _detection_performance(run_dir),
                "coating_service_life": _coating_service_life(run_dir),
                "hourly_detail_endpoint": f"/api/runs/{run_id}/hourly",
            }
        )
        annual_path = run_dir / "scenario_annual_summary.csv"
        if annual_path.is_file():
            header, rows = artifacts.read_csv_rows(annual_path)
            context["annual_summary"] = {"header": header, "rows": rows}
            context["kpi_table"] = _kpi_table(
                header,
                rows,
                period_is_full_year=bool(context["period_is_full_year"]),
            )
            context["water_balance"] = _water_balance_card(header, rows)
            context["financial_ranking"] = _financial_ranking(
                header,
                rows,
                ranking,
                comparison_metadata,
            )
            context["decision_strip"] = _decision_strip(
                cast("dict[str, object] | None", context["financial_ranking"]),
                _sibling_mc_context(run_id, run_dir),
            )
        if (run_dir / "config_resolved.yaml").is_file():
            context["dew_simulator"] = {
                "endpoint": f"/api/runs/{run_id}/dew-simulator",
                "relative_humidity_pct": 80,
                "air_temperature_c": 25,
                "wind_speed_m_s": 2,
            }
        cost_path = run_dir / "scenario_cost_summary.csv"
        if cost_path.is_file():
            header, rows = artifacts.read_csv_rows(cost_path, limit=200)
            context["cost_table"] = _cost_table(header, rows, reconciliation)
        return templates.TemplateResponse(request, "run_comparison.html", context)

    context.update(_analysis_page_context(kind, run_dir))
    return templates.TemplateResponse(request, "run_analysis.html", context)


def _analysis_page_context(kind: str, run_dir: Path) -> dict[str, object]:
    """Extra stored-artifact context for the non-comparison analysis pages."""

    context: dict[str, object] = {}
    if kind == "monte-carlo":
        mc_summary = artifacts.load_json(run_dir / "monte_carlo_summary.json")
        context["mc_summary"] = mc_summary
        if isinstance(mc_summary, dict) and mc_summary.get("majority_trial_winner"):
            winner = str(mc_summary["majority_trial_winner"])
            scenario_summaries = mc_summary.get("scenario_summaries")
            winner_summary = (
                scenario_summaries.get(winner) if isinstance(scenario_summaries, dict) else None
            )
            probability = (
                winner_summary.get("win_probability") if isinstance(winner_summary, dict) else None
            )
            probability_text = (
                f" with {_format_sar(float(probability) * 100)}% win probability"
                if isinstance(probability, int | float)
                else ""
            )
            context["finding"] = {
                "tone": "neutral",
                "text": (
                    f"{winner.capitalize()} is the majority trial winner{probability_text} "
                    "across "
                    f"{mc_summary.get('reconciled_trial_count', 'the stored')} reconciled trials."
                ),
            }
        trials_path = run_dir / "monte_carlo_trials.csv"
        if trials_path.is_file():
            header, rows = artifacts.read_csv_rows(trials_path, limit=1000)
            context["mc_trials"] = _mc_trials_series(header, rows)
    elif kind == "sensitivity-oneway":
        context["generic_summary"] = artifacts.load_json(run_dir / "summary.json")
        context["oneway_tornado"] = _oneway_tornado(
            artifacts.load_json(run_dir / "sensitivity_oneway_summary.json")
        )
    elif kind == "sensitivity-winner-map":
        context["generic_summary"] = artifacts.load_json(run_dir / "summary.json")
        context["twoway_grid"] = _twoway_grid(
            artifacts.load_json(run_dir / "sensitivity_twoway_summary.json")
        )
    elif kind == "break-even":
        context["generic_summary"] = artifacts.load_json(run_dir / "summary.json")
        breakeven_report = artifacts.load_json(run_dir / "breakeven_report.json")
        context["breakeven"] = breakeven_report
        context["breakeven_chart"] = _breakeven_chart(breakeven_report)
    else:
        context["generic_summary"] = artifacts.load_json(run_dir / "summary.json")
    return context


@app.get("/compare-runs", response_class=HTMLResponse)
def compare_runs(request: Request, a: str, b: str) -> HTMLResponse:
    if a == b:
        raise HTTPException(status_code=400, detail="Choose two different runs to compare")
    runs = []
    run_dirs: list[Path] = []
    studies: list[dict[str, str] | None] = []
    for run_id in (a, b):
        run_dir = _run_dir_or_404(run_id)
        run_dirs.append(run_dir)
        studies.append(_run_study(run_dir))
        runs.append(
            {
                "run_id": run_id,
                "provenance": _provenance(run_dir),
                "kind": artifacts._detect_kind(run_id),
                "fingerprint": artifacts.run_fingerprint(run_dir),
            }
        )
    # Before/after framing only makes sense for iterations of one study; two
    # different sites or assumption sets are neutral A/B alternatives.
    same_study = (
        studies[0] is not None
        and studies[1] is not None
        and _studies_compatible(studies[0], studies[1])
    )
    return templates.TemplateResponse(
        request,
        "compare_runs.html",
        {
            "runs": runs,
            "diff_mode": "temporal" if same_study else "neutral",
            "config_diff": _config_diff(run_dirs[0], run_dirs[1]),
            "kpi_diff": _kpi_diff(run_dirs[0], run_dirs[1]),
        },
    )


@app.get("/config/{name}", response_class=HTMLResponse)
def config_page(request: Request, name: str) -> HTMLResponse:
    path = _config_path(name)
    return templates.TemplateResponse(
        request,
        "config.html",
        {
            "name": name,
            "content": path.read_text(encoding="utf-8"),
            "is_default": name == DEFAULT_CONFIG_NAME,
            "default_config_label": DEFAULT_CONFIG_LABEL,
        },
    )


# --------------------------------------------------------------------------
# JSON API
# --------------------------------------------------------------------------


@app.get("/api/configs/{name}/parameters")
def config_parameters(name: str) -> JSONResponse:
    """Return the sensitivity catalog selected by one dashboard config."""
    return JSONResponse(_parameter_catalog(_config_path(name)))


@app.get("/api/configs/{name}/factory-default")
def config_factory_default(name: str) -> JSONResponse:
    """Return the immutable Riyadh preset for resetting the editable Default config."""
    _config_path(name)
    if name != DEFAULT_CONFIG_NAME:
        raise HTTPException(status_code=404, detail="Factory reset is available only for Default")
    return JSONResponse({"content": _RIYADH_DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")})


@app.get("/api/command-index")
def command_index() -> JSONResponse:
    """Lightweight run/config listing for the keyboard command palette.

    Names and stored identity fields only — the palette is navigation, so this
    reuses exactly what the run cards already show.
    """

    runs = [
        {
            "run_id": entry.run_id,
            "kind": entry.kind,
            "kind_label": _RUN_KIND_LABELS.get(entry.kind, entry.kind.replace("-", " ")),
            "site": study["label"],
            "winner": entry.winner,
            "created": _human_created(entry.created, entry.run_id),
        }
        for entry, study in _grouped_run_entries(artifacts.list_runs(_OUTPUTS_DIR))[:200]
    ]
    return JSONResponse(
        {"runs": runs, "configs": _config_names()},
        headers={"Cache-Control": "private, max-age=30"},
    )


@app.get("/api/runs/{run_id}/fingerprint")
def run_fingerprint(run_id: str) -> JSONResponse:
    """Load a run-card fingerprint on demand instead of blocking the run list."""

    run_dir = _run_dir_or_404(run_id)
    return JSONResponse(
        artifacts.run_fingerprint(run_dir) or {},
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.get("/api/runs/{run_id}/hourly/{day}")
def run_hourly_detail(run_id: str, day: date) -> JSONResponse:
    """Select one date's stored weather and clean-reference hourly columns."""

    run_dir = _run_dir_or_404(run_id)
    weather_path = run_dir / "weather_hourly.csv"
    clean_path = run_dir / "clean_energy_hourly.csv"
    if not weather_path.is_file() or not clean_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Run does not contain both stored hourly weather and clean-reference files.",
        )

    weather_header, weather_rows = artifacts.read_csv_rows(weather_path)
    clean_header, clean_rows = artifacts.read_csv_rows(clean_path)
    weather_columns = (
        "timestamp",
        "ghi_w_m2",
        "temp_air_c",
        "wind_speed_m_s",
        "relative_humidity_pct",
    )
    clean_columns = ("timestamp", "clean_ac_energy_kwh")
    if any(column not in weather_header for column in weather_columns) or any(
        column not in clean_header for column in clean_columns
    ):
        raise HTTPException(
            status_code=409,
            detail="Stored hourly files do not contain the dashboard's expected columns.",
        )

    weather_index = {column: weather_header.index(column) for column in weather_columns}
    clean_timestamp = clean_header.index("timestamp")
    clean_energy = clean_header.index("clean_ac_energy_kwh")
    day_text = day.isoformat()
    clean_by_timestamp = {
        row[clean_timestamp]: _parse_finite(row[clean_energy])
        for row in clean_rows
        if len(row) > max(clean_timestamp, clean_energy) and row[clean_timestamp][:10] == day_text
    }
    selected = [
        row
        for row in weather_rows
        if len(row) > max(weather_index.values())
        and row[weather_index["timestamp"]][:10] == day_text
    ]
    if not selected:
        raise HTTPException(status_code=404, detail=f"No stored hourly rows for {day_text}.")

    timestamps = [row[weather_index["timestamp"]] for row in selected]
    payload: dict[str, object] = {
        "date": day_text,
        "timestamps": timestamps,
        "ghi_w_m2": [_parse_finite(row[weather_index["ghi_w_m2"]]) for row in selected],
        "temp_air_c": [_parse_finite(row[weather_index["temp_air_c"]]) for row in selected],
        "wind_speed_m_s": [_parse_finite(row[weather_index["wind_speed_m_s"]]) for row in selected],
        "relative_humidity_pct": [
            _parse_finite(row[weather_index["relative_humidity_pct"]]) for row in selected
        ],
        "clean_ac_energy_kwh": [clean_by_timestamp.get(timestamp) for timestamp in timestamps],
        "sources": [
            "weather_hourly.csv · stored timestamp/ghi/temp/wind/humidity columns",
            "clean_energy_hourly.csv · stored timestamp/clean_ac_energy_kwh columns",
        ],
    }
    return JSONResponse(payload, headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/runs/{run_id}/dew-simulator")
def run_dew_simulator(
    run_id: str,
    relative_humidity_pct: float = Query(default=80.0, ge=1.0, le=100.0),
    air_temperature_c: float = Query(default=25.0, ge=-40.0, le=70.0),
    wind_speed_m_s: float = Query(default=2.0, ge=0.0, le=40.0),
) -> JSONResponse:
    """Evaluate one night hour using the run's immutable coating configuration."""

    run_dir = _run_dir_or_404(run_id)
    config_path = run_dir / "config_resolved.yaml"
    if not config_path.is_file():
        raise HTTPException(
            status_code=409,
            detail="Run has no config_resolved.yaml for the dew simulator.",
        )
    try:
        config = load_config(config_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Run configuration cannot be loaded: {exc}",
        ) from exc
    result = simulate_nighttime_dew(
        config,
        air_temperature_c=air_temperature_c,
        relative_humidity_pct=relative_humidity_pct,
        wind_speed_m_s=wind_speed_m_s,
    )
    return JSONResponse(
        result.to_record(),
        headers={"Cache-Control": "no-store"},
    )


class LaunchRequest(BaseModel):
    kind: str
    config: str = "default.yaml"
    start_date: date | None = None
    end_date: date | None = None
    trials: int = Field(default=25, ge=2, le=500)
    base_seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    steps: int = Field(default=5, ge=3, le=21)
    parameters: list[str] | None = Field(default=None, max_length=100)
    parameter_a: str | None = None
    parameter_b: str | None = None
    grid_steps: int = Field(default=5, ge=3, le=15)
    parameter: str | None = None
    scenario_a: str = "coating"
    scenario_b: str = "baseline"

    @model_validator(mode="after")
    def validate_launch_options(self) -> LaunchRequest:
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date and end_date must be supplied together")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date must be on or after start_date")
        return self


def _load_run_config(config_path: Path, options: LaunchRequest) -> SolarCleanConfig:
    """Load a config with an optional whole-local-day launch override."""
    config = load_config(config_path)
    if options.start_date is None or options.end_date is None:
        return config
    timezone = ZoneInfo(config.simulation.target_timezone)
    start = datetime.combine(options.start_date, datetime_time.min, tzinfo=timezone)
    end = datetime.combine(options.end_date, datetime_time(hour=23), tzinfo=timezone)
    return load_config(
        config_path,
        overrides={"simulation": {"start": start, "end": end}},
    )


def _headline_cards(
    recommendation: dict[str, object] | None,
    reconciliation: dict[str, object] | None,
    *,
    period_is_full_year: bool = True,
) -> list[dict[str, str]] | None:
    """Top-of-page cards for a sole winner that passed every certification gate."""
    winner = _certified_winner(recommendation, reconciliation)
    if recommendation is None or winner is None:
        return None
    snapshot = recommendation.get("kpi_snapshot")
    winner_kpis = snapshot.get(winner) if isinstance(snapshot, dict) else None
    if not isinstance(winner_kpis, dict):
        winner_kpis = {}
    raw_tier = recommendation.get("recommendation_tier")
    tier = str(raw_tier) if raw_tier is not None else ""
    winner_label = {
        "decision_grade": "Decision-grade winner",
        "calibrated": "Calibrated winner",
    }.get(tier, "Winner under assumptions")
    cards = [
        {
            "label": winner_label,
            "value": winner,
            "unit": "",
            "audit_source": "recommendation.json · winner",
            "audit_detail": f"Stored certified winner = {winner}",
        }
    ]
    benefit_period = "annual" if period_is_full_year else "configured-period"
    sar_unit = "SAR/year" if period_is_full_year else "SAR/configured period"
    energy_unit = "kWh/year" if period_is_full_year else "kWh/configured period"
    baseline_won = winner == "baseline"
    margin = recommendation.get("decisive_margin_sar")
    if isinstance(margin, int | float) and math.isfinite(margin):
        cards.append(
            {
                # When doing nothing wins, the stored margin IS the best
                # mitigation's shortfall — same number, honest label.
                "label": (
                    "Best mitigation falls short by" if baseline_won else "Margin over runner-up"
                ),
                "value": _format_sar(margin),
                "unit": sar_unit,
                "audit_source": "recommendation.json · decisive_margin_sar",
                "audit_detail": "Stored margin between the first- and second-ranked strategies.",
            }
        )
    for label, key, unit in (
        (f"Total net {benefit_period} benefit", "net_annual_benefit_sar", sar_unit),
        ("Energy gain vs baseline", "energy_gain_vs_baseline_kwh", energy_unit),
        ("Incremental payback", "incremental_payback_years_vs_baseline", "years"),
    ):
        if baseline_won and key == "energy_gain_vs_baseline_kwh":
            continue  # baseline vs itself is 0 by definition — an empty slot, not a fact
        value = winner_kpis.get(key)
        if isinstance(value, int | float) and math.isfinite(float(value)):
            cards.append(
                {
                    "label": label,
                    "value": _format_sar(value),
                    "unit": unit,
                    "audit_source": f"recommendation.json · kpi_snapshot.{winner}.{key}",
                    "audit_detail": f"Stored {key} for the certified winner.",
                }
            )
    return cards


# Run-directory kind -> launch kind, for the re-run button.
_RERUNNABLE_KINDS: dict[str, str] = {
    "compare-all-scenarios": "compare",
    "monte-carlo": "monte-carlo",
    "sensitivity-oneway": "sensitivity-oneway",
    "sensitivity-winner-map": "winner-map",
    "break-even": "break-even",
}


def _make_work(options: LaunchRequest, config_path: Path) -> Callable[[Job], Path]:
    """Build the background work function for a launch or re-run request."""

    def work(job: Job) -> Path:
        config = _load_run_config(config_path, options)
        parameter_registry_path = _registry_path(config_path)
        if options.kind == "compare":
            job.detail = "Running baseline, reactive, and coating against one event tape"
            return (
                CompareAllScenarios(
                    config,
                    progress_callback=job.report_progress,
                    parameter_registry_path=parameter_registry_path,
                )
                .run()
                .output_directory
            )
        if options.kind == "monte-carlo":
            job.detail = f"Running {options.trials} seeded trials"
            mc_outcome = MonteCarloExperiment(
                config,
                trial_count=options.trials,
                base_seed=options.base_seed,
                progress_callback=job.report_progress,
                parameter_registry_path=parameter_registry_path,
            ).run()
            return mc_outcome.result.output_directory
        if options.kind == "sensitivity-oneway":
            job.detail = "Sweeping calibration parameters one at a time"
            oneway_outcome = OneWaySensitivityExperiment(
                config,
                parameter_names=options.parameters or None,
                steps=options.steps,
                progress_callback=job.report_progress,
                parameter_registry_path=parameter_registry_path,
            ).run()
            return oneway_outcome.result.output_directory
        if options.kind == "winner-map":
            if not options.parameter_a or not options.parameter_b:
                raise ValueError("winner-map needs parameter_a and parameter_b")
            job.detail = f"Gridding {options.parameter_a} x {options.parameter_b}"
            grid_outcome = TwoWaySensitivityExperiment(
                config,
                parameter_name_a=options.parameter_a,
                parameter_name_b=options.parameter_b,
                grid_steps=options.grid_steps,
                progress_callback=job.report_progress,
                parameter_registry_path=parameter_registry_path,
            ).run()
            return grid_outcome.result.output_directory
        # break-even
        if not options.parameter:
            raise ValueError("break-even needs a registry parameter name")
        job.detail = (
            f"Searching break-even {options.parameter} "
            f"for {options.scenario_a} vs {options.scenario_b}"
        )
        break_even_outcome = BreakEvenExperiment(
            config,
            parameter_name=options.parameter,
            scenario_a=options.scenario_a,
            scenario_b=options.scenario_b,
            progress_callback=job.report_progress,
            parameter_registry_path=parameter_registry_path,
        ).run()
        return break_even_outcome.result.output_directory

    return work


def _enqueue_run(kind: str, config_name: str, work: Callable[[Job], Path]) -> Job:
    """Queue an analysis; the registry executes analyses one at a time."""
    return jobs.submit(kind, config_name, work)


@app.post("/api/runs")
def launch_run(body: LaunchRequest) -> JSONResponse:
    if body.kind not in JOB_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {JOB_KINDS}")
    if body.kind == "sensitivity-oneway" and (
        not body.parameters or any(not parameter.strip() for parameter in body.parameters)
    ):
        raise HTTPException(
            status_code=400,
            detail="Choose at least one parameter for one-way sensitivity.",
        )
    if body.kind == "sensitivity-oneway" and body.parameters is not None:
        normalized_parameters = [parameter.strip() for parameter in body.parameters]
        if len(set(normalized_parameters)) != len(normalized_parameters):
            raise HTTPException(
                status_code=400,
                detail="Choose each one-way sensitivity parameter only once.",
            )
    if body.kind == "winner-map":
        if (
            not body.parameter_a
            or not body.parameter_a.strip()
            or not body.parameter_b
            or not body.parameter_b.strip()
        ):
            raise HTTPException(status_code=400, detail="Winner map needs both parameter names.")
        if body.parameter_a.strip() == body.parameter_b.strip():
            raise HTTPException(
                status_code=400,
                detail="Pick two different parameters for the winner map.",
            )
    if body.kind == "break-even":
        if not body.parameter or not body.parameter.strip():
            raise HTTPException(
                status_code=400,
                detail="Break-even needs a registry parameter name.",
            )
        allowed_scenarios = {"baseline", "reactive", "coating"}
        if body.scenario_a not in allowed_scenarios or body.scenario_b not in allowed_scenarios:
            raise HTTPException(
                status_code=400,
                detail="Break-even scenarios must be baseline, reactive, or coating.",
            )
        if body.scenario_a == body.scenario_b:
            raise HTTPException(
                status_code=400,
                detail="Pick two different scenarios for the break-even search.",
            )
    config_path = _config_path(body.config)
    job = _enqueue_run(body.kind, body.config, _make_work(body, config_path))
    return JSONResponse(job.to_record(), status_code=202)


def _apply_mc_rerun_options(options: LaunchRequest, run_dir: Path) -> None:
    summary = artifacts.load_json(run_dir / "monte_carlo_summary.json") or {}
    trials = summary.get("trial_count")
    if isinstance(trials, int) and trials >= 2:
        options.trials = trials
    base_seed = summary.get("base_seed")
    if isinstance(base_seed, int):
        options.base_seed = base_seed


def _apply_oneway_rerun_options(options: LaunchRequest, run_dir: Path) -> None:
    summary = artifacts.load_json(run_dir / "sensitivity_oneway_summary.json") or {}
    results = summary.get("parameter_results")
    if not isinstance(results, list) or not results:
        return
    names = [
        str(item["parameter_name"])
        for item in results
        if isinstance(item, dict) and item.get("parameter_name")
    ]
    options.parameters = names or None
    point_counts = [
        len(item["points"])
        for item in results
        if isinstance(item, dict) and isinstance(item.get("points"), list)
    ]
    if point_counts:
        options.steps = max(2, *point_counts)


def _rerun_options(kind: str, run_dir: Path) -> LaunchRequest:
    """Best-effort reconstruction of a run's launch options from its artifacts."""
    options = LaunchRequest(kind=kind)
    if kind == "monte-carlo":
        _apply_mc_rerun_options(options, run_dir)
    elif kind == "sensitivity-oneway":
        _apply_oneway_rerun_options(options, run_dir)
    elif kind == "winner-map":
        summary = artifacts.load_json(run_dir / "sensitivity_twoway_summary.json") or {}
        parameter_a, parameter_b = summary.get("parameter_a"), summary.get("parameter_b")
        if not isinstance(parameter_a, str) or not isinstance(parameter_b, str):
            raise HTTPException(
                status_code=409, detail="Run lacks a winner-map summary to re-run from."
            )
        options.parameter_a = parameter_a
        options.parameter_b = parameter_b
        grid_points = summary.get("grid_points")
        if isinstance(grid_points, int) and grid_points > 0:
            options.grid_steps = max(2, round(math.sqrt(grid_points)))
    elif kind == "break-even":
        report = artifacts.load_json(run_dir / "breakeven_report.json") or {}
        parameter = report.get("parameter_name")
        if not isinstance(parameter, str):
            raise HTTPException(
                status_code=409, detail="Run lacks a break-even report to re-run from."
            )
        options.parameter = parameter
        if isinstance(report.get("scenario_a"), str):
            options.scenario_a = str(report["scenario_a"])
        if isinstance(report.get("scenario_b"), str):
            options.scenario_b = str(report["scenario_b"])
    return options


@app.post("/api/runs/{run_id}/rerun")
def rerun(run_id: str) -> JSONResponse:
    """Repeat an analysis using the run's own stored config snapshot.

    The run directory's config_resolved.yaml is what actually produced the
    result, so re-running it is exact for the config; analysis options
    (trials, parameters, ...) are reconstructed from the run's summary
    artifacts.
    """
    run_dir = _run_dir_or_404(run_id)
    kind = _RERUNNABLE_KINDS.get(artifacts._detect_kind(run_id))
    if kind is None:
        raise HTTPException(status_code=400, detail="This run type cannot be re-run.")
    config_path = run_dir / "config_resolved.yaml"
    if not config_path.is_file():
        raise HTTPException(
            status_code=409, detail="Run has no config_resolved.yaml to re-run from."
        )
    options = _rerun_options(kind, run_dir)
    job = _enqueue_run(kind, f"re-run of {run_id}", _make_work(options, config_path))
    return JSONResponse(job.to_record(), status_code=202)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> JSONResponse:
    record = jobs.get_record(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return JSONResponse(record)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> JSONResponse:
    """Delete a run session. Running sessions are cancelled first (cooperatively).

    Only the session entry is removed (including from the persisted history);
    any run directory already written under outputs/ is preserved.
    """
    deleted = jobs.delete(job_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    status = deleted.status if isinstance(deleted, Job) else str(deleted.get("status", ""))
    return JSONResponse(
        {
            "deleted": True,
            "job_id": job_id,
            "was_running": status in ("queued", "running"),
        }
    )


def _retry_readonly_removal(
    remove: Callable[[str], object],
    path: str,
    error_info: tuple[type[BaseException], BaseException, object],
) -> None:
    """Let ``rmtree`` remove Windows/OneDrive paths marked read-only."""

    error = error_info[1]
    if not isinstance(error, PermissionError):
        raise error
    os.chmod(path, stat.S_IWRITE)
    remove(path)


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str) -> JSONResponse:
    """Permanently delete a run directory and everything in it.

    Irreversible: exports, plots, and CSVs for this run are removed from disk.
    The UI asks for confirmation before calling this. Removal is retried
    briefly because sync clients (OneDrive) and antivirus scanners on Windows
    hold short-lived handles on recently written directories.
    """
    run_dir = _run_dir_or_404(run_id)
    last_error: OSError | None = None
    for _ in range(4):
        try:
            shutil.rmtree(run_dir, onerror=_retry_readonly_removal)
            last_error = None
            break
        except FileNotFoundError:
            last_error = None
            break
        except OSError as exc:
            last_error = exc
            time.sleep(0.25)
    if last_error is not None:
        if run_dir.is_dir() and not any(run_dir.iterdir()):
            # All contents are gone; only the empty shell resists because a
            # sync client (OneDrive) or indexer briefly holds the directory
            # handle. The data is deleted — report success. Empty shells are
            # hidden from the runs list and swept on later visits.
            return JSONResponse({"deleted": True, "run_id": run_id})
        raise HTTPException(
            status_code=409,
            detail=(
                f"Could not delete {run_id}: a file or folder is still in use or inaccessible "
                "(often OneDrive sync or antivirus). Close it and try again. "
                f"({type(last_error).__name__}: {last_error})"
            ),
        )
    return JSONResponse({"deleted": True, "run_id": run_id})


@app.get("/api/runs/{run_id}/artifact/{name}")
def get_artifact(run_id: str, name: str) -> FileResponse:
    run_dir = _run_dir_or_404(run_id)
    path = artifacts.resolve_artifact(run_dir, name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"No artifact {name} in run {run_id}")
    return FileResponse(path, filename=name)


@app.get("/api/runs/{run_id}/artifact-preview/{name}")
def preview_artifact(run_id: str, name: str) -> JSONResponse:
    """Return a bounded, uninterpreted preview of one guarded run artifact."""

    run_dir = _run_dir_or_404(run_id)
    path = artifacts.resolve_artifact(run_dir, name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"No artifact {name} in run {run_id}")
    suffix = path.suffix.lower()
    download_url = f"/api/runs/{run_id}/artifact/{name}"
    size_bytes = path.stat().st_size
    payload: dict[str, object] = {
        "name": name,
        "size_bytes": size_bytes,
        "download_url": download_url,
        "audit_source": name,
    }
    if suffix == ".csv":
        header, shown, total_rows = artifacts.read_csv_preview(path, limit=_ARTIFACT_PREVIEW_ROWS)
        payload.update(
            {
                "kind": "csv",
                "header": header,
                "rows": shown,
                "shown_rows": len(shown),
                "total_rows": total_rows,
                "truncated": len(shown) < total_rows,
            }
        )
    elif suffix == ".json":
        if size_bytes > _ARTIFACT_JSON_PREVIEW_BYTES:
            raise HTTPException(
                status_code=413,
                detail="JSON artifact is too large for an in-page preview; download it instead.",
            )
        json_content = artifacts.load_json(path)
        if json_content is None:
            raise HTTPException(
                status_code=422,
                detail="JSON artifact is not a valid object and cannot be previewed.",
            )
        payload.update(
            {
                "kind": "json",
                "content": json.dumps(json_content, indent=2, ensure_ascii=False),
            }
        )
    elif suffix in {".txt", ".md", ".log", ".yaml", ".yml"}:
        text_content = artifacts.text_preview(path)
        if text_content is None:
            raise HTTPException(
                status_code=413,
                detail="Text artifact is too large for an in-page preview; download it instead.",
            )
        payload.update({"kind": "text", "content": text_content})
    elif suffix == ".png":
        payload.update({"kind": "png", "url": download_url})
    else:
        raise HTTPException(
            status_code=415,
            detail=f"Preview is not available for {suffix or 'extensionless'} artifacts.",
        )
    return JSONResponse(payload, headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/runs/{run_id}/download")
def download_run(run_id: str) -> StreamingResponse:
    run_dir = _run_dir_or_404(run_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(run_dir.iterdir()):
            if path.is_file():
                archive.write(path, arcname=f"{run_id}/{path.name}")
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'},
    )


class ConfigBody(BaseModel):
    content: str
    save_as: str | None = None


class LocationConfigBody(BaseModel):
    content: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    site_name: str | None = None
    # Optional whole-day period rewrite applied in the same validated YAML
    # edit, so the config essentials form needs no YAML hand-editing.
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_period(self) -> LocationConfigBody:
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date and end_date must be supplied together")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date must be on or after start_date")
        return self


@lru_cache(maxsize=1)
def _timezone_finder() -> TimezoneFinder:
    """Load the offline boundary dataset once, on the first location update."""

    return TimezoneFinder(in_memory=True)


def _timezone_at(latitude: float, longitude: float) -> str:
    timezone_name = _timezone_finder().timezone_at(lng=longitude, lat=latitude)
    if timezone_name is None:
        raise ValueError("could not determine a timezone for those coordinates")
    return timezone_name


def _replace_yaml_section_scalar(
    content: str,
    *,
    section: str,
    key: str,
    rendered_value: str,
) -> str:
    """Replace one scalar in a top-level block while preserving the rest of the YAML."""

    lines = content.splitlines(keepends=True)
    section_index: int | None = None
    for index, line in enumerate(lines):
        if line.rstrip("\r\n").strip() == f"{section}:":
            section_index = index
            break
    if section_index is None:
        raise ValueError(f"could not find {section}: section in the YAML")

    key_pattern = re.compile(rf"^(?P<indent>\s+){re.escape(key)}\s*:")
    for index in range(section_index + 1, len(lines)):
        raw_line = lines[index].rstrip("\r\n")
        if raw_line and not raw_line[0].isspace() and not raw_line.startswith("#"):
            break
        match = key_pattern.match(raw_line)
        if match:
            newline = "\r\n" if lines[index].endswith("\r\n") else "\n"
            if not lines[index].endswith(("\n", "\r")):
                newline = ""
            lines[index] = f"{match.group('indent')}{key}: {rendered_value}{newline}"
            return "".join(lines)
    raise ValueError(f"could not find {section}.{key} in the YAML")


def _simulation_bound_from_yaml(raw: object, field_name: str) -> datetime:
    if not isinstance(raw, dict) or not isinstance(raw.get("simulation"), dict):
        raise ValueError("simulation: section must be a YAML mapping")
    value = raw["simulation"].get(field_name)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"simulation.{field_name} must be an ISO datetime") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"simulation.{field_name} must be a timezone-aware datetime")
    return value


@app.post("/api/configs/{name}/apply-location")
def apply_location(name: str, body: LocationConfigBody) -> JSONResponse:
    """Apply coordinates and their detected timezone with DST-correct period offsets."""

    _config_path(name)
    try:
        timezone_name = _timezone_at(body.latitude, body.longitude)
        timezone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        return JSONResponse({"valid": False, "error": f"Timezone lookup failed: {exc}"})
    try:
        raw = yaml.safe_load(body.content)
        start = _simulation_bound_from_yaml(raw, "start")
        end = _simulation_bound_from_yaml(raw, "end")
        if body.start_date is not None and body.end_date is not None:
            # Whole-day period override, same convention as the launch form.
            local_start = datetime.combine(body.start_date, datetime_time.min, timezone)
            local_end = datetime.combine(body.end_date, datetime_time(hour=23), timezone)
        else:
            local_start = datetime.combine(start.date(), start.time(), timezone)
            local_end = datetime.combine(end.date(), end.time(), timezone)

        updated = body.content
        replacements = [
            ("simulation", "start", f'"{local_start.isoformat()}"'),
            ("simulation", "end", f'"{local_end.isoformat()}"'),
            ("simulation", "target_timezone", timezone_name),
            ("site", "latitude", str(body.latitude)),
            ("site", "longitude", str(body.longitude)),
            ("site", "timezone", timezone_name),
        ]
        if body.site_name is not None:
            replacements.append(("site", "name", json.dumps(body.site_name)))
        for section, key, rendered_value in replacements:
            updated = _replace_yaml_section_scalar(
                updated,
                section=section,
                key=key,
                rendered_value=rendered_value,
            )
        SolarCleanConfig.model_validate(yaml.safe_load(updated))
    except (ValueError, yaml.YAMLError) as exc:
        return JSONResponse({"valid": False, "error": f"{type(exc).__name__}: {exc}"})

    return JSONResponse(
        {
            "valid": True,
            "content": updated,
            "timezone": timezone_name,
            "start": local_start.isoformat(),
            "end": local_end.isoformat(),
        }
    )


@app.post("/api/configs/{name}/validate")
def validate_config(name: str, body: ConfigBody) -> JSONResponse:
    _config_path(name)  # 404 for unknown base config; edits start from a real file
    try:
        yaml.safe_load(body.content)
    except yaml.YAMLError as exc:
        return JSONResponse({"valid": False, "error": f"YAML parse error: {exc}"})
    # load_config wants a file path, so round-trip through a temp file.
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as tmp:
        tmp.write(body.content)
        tmp_path = Path(tmp.name)
    try:
        load_config(tmp_path)
    except Exception as exc:
        return JSONResponse({"valid": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        tmp_path.unlink(missing_ok=True)

    if body.save_as:
        if body.save_as != DEFAULT_CONFIG_NAME:
            return JSONResponse(
                {
                    "valid": True,
                    "saved": False,
                    "error": f"Only {DEFAULT_CONFIG_NAME} may be saved",
                }
            )
        if not _CONFIG_NAME_PATTERN.match(body.save_as):
            return JSONResponse(
                {
                    "valid": True,
                    "saved": False,
                    "error": "Save name must be <letters-digits-_->.yaml",
                }
            )
        (_CONFIGS_DIR / DEFAULT_CONFIG_NAME).write_text(body.content, encoding="utf-8")
        return JSONResponse({"valid": True, "saved": True, "saved_as": DEFAULT_CONFIG_NAME})
    return JSONResponse({"valid": True, "saved": False})
