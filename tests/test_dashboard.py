"""T8 dashboard tests.

The important one is test_displayed_ranking_matches_artifact: T8's completion
criteria require that what the dashboard shows reconciles with what the backend
wrote, so we run one real offline comparison and check the page against the
JSON artifact it claims to display.

T9 additions cover the Default-config-only launch flow, run-session delete and
cancel, honest progress/ETA reporting, KPI best-value highlighting, the
redesigned cost table, evidence-status visibility, theme toggle persistence
markers, and web-readiness (environment-configurable paths and bind address).
"""

from __future__ import annotations

import io
import json
import threading
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

fastapi = pytest.importorskip("fastapi", reason="dashboard extra not installed")
from fastapi.testclient import TestClient  # noqa: E402
from tests.config_factory import DEFAULT_CONFIG_PATH, fixture_config  # noqa: E402

from solarclean.application import sensitivity  # noqa: E402
from solarclean.application.comparison import CompareAllScenarios  # noqa: E402
from solarclean.application.monte_carlo import MonteCarloExperiment  # noqa: E402
from solarclean.application.sensitivity import (  # noqa: E402
    BreakEvenExperiment,
    OneWaySensitivityExperiment,
    TwoWaySensitivityExperiment,
)
from solarclean.config.loader import load_config  # noqa: E402
from solarclean.dashboard import app as dashboard_app  # noqa: E402
from solarclean.dashboard import artifacts as artifacts_module  # noqa: E402
from solarclean.dashboard.__main__ import resolve_bind  # noqa: E402
from solarclean.dashboard.app import (  # noqa: E402
    DEFAULT_CONFIG_NAME,
    _cost_table,
    _format_sar,
    _kpi_table,
    app,
)
from solarclean.dashboard.jobs import Job, JobCancelled, JobRegistry  # noqa: E402


@pytest.fixture(scope="module")
def comparison_run() -> Path:
    result = CompareAllScenarios(fixture_config()).run()
    return result.output_directory


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# --------------------------------------------------------------------------
# Default config behaviour
# --------------------------------------------------------------------------


