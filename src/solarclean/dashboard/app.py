"""T8 dashboard: a thin web layer over the existing application use cases.

Design rule (see docs/dashboard_user_guide.md): this module may load configs,
start use cases, and read artifact files. It must not calculate energy, cost,
or statistics. If a screen needs a number that no use case writes, the fix is
a backend change, not a formula here. The only transformations allowed are
reshaping stored values (picking columns, grouping rows) and display
formatting (rounding, thousands separators, best-of-row highlighting of
already-stored numbers).
"""

from __future__ import annotations

import base64
import binascii
import io
import math
import os
import re
import secrets
import shutil
import tempfile
import time
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from solarclean.application.comparison import CompareAllScenarios
from solarclean.application.monte_carlo import MonteCarloExperiment
from solarclean.application.sensitivity import (
    BreakEvenExperiment,
    OneWaySensitivityExperiment,
    TwoWaySensitivityExperiment,
)
from solarclean.config.loader import load_config
from solarclean.dashboard import artifacts
from solarclean.dashboard.jobs import JOB_KINDS, Job, JobRegistry
from solarclean.domain.calibration.parameter_overrides import build_parameter_catalog
from solarclean.domain.calibration.registry import ParameterRegistry

_PACKAGE_DIR = Path(__file__).parent

# The one config the launch form runs, presented as "Default" in the UI.
# It uses the nasa_power weather provider, so the site coordinates (editable
# via the map picker on the config page) genuinely change the weather the
# simulation runs on. Other YAML files in configs/ remain editable and
# CLI-runnable, but the dashboard intentionally offers no config picker.
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
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(number):  # e.g. baseline payback_years
        return "–"
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    if abs(number) >= 1:
        return f"{number:,.2f}"
    return f"{number:.4f}"


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


templates.env.filters["display_number"] = _display_number
templates.env.filters["sar"] = _format_sar


def _config_path(name: str) -> Path:
    if not _CONFIG_NAME_PATTERN.match(name):
        raise HTTPException(status_code=400, detail="Config name must be <letters-digits-_->.yaml")
    path = _CONFIGS_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"No config named {name} in configs/")
    return path


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
    ("Water used (L)", "annual_operational_water_liters", None),
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


def _kpi_table(header: list[str], rows: list[list[str]]) -> dict[str, object]:
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
                "values": values,
                "direction": direction,
                "best": _best_flags(values, direction),
                "help": _KPI_GLOSSARY.get(column, ""),
            }
        )
    return {"scenarios": scenarios, "rows": table_rows}


# Cost component category order and labels for the redesigned cost table.
_COST_CATEGORY_LABELS = {
    "capex": "Capital costs (CAPEX)",
    "opex": "Operating costs (OPEX)",
}


def _cost_table(header: list[str], rows: list[list[str]]) -> list[dict[str, object]]:
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
    components_by_scenario: dict[str, dict[str, list[dict[str, str]]]] = {}
    stored_totals: dict[str, dict[str, str]] = {}
    evidence_by_scenario: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        scenario_id = cell(row, "scenario_id")
        if not scenario_id:
            continue
        if scenario_id not in scenario_order:
            scenario_order.append(scenario_id)
            components_by_scenario[scenario_id] = {}
            evidence_by_scenario[scenario_id] = []
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
                "evidence": evidence_by_scenario[scenario_id],
            }
        )
    return table


def _annual_cost_bars(header: list[str], rows: list[list[str]]) -> dict[str, object] | None:
    """Pick stored annual money columns for the cost/benefit bar chart."""
    index = {name: position for position, name in enumerate(header)}
    scenario_col = index.get("scenario_name", index.get("scenario_id"))
    if scenario_col is None:
        return None
    metrics = (
        ("Annual revenue", "annual_revenue_sar"),
        ("Annualized CAPEX", "annualized_capex_sar"),
        ("Annual OPEX", "annual_opex_sar"),
        ("Net annual benefit", "net_annual_benefit_sar"),
    )
    series = []
    for label, column in metrics:
        if column not in index:
            return None
        series.append(
            {
                "label": label,
                "values": [_parse_finite(row[index[column]]) for row in rows],
            }
        )
    return {"scenarios": [row[scenario_col] for row in rows], "metrics": series}


