"""T8 dashboard: a thin web layer over the existing application use cases.

Design rule (see docs/dashboard_user_guide.md): this module may load configs,
start use cases, and read artifact files. It must not calculate energy, cost,
or statistics. If a screen needs a number that no use case writes, the fix is
a backend change, not a formula here.
"""

from __future__ import annotations

import io
import math
import re
import tempfile
import zipfile
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request
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

_PACKAGE_DIR = Path(__file__).parent
_REPO_ROOT = Path.cwd()
_CONFIGS_DIR = _REPO_ROOT / "configs"
_OUTPUTS_DIR = _REPO_ROOT / "outputs"
_CONFIG_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+\.yaml$")

app = FastAPI(title="SolarClean-DT dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=_PACKAGE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=_PACKAGE_DIR / "templates")
jobs = JobRegistry()


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


templates.env.filters["display_number"] = _display_number


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
# exactly as written in scenario_annual_summary.csv.
_KPI_FIELDS = (
    ("Annual AC energy (kWh)", "annual_actual_energy_kwh"),
    ("Energy loss vs clean (%)", "annual_energy_loss_percent"),
    ("Energy gain vs baseline (kWh)", "energy_gain_vs_baseline_kwh"),
    ("Annual revenue (SAR)", "annual_revenue_sar"),
    ("Annualized CAPEX (SAR)", "annualized_capex_sar"),
    ("Annual OPEX (SAR)", "annual_opex_sar"),
    ("Total annual cost (SAR)", "total_annual_cost_sar"),
    ("Net annual benefit (SAR)", "net_annual_benefit_sar"),
    ("Incremental ROI vs baseline", "incremental_roi_vs_baseline"),
    ("Incremental payback vs baseline (yr)", "incremental_payback_years_vs_baseline"),
    ("Effective LCOE (SAR/kWh)", "effective_lcoe_sar_per_kwh"),
    ("Water used (L)", "annual_operational_water_liters"),
    ("Crew hours", "annual_operational_crew_hours"),
    ("Drone flight hours", "annual_operational_drone_flight_hours"),
)


def _kpi_table(header: list[str], rows: list[list[str]]) -> dict[str, object]:
    """Transpose selected annual summary columns: scenarios across, KPIs down."""
    index = {name: position for position, name in enumerate(header)}
    scenario_col = index.get("scenario_name", index.get("scenario_id", 0))
    scenarios = [row[scenario_col] for row in rows]
    table_rows = []
    for label, column in _KPI_FIELDS:
        if column not in index:
            continue
        table_rows.append({"label": label, "values": [row[index[column]] for row in rows]})
    return {"scenarios": scenarios, "rows": table_rows}


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    configs = sorted(p.name for p in _CONFIGS_DIR.glob("*.yaml"))
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "configs": configs,
            "runs": artifacts.list_runs(_OUTPUTS_DIR),
            "jobs": [job.to_record() for job in jobs.all()],
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
    }

    if kind == "compare-all-scenarios":
        context.update(
            {
                "ranking": artifacts.load_json(run_dir / "scenario_ranking.json"),
                "recommendation": artifacts.load_json(run_dir / "recommendation.json"),
                "reconciliation": artifacts.load_json(run_dir / "reconciliation_report.json"),
                "daily_energy": artifacts.daily_energy_series(run_dir),
            }
        )
        annual_path = run_dir / "scenario_annual_summary.csv"
        if annual_path.is_file():
            header, rows = artifacts.read_csv_rows(annual_path)
            context["annual_summary"] = {"header": header, "rows": rows}
            context["kpi_table"] = _kpi_table(header, rows)
        cost_path = run_dir / "scenario_cost_summary.csv"
        if cost_path.is_file():
            header, rows = artifacts.read_csv_rows(cost_path, limit=200)
            context["cost_summary"] = {"header": header, "rows": rows}
        return templates.TemplateResponse(request, "run_comparison.html", context)

    if kind == "monte-carlo":
        context["mc_summary"] = artifacts.load_json(run_dir / "monte_carlo_summary.json")
    else:
        context["generic_summary"] = artifacts.load_json(run_dir / "summary.json")
    return templates.TemplateResponse(request, "run_analysis.html", context)


@app.get("/config/{name}", response_class=HTMLResponse)
def config_page(request: Request, name: str) -> HTMLResponse:
    path = _config_path(name)
    return templates.TemplateResponse(
        request,
        "config.html",
        {"name": name, "content": path.read_text(encoding="utf-8")},
    )


# --------------------------------------------------------------------------
# JSON API
# --------------------------------------------------------------------------


class LaunchRequest(BaseModel):
    kind: str
    config_name: str
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


@app.post("/api/runs")
def launch_run(body: LaunchRequest) -> JSONResponse:
    if body.kind not in JOB_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {JOB_KINDS}")
    config_path = _config_path(body.config_name)

    def work(job: Job) -> Path:
        config = load_config(config_path)
        if body.kind == "compare":
            job.detail = "Running baseline, reactive, and coating against one event tape"
            return CompareAllScenarios(config).run().output_directory
        if body.kind == "monte-carlo":
            job.detail = f"Running {body.trials} seeded trials"
            mc_outcome = MonteCarloExperiment(
                config, trial_count=body.trials, base_seed=body.base_seed
            ).run()
            return mc_outcome.result.output_directory
        if body.kind == "sensitivity-oneway":
            job.detail = "Sweeping calibration parameters one at a time"
            oneway_outcome = OneWaySensitivityExperiment(
                config, parameter_names=body.parameters or None, steps=body.steps
            ).run()
            return oneway_outcome.result.output_directory
        if body.kind == "winner-map":
            if not body.parameter_a or not body.parameter_b:
                raise ValueError("winner-map needs parameter_a and parameter_b")
            job.detail = f"Gridding {body.parameter_a} x {body.parameter_b}"
            grid_outcome = TwoWaySensitivityExperiment(
                config,
                parameter_name_a=body.parameter_a,
                parameter_name_b=body.parameter_b,
                grid_steps=body.grid_steps,
            ).run()
            return grid_outcome.result.output_directory
        # break-even
        if not body.parameter:
            raise ValueError("break-even needs a registry parameter name")
        job.detail = (
            f"Searching break-even {body.parameter} for {body.scenario_a} vs {body.scenario_b}"
        )
        break_even_outcome = BreakEvenExperiment(
            config,
            parameter_name=body.parameter,
            scenario_a=body.scenario_a,
            scenario_b=body.scenario_b,
        ).run()
        return break_even_outcome.result.output_directory

    job = jobs.submit(body.kind, body.config_name, work)
    return JSONResponse(job.to_record(), status_code=202)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> JSONResponse:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return JSONResponse(job.to_record())


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