def test_index_offers_only_the_default_config(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    # The launch form shows the Default config and links to its editor ...
    assert ">Default<" in response.text
    assert f"/config/{DEFAULT_CONFIG_NAME}" in response.text
    # ... and no longer renders a config picker over configs/*.yaml.
    assert '<select id="config"' not in response.text
    assert "riyadh_2025.yaml" not in response.text
    assert "coating_central.yaml" not in response.text


def test_launch_rejects_unknown_kind(client: TestClient) -> None:
    response = client.post("/api/runs", json={"kind": "warp-drive"})
    assert response.status_code == 400


def test_launch_runs_default_config_and_reports_progress(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Point "Default" at the fast 2-day fixture so the test finishes quickly;
    # the route logic is identical for the real full-year default.
    sandbox = tmp_path / "configs"
    sandbox.mkdir()
    (sandbox / DEFAULT_CONFIG_NAME).write_text(
        yaml.safe_dump(fixture_config().model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_app, "_CONFIGS_DIR", sandbox)
    launched = client.post("/api/runs", json={"kind": "compare"})
    assert launched.status_code == 202
    record = launched.json()
    assert record["config_name"] == DEFAULT_CONFIG_NAME

    deadline = time.time() + 120
    while time.time() < deadline:
        record = client.get(f"/api/jobs/{record['job_id']}").json()
        if record["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert record["status"] == "done", record.get("error")
    assert record["progress_total"] == 3
    assert record["progress_percent"] == 100.0
    assert record["elapsed_seconds"] is not None
    assert record["run_id"]

    # Deleting a finished session removes it from the registry and the page.
    deleted = client.delete(f"/api/jobs/{record['job_id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {
        "deleted": True,
        "job_id": record["job_id"],
        "was_running": False,
    }
    assert client.get(f"/api/jobs/{record['job_id']}").status_code == 404


# --------------------------------------------------------------------------
# Session delete / cancel and progress bookkeeping
# --------------------------------------------------------------------------


def test_delete_cancels_a_running_session(client: TestClient) -> None:
    started = threading.Event()

    def work(job: Job) -> Path:
        while True:  # exits via JobCancelled raised by report_progress
            job.report_progress(1, 1000, "spinning until cancelled")
            started.set()
            time.sleep(0.02)

    job = dashboard_app.jobs.submit("compare", "synthetic.yaml", work)
    assert started.wait(timeout=10)

    response = client.delete(f"/api/jobs/{job.job_id}")
    assert response.status_code == 200
    assert response.json()["was_running"] is True
    # Hidden immediately, even while the worker winds down.
    assert client.get(f"/api/jobs/{job.job_id}").status_code == 404
    assert job.job_id not in {j.job_id for j in dashboard_app.jobs.all()}
    assert job.job_id not in client.get("/").text

    deadline = time.time() + 10
    while job.status != "cancelled" and time.time() < deadline:
        time.sleep(0.02)
    assert job.status == "cancelled"


def test_delete_unknown_session_is_404(client: TestClient) -> None:
    assert client.delete("/api/jobs/no-such-job").status_code == 404


def test_job_record_reports_honest_progress_and_eta() -> None:
    job = Job(job_id="j1", kind="compare", config_name="x.yaml")
    record = job.to_record()
    # Before any unit finishes there is no percentage and no ETA.
    assert record["progress_percent"] is None
    assert record["eta_seconds"] is None

    job.status = "running"
    job.started_at = datetime.now(UTC) - timedelta(seconds=10)
    job.report_progress(1, 4, "Simulating reactive scenario")
    record = job.to_record()
    assert record["progress_percent"] == 25.0
    assert record["detail"] == "Simulating reactive scenario"
    elapsed = record["elapsed_seconds"]
    assert isinstance(elapsed, float) and elapsed >= 10
    # ETA = measured pace * remaining units (~30s here), never invented.
    eta = record["eta_seconds"]
    assert isinstance(eta, float) and 25 <= eta <= 40

    # A kind that reports no unit counts keeps percentage and ETA blank.
    silent = Job(job_id="j2", kind="break-even", config_name="x.yaml", status="running")
    silent.started_at = datetime.now(UTC)
    silent_record = silent.to_record()
    assert silent_record["progress_percent"] is None
    assert silent_record["eta_seconds"] is None


def test_report_progress_raises_when_cancel_requested() -> None:
    job = Job(job_id="j3", kind="compare", config_name="x.yaml")
    job.cancel_event.set()
    with pytest.raises(JobCancelled):
        job.report_progress(1, 3, "should abort")


def test_registry_delete_semantics() -> None:
    registry = JobRegistry()
    done = threading.Event()

    def work(job: Job) -> Path:
        done.wait(timeout=5)
        return Path("outputs/fake")

    job = registry.submit("compare", "x.yaml", work)
    assert registry.get(job.job_id) is job
    deleted = registry.delete(job.job_id)
    assert deleted is job
    assert registry.get(job.job_id) is None
    assert registry.all() == []
    done.set()


# --------------------------------------------------------------------------
# Application-layer progress callbacks (compare + Monte Carlo)
# --------------------------------------------------------------------------


def test_compare_progress_callback_counts_scenarios() -> None:
    calls: list[tuple[int, int, str]] = []
    CompareAllScenarios(
        fixture_config(),
        progress_callback=lambda done, total, stage: calls.append((done, total, stage)),
        write_artifacts=False,
    ).run()
    assert calls[0][:2] == (0, 3)
    assert calls[-1][:2] == (3, 3)
    dones = [done for done, _, _ in calls]
    assert dones == sorted(dones)
    assert all(total == 3 for _, total, _ in calls)


def test_monte_carlo_progress_callback_counts_trials() -> None:
    calls: list[tuple[int, int, str]] = []
    MonteCarloExperiment(
        fixture_config(),
        trial_count=2,
        progress_callback=lambda done, total, stage: calls.append((done, total, stage)),
        write_artifacts=False,
    ).run()
    totals = {total for _, total, _ in calls}
    assert totals == {3}  # central comparison + 2 trials
    assert calls[0][0] == 0
    assert calls[-1][0] == 3


@pytest.fixture
def stub_run_variant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the per-variant comparison with a canned reconciled result.

    The T7 experiments treat CompareAllScenarios as a black box, so progress
    accounting can be tested without paying for real simulations. baseline
    always wins, so break-even (coating vs baseline) finds no crossing and
    stops after its scan phase — exercising the under-budget completion path.
    """
    canned = sensitivity.VariantResult(
        net_annual_benefit_sar={"baseline": 3.0, "reactive": 2.0, "coating": 1.0},
        winner="baseline",
        reconciled=True,
        failed_reconciliation_checks=(),
    )

    def fake_run_variant(**kwargs: object) -> sensitivity.VariantResult:
        return canned

    monkeypatch.setattr(sensitivity, "_run_variant", fake_run_variant)


def test_oneway_progress_callback_counts_sweep_points(stub_run_variant: None) -> None:
    calls: list[tuple[int, int, str]] = []
    outcome = OneWaySensitivityExperiment(
        fixture_config(),
        parameter_names=["economics.electricity_tariff_sar_per_kwh"],
        steps=3,
        write_artifacts=False,
        progress_callback=lambda done, total, stage: calls.append((done, total, stage)),
    ).run()
    point_count = len(outcome.result.parameter_results[0].points)
    total = 1 + point_count  # base variant + each sweep point
    assert calls[0][:2] == (0, total)
    assert calls[-1][:2] == (total, total)
    dones = [done for done, _, _ in calls]
    assert dones == sorted(dones)
    assert all(t == total for _, t, _ in calls)


def test_winner_map_progress_callback_counts_grid_points(stub_run_variant: None) -> None:
    calls: list[tuple[int, int, str]] = []
    outcome = TwoWaySensitivityExperiment(
        fixture_config(),
        parameter_name_a="economics.electricity_tariff_sar_per_kwh",
        parameter_name_b="economics.labour_cost_sar_per_hour",
        grid_steps=3,
        write_artifacts=False,
        progress_callback=lambda done, total, stage: calls.append((done, total, stage)),
    ).run()
    total = len(outcome.result.grid)
    assert calls[0][:2] == (0, total)
    assert calls[-1][:2] == (total, total)
    dones = [done for done, _, _ in calls]
    assert dones == sorted(dones)


def test_break_even_progress_reports_against_declared_budget(stub_run_variant: None) -> None:
    calls: list[tuple[int, int, str]] = []
    outcome = BreakEvenExperiment(
        fixture_config(),
        parameter_name="economics.electricity_tariff_sar_per_kwh",
        scenario_a="coating",
        scenario_b="baseline",
        write_artifacts=False,
        progress_callback=lambda done, total, stage: calls.append((done, total, stage)),
    ).run()
    budget = sensitivity.DEFAULT_MAX_BREAKEVEN_EVALUATIONS
    assert all(total == budget for _, total, _ in calls)
    assert calls[0][0] == 0
    # baseline dominates everywhere, so the scan finds no crossing and the
    # search finishes under budget; progress still closes out at 100%.
    assert outcome.result.crossing_status == "no_crossing"
    assert len(outcome.result.evaluations) < budget
    assert calls[-1][0] == budget


# --------------------------------------------------------------------------
# Comparison page rendering
# --------------------------------------------------------------------------


def test_displayed_ranking_matches_artifact(client: TestClient, comparison_run: Path) -> None:
    with (comparison_run / "scenario_ranking.json").open(encoding="utf-8") as handle:
        ranking = json.load(handle)["ranking"]
    page = client.get(f"/run/{comparison_run.name}").text
    if not ranking:
        # T6 policy: non-full-year runs (like this 2-day fixture) produce no
        # ranking; the page must say so instead of showing a winner.
        assert "no ranking was accepted" in page
        return
    for entry in ranking:
        assert entry["scenario_id"] in page
        # Net annual benefit is rendered with %.0f on the ranking table.
        assert f"{entry['net_annual_benefit_sar']:.0f}" in page


def test_reconciliation_chips_rendered(client: TestClient, comparison_run: Path) -> None:
    page = client.get(f"/run/{comparison_run.name}").text
    assert "same_weather_checksum" in page
    assert "same_event_tape_checksum" in page


def test_cost_reconciliation_help_is_plain_english(
    client: TestClient, comparison_run: Path
) -> None:
    page = client.get(f"/run/{comparison_run.name}").text
    assert "crew hours" in page
    assert "labour rate" in page
    assert "water price" in page


def test_kpi_best_values_highlighted(client: TestClient, comparison_run: Path) -> None:
    page = client.get(f"/run/{comparison_run.name}").text
    assert "best-cell" in page


def test_charts_replace_static_plot_grid(client: TestClient, comparison_run: Path) -> None:
    page = client.get(f"/run/{comparison_run.name}").text
    # Interactive charts fed from stored CSV columns ...
    assert "daily-energy-chart" in page
    assert "daily-loss-chart" in page
    assert "daily-soiling-chart" in page
    assert "Daily contamination cleanliness by scenario" in page
    cleanliness = artifacts_module.daily_cleanliness_series(comparison_run)
    assert cleanliness is not None
    assert set(cleanliness["series"]) == {"baseline", "reactive", "coating"}
    assert "annual-cost-chart" in page
    # ... and no inline <img> plot grid on the comparison page. PNGs stay
    # downloadable from the artifact list.
    assert '<div class="plot-grid">' not in page
    assert "comparison_daily_energy.png" in page  # still listed as an artifact


def test_evidence_status_hidden_by_default(client: TestClient, comparison_run: Path) -> None:
    page = client.get(f"/run/{comparison_run.name}").text
    # Renamed and tucked into a collapsed advanced section ...
    assert "Evidence status" in page
    assert "Evidence status &amp; sources (advanced)" in page
    # ... instead of a raw source_status column in the main table.
    assert "<th>source_status</th>" not in page


def test_cost_table_grouped_with_subtotals(client: TestClient, comparison_run: Path) -> None:
    page = client.get(f"/run/{comparison_run.name}").text
    assert "Cost components" in page
    assert "Capital costs (CAPEX)" in page
    assert "Operating costs (OPEX)" in page
    assert "Subtotal" in page
    assert "Total annual cost" in page
    assert "SAR/year" in page


# --------------------------------------------------------------------------
# Display-formatting helpers (reshaping only, no calculation)
# --------------------------------------------------------------------------


def test_format_sar_rounds_and_separates_thousands() -> None:
    assert _format_sar("150000.0000000000") == "150,000"
    assert _format_sar("950.4000000000") == "950"
    assert _format_sar("50.2470000000") == "50.25"
    assert _format_sar("0.0000000000") == "0"
    assert _format_sar("nan") == "–"
    assert _format_sar("") == ""


def test_kpi_table_marks_best_by_metric_direction() -> None:
    header = [
        "scenario_name",
        "annual_revenue_sar",
        "total_annual_cost_sar",
        "annual_operational_water_liters",
        "incremental_payback_years_vs_baseline",
    ]
    rows = [
        ["baseline", "100.0", "50.0", "0.0", "nan"],
        ["reactive", "200.0", "40.0", "10.0", "2.0"],
        ["coating", "150.0", "60.0", "5.0", "1.5"],
    ]
    table = _kpi_table(header, rows)
    by_label = {row["label"]: row for row in table["rows"]}
    # Higher is better for revenue.
    assert by_label["Annual revenue (SAR)"]["best"] == [False, True, False]
    # Lower is better for cost and payback; NaN entries are never "best".
    assert by_label["Total annual cost (SAR)"]["best"] == [False, True, False]
    assert by_label["Incremental payback vs baseline (yr)"]["best"] == [False, False, True]
    # Operational quantities carry no direction, so nothing is highlighted.
    assert by_label["Water used (L)"]["best"] == [False, False, False]


def test_cost_table_groups_components_and_passes_through_stored_totals() -> None:
    header = [
        "scenario_id",
        "annualized_capex_sar",
        "annual_opex_sar",
        "total_annual_cost_sar",
        "total_capex_sar",
        "capital_recovery_life_years",
        "component_name",
        "category",
        "amount_sar",
        "unit",
        "source",
        "source_status",
        "notes",
    ]
    rows = [
        ["baseline", "0", "0", "0", "0", "15", "none", "", "0", "", "", "", ""],
        [
            "reactive",
            "17524",
            "160640",
            "178165",
            "150000",
            "15",
            "reactive crew labour",
            "opex",
            "20328",
            "SAR/year",
            "wage refs",
            "blocked",
            "n1",
        ],
        [
            "reactive",
            "17524",
            "160640",
            "178165",
            "150000",
            "15",
            "drone equipment capex",
            "capex",
            "150000",
            "SAR",
            "uav specs",
            "blocked",
            "n2",
        ],
    ]
    table = _cost_table(header, rows)
    by_scenario = {entry["scenario"]: entry for entry in table}

    assert by_scenario["baseline"]["groups"] == []
    reactive = by_scenario["reactive"]
    groups = {group["category"]: group for group in reactive["groups"]}
    assert [group["category"] for group in reactive["groups"]] == ["capex", "opex"]
    # Subtotals are the stored scenario-level columns, not sums made here.
    assert groups["capex"]["subtotal_amount"] == "150000"
    assert groups["opex"]["subtotal_amount"] == "160640"
    assert reactive["total_annual_cost_sar"] == "178165"
    # source_status is exposed only as renamed evidence metadata.
    statuses = {item["evidence_status"] for item in reactive["evidence"]}
    assert statuses == {"blocked"}


# --------------------------------------------------------------------------
# Theme toggle persistence
# --------------------------------------------------------------------------


def test_theme_toggle_present_and_persisted(client: TestClient) -> None:
    page = client.get("/").text
    assert 'id="theme-toggle"' in page
    # The persisted choice is applied from localStorage before first paint.
    assert 'localStorage.getItem("solarclean-theme")' in page
    js = client.get("/static/dashboard.js").text
    assert 'localStorage.setItem("solarclean-theme"' in js


# --------------------------------------------------------------------------
# Config validate / save
# --------------------------------------------------------------------------


def test_config_validation_paths(client: TestClient) -> None:
    bad_yaml = client.post(
        f"/api/configs/{DEFAULT_CONFIG_NAME}/validate", json={"content": "not: [valid"}
    )
    assert bad_yaml.json()["valid"] is False

    bad_schema = client.post(
        f"/api/configs/{DEFAULT_CONFIG_NAME}/validate", json={"content": "site: {}"}
    )
    assert bad_schema.json()["valid"] is False

    good = client.post(
        f"/api/configs/{DEFAULT_CONFIG_NAME}/validate",
        json={"content": DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")},
    )
    assert good.json()["valid"] is True


def test_config_save_updates_default(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    sandbox = tmp_path / "configs"
    sandbox.mkdir()
    (sandbox / DEFAULT_CONFIG_NAME).write_text(content, encoding="utf-8")
    monkeypatch.setattr(dashboard_app, "_CONFIGS_DIR", sandbox)

    edited = content.replace("run_id_prefix:", "run_id_prefix:", 1)  # identity edit is fine
    saved = client.post(
        f"/api/configs/{DEFAULT_CONFIG_NAME}/validate",
        json={"content": edited, "save_as": DEFAULT_CONFIG_NAME},
    )
    body = saved.json()
    assert body == {"valid": True, "saved": True, "saved_as": DEFAULT_CONFIG_NAME}
    assert (sandbox / DEFAULT_CONFIG_NAME).read_text(encoding="utf-8") == edited

    invalid_name = client.post(
        f"/api/configs/{DEFAULT_CONFIG_NAME}/validate",
        json={"content": edited, "save_as": "../escape.yaml"},
    )
    assert invalid_name.json()["saved"] is False
    assert not (tmp_path / "escape.yaml").exists()


def test_default_config_runs_live_weather_for_riyadh() -> None:
    config = load_config(Path("configs") / DEFAULT_CONFIG_NAME)
    # The Default fetches location-driven NASA POWER weather, so the map picker
    # genuinely changes simulation inputs; the default site stays Riyadh.
    assert config.weather.provider == "nasa_power"
    assert config.site.name == "Riyadh"
    assert config.site.latitude == pytest.approx(24.7136)
    assert config.site.longitude == pytest.approx(46.6753)
    assert config.weather.cache_enabled is True


def test_config_page_states_location_semantics(client: TestClient) -> None:
    page = client.get(f"/config/{DEFAULT_CONFIG_NAME}").text
    # States what a location change does (live NASA POWER weather) and what it
    # does not do (fixture/csv weather is fixed; dust calibration stays Riyadh).
    assert "NASA POWER" in page
    assert "metadata only" in page
    assert "Riyadh central-v2" in page


def test_config_page_has_offline_map_picker(client: TestClient) -> None:
    page = client.get(f"/config/{DEFAULT_CONFIG_NAME}").text
    assert 'id="site-map"' in page
    assert 'viewBox="-180 -90 360 180"' in page  # equirectangular click mapping
    assert 'id="site-lat"' in page and 'id="site-lon"' in page
    assert 'id="apply-location"' in page
    assert "/static/world_land.js" in page

    # The world outline is vendored (offline; no tile servers) and public domain.
    asset = client.get("/static/world_land.js")
    assert asset.status_code == 200
    assert "SOLARCLEAN_WORLD_LAND" in asset.text
    assert "Natural Earth" in asset.text
    assert "public domain" in asset.text


# --------------------------------------------------------------------------
# Artifacts, downloads, traversal
# --------------------------------------------------------------------------


def test_artifact_download_and_traversal_guard(client: TestClient, comparison_run: Path) -> None:
    ok = client.get(f"/api/runs/{comparison_run.name}/artifact/scenario_ranking.json")
    assert ok.status_code == 200
    escaped = client.get(f"/api/runs/{comparison_run.name}/artifact/..%2Fpyproject.toml")
    assert escaped.status_code == 404
    bad_run = client.get("/api/runs/..%2Fconfigs/artifact/riyadh_2025.yaml")
    assert bad_run.status_code == 404


def test_run_zip_contains_all_artifacts(client: TestClient, comparison_run: Path) -> None:
    response = client.get(f"/api/runs/{comparison_run.name}/download")
    assert response.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    on_disk = {path.name for path in comparison_run.iterdir() if path.is_file()}
    assert {name.split("/", 1)[1] for name in names} == on_disk


# --------------------------------------------------------------------------
# Deleting completed runs
# --------------------------------------------------------------------------


def test_delete_run_removes_directory(client: TestClient) -> None:
    run_id = "test-dashboard-disposable-run"
    run_dir = Path("outputs") / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text("{}", encoding="utf-8")

    response = client.delete(f"/api/runs/{run_id}")
    assert response.status_code == 200
    assert response.json() == {"deleted": True, "run_id": run_id}
    assert not run_dir.exists()
    # Gone means gone; and traversal out of outputs/ stays blocked.
    assert client.delete(f"/api/runs/{run_id}").status_code == 404
    assert client.delete("/api/runs/..%2Fconfigs").status_code == 404


def test_empty_run_shells_are_hidden_and_swept(tmp_path: Path) -> None:
    # A sync client (OneDrive) can briefly block removing the empty directory
    # shell after a delete; such shells must not reappear as runs.
    outputs = tmp_path / "outputs"
    (outputs / "real-run-compare-all-scenarios-x").mkdir(parents=True)
    (outputs / "real-run-compare-all-scenarios-x" / "summary.json").write_text(
        "{}", encoding="utf-8"
    )
    (outputs / "husk-compare-all-scenarios-y").mkdir()
    entries = artifacts_module.list_runs(outputs)
    assert [entry.run_id for entry in entries] == ["real-run-compare-all-scenarios-x"]
    assert not (outputs / "husk-compare-all-scenarios-y").exists()  # swept


def test_runs_table_offers_delete_controls(client: TestClient, comparison_run: Path) -> None:
    page = client.get("/").text
    assert 'class="run-select"' in page  # bulk-select checkboxes
    assert "Delete selected" in page
    assert 'class="danger-quiet run-delete"' in page
    assert "permanently removes its directory" in page  # destructive action is spelled out


# --------------------------------------------------------------------------
# Parameter dropdowns
# --------------------------------------------------------------------------


def test_launch_form_offers_parameter_dropdowns(client: TestClient) -> None:
    page = client.get("/").text
    assert '<select id="parameters" multiple' in page
    assert '<select id="parameter-a">' in page
    assert '<select id="be-parameter">' in page
    # Options come from the T7-supported registry catalog with their ranges.
    assert 'value="economics.electricity_tariff_sar_per_kwh"' in page
    assert "registry range" in page


# --------------------------------------------------------------------------
# Analysis-page charts (tornado, winner map, MC distribution, break-even)
# --------------------------------------------------------------------------


def _delete_run(client: TestClient, run_dir: Path) -> None:
    assert client.delete(f"/api/runs/{run_dir.name}").status_code == 200


def test_oneway_page_renders_tornado(client: TestClient, stub_run_variant: None) -> None:
    outcome = OneWaySensitivityExperiment(
        fixture_config(),
        parameter_names=["economics.electricity_tariff_sar_per_kwh"],
        steps=3,
    ).run()
    page = client.get(f"/run/{outcome.output_directory.name}").text
    assert 'id="tornado-chart"' in page
    assert "net-benefit swing" in page
    _delete_run(client, outcome.output_directory)


def test_winner_map_page_renders_heatmap(client: TestClient, stub_run_variant: None) -> None:
    outcome = TwoWaySensitivityExperiment(
        fixture_config(),
        parameter_name_a="economics.electricity_tariff_sar_per_kwh",
        parameter_name_b="economics.labour_cost_sar_per_hour",
        grid_steps=3,
    ).run()
    page = client.get(f"/run/{outcome.output_directory.name}").text
    assert 'class="winner-map"' in page
    assert "wm-cell" in page
    assert "wm-baseline" in page  # stubbed variants always crown baseline
    _delete_run(client, outcome.output_directory)


def test_breakeven_page_renders_crossing_chart(client: TestClient, stub_run_variant: None) -> None:
    outcome = BreakEvenExperiment(
        fixture_config(),
        parameter_name="economics.electricity_tariff_sar_per_kwh",
        scenario_a="coating",
        scenario_b="baseline",
    ).run()
    page = client.get(f"/run/{outcome.output_directory.name}").text
    assert 'id="breakeven-chart"' in page
    assert "crosses zero" in page
    _delete_run(client, outcome.output_directory)


def test_monte_carlo_page_renders_trials_distribution(client: TestClient) -> None:
    # Synthetic artifacts: the offline fixture's MC trials do not reconcile
    # (blocking assumption warnings), and unreconciled trials are rightly
    # excluded from the chart — so exercise the rendering path with a couple
    # of reconciled trial rows written in the real CSV shape.
    run_dir = Path("outputs") / "test-dashboard-monte-carlo-page"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "monte_carlo_trials.csv").write_text(
        "trial_index,seed,reconciled,winner,"
        "baseline_net_annual_benefit_sar,reactive_net_annual_benefit_sar,"
        "coating_net_annual_benefit_sar\n"
        "0,1,True,reactive,100.0,220.0,180.0\n"
        "1,2,True,reactive,110.0,230.0,150.0\n"
        "2,3,False,,0.0,0.0,0.0\n",
        encoding="utf-8",
    )
    summary = {
        "trial_count": 3,
        "reconciled_trial_count": 2,
        "failed_trial_count": 1,
        "central_t6_winner": "reactive",
        "majority_trial_winner": "reactive",
        "uncertainty_mode": "stochastic_seed_only",
        "base_seed": 42,
        "scenario_summaries": {
            "reactive": {
                "win_probability": 1.0,
                "mean_net_annual_benefit_sar": 225.0,
                "std_net_annual_benefit_sar": 5.0,
                "p5_net_annual_benefit_sar": 220.0,
                "p95_net_annual_benefit_sar": 230.0,
            }
        },
    }
    (run_dir / "monte_carlo_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    try:
        page = client.get(f"/run/{run_dir.name}").text
        assert 'id="mc-trials-chart"' in page
        assert "one dot per trial" in page
        # The unreconciled trial is excluded from the chart payload.
        assert '"reactive": [220.0, 230.0]' in page
    finally:
        _delete_run(client, run_dir)


# --------------------------------------------------------------------------
# Headline cards, glossary, provenance, cumulative gain
# --------------------------------------------------------------------------


def test_comparison_page_shows_headline_cards(client: TestClient, comparison_run: Path) -> None:
    # The 2-day fixture run yields no valid recommendation (T6 blocks
    # non-full-year rankings), so its page must show no headline cards ...
    page = client.get(f"/run/{comparison_run.name}").text
    assert 'class="headline-card"' not in page

    # ... while a run with a valid stored recommendation gets them.
    run_dir = Path("outputs") / "test-dashboard-compare-all-scenarios-headline"
    run_dir.mkdir(parents=True, exist_ok=True)
    recommendation = {
        "valid": True,
        "winner": "coating",
        "decisive_margin_sar": 12345.6,
        "kpi_snapshot": {
            "coating": {
                "net_annual_benefit_sar": 734918.1,
                "energy_gain_vs_baseline_kwh": 448938.0,
                "incremental_payback_years_vs_baseline": 5.76,
            }
        },
        "assumptions": [],
        "warnings": [],
    }
    (run_dir / "recommendation.json").write_text(json.dumps(recommendation), encoding="utf-8")
    try:
        page = client.get(f"/run/{run_dir.name}").text
        assert "Recommended strategy" in page
        assert 'class="headline-card"' in page
        assert "Net annual benefit" in page
        assert "Margin over runner-up" in page
        assert "734,918" in page  # stored value, formatted for reading
    finally:
        _delete_run(client, run_dir)


def test_kpi_glossary_is_plain_english(client: TestClient, comparison_run: Path) -> None:
    page = client.get(f"/run/{comparison_run.name}").text
    assert "What these metrics mean" in page
    assert "Levelized cost of energy" in page
    assert "Return on investment" in page


def test_run_page_shows_weather_provenance(client: TestClient, comparison_run: Path) -> None:
    page = client.get(f"/run/{comparison_run.name}").text
    assert "Weather provider" in page
    assert "fixture" in page  # the offline test run's provider, stated on the page
    assert "Weather checksum" in page
    # Site coordinates come from the run's own config_resolved.yaml.
    assert "24.7136" in page and "46.6753" in page


def test_cumulative_gain_column_reconciles_and_charts(
    client: TestClient, comparison_run: Path
) -> None:
    header, rows = artifacts_module.read_csv_rows(comparison_run / "scenario_daily_summary.csv")
    assert "cumulative_energy_gain_vs_baseline_kwh" in header
    cum_col = header.index("cumulative_energy_gain_vs_baseline_kwh")
    scen_col = header.index("scenario_name")
    last_coating = [float(row[cum_col]) for row in rows if row[scen_col] == "coating"][-1]

    annual_header, annual_rows = artifacts_module.read_csv_rows(
        comparison_run / "scenario_annual_summary.csv"
    )
    gain_col = annual_header.index("energy_gain_vs_baseline_kwh")
    annual_scen_col = annual_header.index("scenario_name")
    annual_gain = next(
        float(row[gain_col]) for row in annual_rows if row[annual_scen_col] == "coating"
    )
    # The stored running total must land exactly on the stored annual gain.
    assert last_coating == pytest.approx(annual_gain, abs=1e-6)

    page = client.get(f"/run/{comparison_run.name}").text
    assert 'id="daily-cumgain-chart"' in page


# --------------------------------------------------------------------------
# Persistent job history + re-run
# --------------------------------------------------------------------------


def test_job_history_survives_registry_restart(tmp_path: Path) -> None:
    history = tmp_path / "jobs.json"
    registry = JobRegistry(history_path=history)
    job = registry.submit("compare", "x.yaml", lambda job: Path("outputs/fake"))
    # The record is persisted in the worker's finally block, just after the
    # status flips to done — poll for the file, not the status.
    deadline = time.time() + 10
    while not history.is_file() and time.time() < deadline:
        time.sleep(0.02)
    assert job.status == "done"
    assert history.is_file()

    reborn = JobRegistry(history_path=history)
    records = reborn.records()
    assert [record["job_id"] for record in records] == [job.job_id]
    assert reborn.get_record(job.job_id) is not None
    # Deleting a historical session removes it from the persisted file too.
    assert reborn.delete(job.job_id) is not None
    assert JobRegistry(history_path=history).records() == []


def test_rerun_repeats_an_analysis_from_its_config_snapshot(
    client: TestClient, comparison_run: Path
) -> None:
    page = client.get(f"/run/{comparison_run.name}").text
    assert 'id="rerun-btn"' in page

    launched = client.post(f"/api/runs/{comparison_run.name}/rerun")
    assert launched.status_code == 202
    record = launched.json()
    assert record["config_name"] == f"re-run of {comparison_run.name}"

    deadline = time.time() + 120
    while time.time() < deadline:
        record = client.get(f"/api/jobs/{record['job_id']}").json()
        if record["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert record["status"] == "done", record.get("error")
    assert record["run_id"] != comparison_run.name  # a new run directory
    # Tidy up: drop the session and the produced run directory.
    assert client.delete(f"/api/jobs/{record['job_id']}").status_code == 200
    assert client.delete(f"/api/runs/{record['run_id']}").status_code == 200


def test_rerun_unknown_run_is_404(client: TestClient) -> None:
    assert client.post("/api/runs/no-such-run/rerun").status_code == 404


# --------------------------------------------------------------------------
# Auth token + concurrency guard
# --------------------------------------------------------------------------


def test_auth_token_gates_every_route(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLARCLEAN_DASHBOARD_TOKEN", "s3cret")
    assert client.get("/").status_code == 401
    assert client.get("/static/dashboard.js").status_code == 401
    assert client.post("/api/runs", json={"kind": "compare"}).status_code == 401
    # Any username; the token is the Basic-auth password.
    assert client.get("/", auth=("anyone", "s3cret")).status_code == 200
    assert client.get("/", auth=("anyone", "wrong")).status_code == 401
    monkeypatch.delenv("SOLARCLEAN_DASHBOARD_TOKEN")
    assert client.get("/").status_code == 200  # workstation default stays open


def test_launch_rejects_concurrent_runs(client: TestClient, comparison_run: Path) -> None:
    release = threading.Event()

    def work(job: Job) -> Path:
        release.wait(timeout=30)
        return Path("outputs/fake")

    job = dashboard_app.jobs.submit("compare", "synthetic.yaml", work)
    try:
        blocked = client.post("/api/runs", json={"kind": "compare"})
        assert blocked.status_code == 409
        assert "already" in blocked.json()["detail"]
        rerun_blocked = client.post(f"/api/runs/{comparison_run.name}/rerun")
        assert rerun_blocked.status_code == 409
    finally:
        release.set()
    deadline = time.time() + 10
    while job.status != "done" and time.time() < deadline:
        time.sleep(0.02)
    assert dashboard_app.jobs.delete(job.job_id) is not None


# --------------------------------------------------------------------------
# Web readiness / deployment assumptions
# --------------------------------------------------------------------------


def test_data_directories_are_environment_overridable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SOLARCLEAN_CONFIGS_DIR", str(tmp_path / "cfg"))
    resolved = dashboard_app._directory_from_env("SOLARCLEAN_CONFIGS_DIR", Path("fallback"))
    assert resolved == tmp_path / "cfg"
    monkeypatch.delenv("SOLARCLEAN_CONFIGS_DIR")
    assert dashboard_app._directory_from_env("SOLARCLEAN_CONFIGS_DIR", Path("fallback")) == Path(
        "fallback"
    )


def test_bind_address_is_environment_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOLARCLEAN_DASHBOARD_HOST", raising=False)
    monkeypatch.delenv("SOLARCLEAN_DASHBOARD_PORT", raising=False)
    assert resolve_bind() == ("127.0.0.1", 8050)  # workstation default stays safe

    monkeypatch.setenv("SOLARCLEAN_DASHBOARD_HOST", "0.0.0.0")
    monkeypatch.setenv("SOLARCLEAN_DASHBOARD_PORT", "9000")
    assert resolve_bind() == ("0.0.0.0", 9000)

    monkeypatch.setenv("SOLARCLEAN_DASHBOARD_PORT", "not-a-port")
    with pytest.raises(SystemExit):
        resolve_bind()