def _parameter_catalog() -> list[dict[str, object]]:
    """T7-supported sensitivity parameters for the launch-form dropdowns.

    Listing only: names and registry ranges pass through so users pick from a
    menu instead of hand-typing registry keys. Empty on any load failure — the
    launch endpoint will then produce the real error.
    """
    registry_path = _REPO_ROOT / "data" / "calibration" / "parameter_registry.yaml"
    try:
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


def _resolved_config_section(run_dir: Path, section: str) -> dict[str, object]:
    """One top-level section of the run's stored config_resolved.yaml."""
    config_path = run_dir / "config_resolved.yaml"
    if not config_path.is_file():
        return {}
    try:
        resolved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(resolved, dict):
        return {}
    raw = resolved.get(section)
    return raw if isinstance(raw, dict) else {}


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
    if metadata is None and not site and not weather_cfg:
        return None
    metadata = metadata or {}
    checksum = str(metadata.get("weather_checksum", ""))
    return {
        "provider": metadata.get("weather_provider") or weather_cfg.get("provider"),
        "site_name": site.get("name"),
        "latitude": site.get("latitude"),
        "longitude": site.get("longitude"),
        "weather_checksum_short": checksum[:12] if checksum else None,
        "created_at_utc": str(metadata.get("created_at_utc", ""))[:19],
        "assumption_set": metadata.get("calibration_assumption_set")
        or calibration.get("assumption_set"),
    }


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "default_config_name": DEFAULT_CONFIG_NAME,
            "default_config_label": DEFAULT_CONFIG_LABEL,
            "default_config_exists": (_CONFIGS_DIR / DEFAULT_CONFIG_NAME).is_file(),
            "runs": artifacts.list_runs(_OUTPUTS_DIR),
            "jobs": jobs.records(),
            "parameters": _parameter_catalog(),
        },
    )


@app.get("/run/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: str) -> HTMLResponse:
    run_dir = _run_dir_or_404(run_id)
    kind = artifacts._detect_kind(run_id)
    context: dict[str, object] = {
        "run_id": run_id,
        "kind": kind,
        "artifacts": artifacts.list_artifacts(run_dir),
        "plots": [
            f["name"] for f in artifacts.list_artifacts(run_dir) if str(f["name"]).endswith(".png")
        ],
        "summary_text": artifacts.text_preview(run_dir / "summary.txt"),
        "provenance": _provenance(run_dir),
        "rerun_supported": kind in _RERUNNABLE_KINDS,
    }

    if kind == "compare-all-scenarios":
        recommendation = artifacts.load_json(run_dir / "recommendation.json")
        context.update(
            {
                "ranking": artifacts.load_json(run_dir / "scenario_ranking.json"),
                "recommendation": recommendation,
                "reconciliation": artifacts.load_json(run_dir / "reconciliation_report.json"),
                "headline": _headline_cards(recommendation),
                "daily_energy": artifacts.daily_energy_series(run_dir),
                "daily_loss": artifacts.daily_series(run_dir, "energy_loss_kwh"),
                "daily_soiling": artifacts.daily_series(run_dir, "soiling_ratio"),
                "daily_cumgain": artifacts.daily_series(
                    run_dir, "cumulative_energy_gain_vs_baseline_kwh"
                ),
            }
        )
        annual_path = run_dir / "scenario_annual_summary.csv"
        if annual_path.is_file():
            header, rows = artifacts.read_csv_rows(annual_path)
            context["annual_summary"] = {"header": header, "rows": rows}
            context["kpi_table"] = _kpi_table(header, rows)
            context["annual_cost_bars"] = _annual_cost_bars(header, rows)
        cost_path = run_dir / "scenario_cost_summary.csv"
        if cost_path.is_file():
            header, rows = artifacts.read_csv_rows(cost_path, limit=200)
            context["cost_table"] = _cost_table(header, rows)
        return templates.TemplateResponse(request, "run_comparison.html", context)

    if kind == "monte-carlo":
        context["mc_summary"] = artifacts.load_json(run_dir / "monte_carlo_summary.json")
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
    return templates.TemplateResponse(request, "run_analysis.html", context)


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


class LaunchRequest(BaseModel):
    kind: str
    trials: int = 25
    base_seed: int | None = None
    steps: int = 5
    parameters: list[str] | None = None
    parameter_a: str | None = None
    parameter_b: str | None = None
    grid_steps: int = 5
    parameter: str | None = None
    scenario_a: str = "coating"
    scenario_b: str = "baseline"


def _headline_cards(recommendation: dict[str, object] | None) -> list[dict[str, str]] | None:
    """Top-of-page cards from stored recommendation values (formatting only)."""
    if not recommendation or not recommendation.get("valid"):
        return None
    winner = recommendation.get("winner")
    if not isinstance(winner, str):
        return None
    snapshot = recommendation.get("kpi_snapshot")
    winner_kpis = snapshot.get(winner) if isinstance(snapshot, dict) else None
    if not isinstance(winner_kpis, dict):
        winner_kpis = {}
    cards = [{"label": "Recommended strategy", "value": winner, "unit": ""}]
    margin = recommendation.get("decisive_margin_sar")
    if isinstance(margin, int | float) and math.isfinite(margin):
        cards.append(
            {"label": "Margin over runner-up", "value": _format_sar(margin), "unit": "SAR/year"}
        )
    for label, key, unit in (
        ("Net annual benefit", "net_annual_benefit_sar", "SAR/year"),
        ("Energy gain vs baseline", "energy_gain_vs_baseline_kwh", "kWh/year"),
        ("Incremental payback", "incremental_payback_years_vs_baseline", "years"),
    ):
        value = winner_kpis.get(key)
        if isinstance(value, int | float) and math.isfinite(float(value)):
            cards.append({"label": label, "value": _format_sar(value), "unit": unit})
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
        config = load_config(config_path)
        if options.kind == "compare":
            job.detail = "Running baseline, reactive, and coating against one event tape"
            return (
                CompareAllScenarios(config, progress_callback=job.report_progress)
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
            ).run()
            return mc_outcome.result.output_directory
        if options.kind == "sensitivity-oneway":
            job.detail = "Sweeping calibration parameters one at a time"
            oneway_outcome = OneWaySensitivityExperiment(
                config,
                parameter_names=options.parameters or None,
                steps=options.steps,
                progress_callback=job.report_progress,
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
        ).run()
        return break_even_outcome.result.output_directory

    return work


def _reject_if_busy() -> None:
    """Serialize heavy runs: one active session at a time.

    Simulations are CPU-bound; two concurrent full-year runs just slow each
    other down and confuse progress ETAs. 409 tells the user to wait or cancel.
    """
    active = [job for job in jobs.all() if job.status in ("queued", "running")]
    if active:
        busy = active[0]
        raise HTTPException(
            status_code=409,
            detail=(
                f"A {busy.kind} run is already {busy.status} (session {busy.job_id}). "
                "Wait for it to finish or delete its session, then launch again."
            ),
        )


@app.post("/api/runs")
def launch_run(body: LaunchRequest) -> JSONResponse:
    if body.kind not in JOB_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {JOB_KINDS}")
    _reject_if_busy()
    # Runs always use the Default config; there is deliberately no picker.
    config_path = _config_path(DEFAULT_CONFIG_NAME)
    job = jobs.submit(body.kind, DEFAULT_CONFIG_NAME, _make_work(body, config_path))
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
    _reject_if_busy()
    options = _rerun_options(kind, run_dir)
    job = jobs.submit(kind, f"re-run of {run_id}", _make_work(options, config_path))
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
            shutil.rmtree(run_dir)
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
                f"Could not delete {run_id}: a file or folder is held open by another "
                "program (often OneDrive sync or antivirus). Close it and try again. "
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
        if not _CONFIG_NAME_PATTERN.match(body.save_as):
            return JSONResponse(
                {
                    "valid": True,
                    "saved": False,
                    "error": "Save name must be <letters-digits-_->.yaml",
                }
            )
        (_CONFIGS_DIR / body.save_as).write_text(body.content, encoding="utf-8")
        return JSONResponse({"valid": True, "saved": True, "saved_as": body.save_as})
    return JSONResponse({"valid": True, "saved": False})
