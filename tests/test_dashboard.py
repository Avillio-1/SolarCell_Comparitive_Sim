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

import csv
import io
import json
import os
import shutil
import stat
import threading
import time
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

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
from solarclean.config.models import SolarCleanConfig  # noqa: E402
from solarclean.dashboard import app as dashboard_app  # noqa: E402
from solarclean.dashboard import artifacts as artifacts_module  # noqa: E402
from solarclean.dashboard.__main__ import resolve_bind  # noqa: E402
from solarclean.dashboard.app import (  # noqa: E402
    DEFAULT_CONFIG_NAME,
    _cost_table,
    _financial_ranking,
    _format_sar,
    _kpi_table,
    app,
)
from solarclean.dashboard.jobs import ActiveJobError, Job, JobCancelled, JobRegistry  # noqa: E402


@pytest.fixture(scope="module")
def comparison_run() -> Path:
    result = CompareAllScenarios(fixture_config()).run()
    return result.output_directory


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# --------------------------------------------------------------------------
# Configuration selection
# --------------------------------------------------------------------------


def test_index_offers_available_configurations(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert '<select id="config"' in response.text
    assert f"/config/{DEFAULT_CONFIG_NAME}" in response.text
    assert f'value="{DEFAULT_CONFIG_NAME}"' in response.text
    assert 'value="dammam_humid_desert.yaml"' in response.text
    assert 'value="riyadh_dry_desert.yaml"' in response.text
    assert "Configuration" in response.text
    assert 'id="start-date"' in response.text
    assert 'id="end-date"' in response.text
    assert 'data-start="2025-01-01"' in response.text


def test_launch_rejects_unknown_kind(client: TestClient) -> None:
    response = client.post("/api/runs", json={"kind": "warp-drive"})
    assert response.status_code == 400


def test_launch_period_override_uses_whole_days_in_config_timezone(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(fixture_config().model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    options = dashboard_app.LaunchRequest(
        kind="compare",
        start_date=date(2024, 2, 1),
        end_date=date(2024, 2, 29),
    )

    resolved = dashboard_app._load_run_config(config_path, options)

    assert resolved.simulation.start.isoformat() == "2024-02-01T00:00:00+03:00"
    assert resolved.simulation.end.isoformat() == "2024-02-29T23:00:00+03:00"
    assert resolved.simulation.target_timezone == "Asia/Riyadh"


def test_launch_period_override_requires_two_ordered_dates(client: TestClient) -> None:
    missing_end = client.post(
        "/api/runs",
        json={"kind": "compare", "start_date": "2024-01-01"},
    )
    reversed_period = client.post(
        "/api/runs",
        json={
            "kind": "compare",
            "start_date": "2024-02-01",
            "end_date": "2024-01-01",
        },
    )

    assert missing_end.status_code == 422
    assert reversed_period.status_code == 422


def test_launch_runs_selected_config_and_reports_progress(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Point both names at the fast 2-day fixture so the test finishes quickly;
    # the route logic is identical for the real full-year configurations.
    sandbox = tmp_path / "configs"
    sandbox.mkdir()
    (sandbox / DEFAULT_CONFIG_NAME).write_text(
        yaml.safe_dump(fixture_config().model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    selected_name = "dammam_humid_desert.yaml"
    (sandbox / selected_name).write_text(
        yaml.safe_dump(fixture_config().model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_app, "_CONFIGS_DIR", sandbox)
    launched = client.post("/api/runs", json={"kind": "compare", "config": selected_name})
    assert launched.status_code == 202
    record = launched.json()
    assert record["config_name"] == selected_name

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
    deadline = time.time() + 10
    while job.finished_at is None and time.time() < deadline:
        time.sleep(0.02)
    assert job.finished_at is not None
    assert job.job_id not in registry._jobs


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
        # Net annual benefit is displayed with readable currency grouping.
        assert _format_sar(entry["net_annual_benefit_sar"]) in page


def test_financial_ranking_explains_total_and_baseline_change(
    client: TestClient,
    comparison_run: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    run_dir = outputs / "test-financial-ranking-compare-all-scenarios-20260714"
    shutil.copytree(comparison_run, run_dir)
    with (run_dir / "scenario_annual_summary.csv").open(encoding="utf-8", newline="") as handle:
        annual_rows = list(csv.DictReader(handle))
    ranking_rows = [
        {
            "rank": rank,
            "scenario_id": row["scenario_name"],
            "annual_actual_energy_kwh": float(row["annual_actual_energy_kwh"]),
            "energy_gain_vs_baseline_kwh": float(row["energy_gain_vs_baseline_kwh"]),
            "net_annual_benefit_sar": float(row["net_annual_benefit_sar"]),
            "tied_with_previous": False,
        }
        for rank, row in enumerate(annual_rows, start=1)
    ]
    (run_dir / "scenario_ranking.json").write_text(
        json.dumps({"ranking": ranking_rows}), encoding="utf-8"
    )
    (run_dir / "recommendation.json").write_text(
        json.dumps(
            {
                "calculation_valid": True,
                "valid": True,
                "winner": ranking_rows[0]["scenario_id"],
                "recommendation_tier": "exploratory",
                "warnings": [],
                "assumptions": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "reconciliation_report.json").write_text(
        json.dumps({"passed": True, "checks": []}), encoding="utf-8"
    )
    monkeypatch.setattr(dashboard_app, "_OUTPUTS_DIR", outputs)

    page = client.get(f"/run/{run_dir.name}").text

    assert "Ranking by annual financial outcome" in page
    assert "Value of extra energy" in page
    assert "Net change" in page and "vs baseline" in page
    assert "0.18 SAR/kWh" in page
    assert "Cost boundary:" in page
    # The decision strip answers the question visually, above the arithmetic.
    assert 'class="decision-strip"' in page
    assert "Net change vs doing nothing" in page
    assert "0 · reference" in page
    first = ranking_rows[0]
    assert f"How {_format_sar(first['net_annual_benefit_sar'])} SAR/year is calculated" in page
    assert "annual AC energy ×" in page
    assert "incremental_net_annual_benefit_vs_baseline_sar" in page


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
    assert 'id="energy-explorer"' in page
    assert 'data-energy-scenario="baseline"' in page
    assert 'data-energy-scenario="compare"' in page
    assert "daily-ghi-chart" in page
    assert "daily-temperature-chart" in page
    assert "daily-rainfall-chart" in page
    assert "daily-events-chart" in page
    assert 'class="selected-day-panel"' in page
    assert 'id="selected-day-date"' in page
    assert 'id="follow-hover-button"' in page
    assert "environmental values are context, not independent causal attribution" in page
    # The explorer is the single daily instrument: loss, cleanliness, and
    # cumulative gain are metric-switcher views of the same chart, not
    # separate panels, and the stored series still reach the page payload.
    assert 'data-energy-metric="energy"' in page
    assert 'data-energy-metric="loss"' in page
    assert 'data-energy-metric="cleanliness"' in page
    assert "dailyLoss:" in page
    assert "dailySoiling:" in page
    assert 'id="daily-loss-chart"' not in page
    assert 'id="daily-soiling-chart"' not in page
    # The full-width fingerprint doubles as the range scrubber.
    assert 'id="explorer-scrubber"' in page
    assert 'id="scrubber-reset"' in page
    dashboard_js = Path(dashboard_app.__file__).parent / "static" / "dashboard.js"
    dashboard_script = dashboard_js.read_text(encoding="utf-8")
    assert "drawEnergyExplorer" in dashboard_script
    assert "applyExplorerScenario" in dashboard_script
    assert "applyExplorerMetric" in dashboard_script
    assert "Resume hover" in dashboard_script
    # The duplicate annual money bar chart was removed; the decision strip,
    # financial ledger, and KPI table remain the authoritative annual views.
    assert "annual-cost-chart" not in page
    assert 'id="annual-chart"' not in page
    # ... and no inline <img> plot grid on the comparison page. PNGs stay
    # downloadable from the artifact list.
    assert '<div class="plot-grid">' not in page
    assert "comparison_daily_energy.png" in page  # still listed as an artifact


def test_comparison_page_has_water_balance_and_dew_simulator(
    client: TestClient,
    comparison_run: Path,
) -> None:
    page = client.get(f"/run/{comparison_run.name}").text

    assert 'id="water-balance"' in page
    assert "Water balance by strategy" in page
    assert "Net water position" in page
    assert "Cleaning water consumed" in page
    assert "Dew harvested" in page
    assert "Tank equivalents" in page
    assert "Dew-eligible nights" in page
    assert "m³" in page
    assert "alternative operating strategy" in page

    assert 'id="dew-simulator"' in page
    assert "Humidity &amp; dew-point simulator" in page
    assert 'id="dew-relative-humidity"' in page
    assert 'id="dew-air-temperature"' in page
    assert 'id="dew-wind-speed"' in page
    assert 'id="humidity-indicator"' in page
    assert 'aria-live="polite"' in page


def test_dew_simulator_endpoint_uses_the_run_config(
    client: TestClient,
    comparison_run: Path,
) -> None:
    response = client.get(
        f"/api/runs/{comparison_run.name}/dew-simulator",
        params={
            "relative_humidity_pct": 80,
            "air_temperature_c": 25,
            "wind_speed_m_s": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["relative_humidity_pct"] == pytest.approx(80.0)
    assert payload["air_temperature_c"] == pytest.approx(25.0)
    assert payload["wind_speed_m_s"] == pytest.approx(2.0)
    assert payload["coated_area_m2"] == pytest.approx(20_000.0)
    assert "dew_point_c" in payload
    assert "coated_surface_temperature_c" in payload
    assert "harvested_liters_per_m2_hour" in payload
    assert "whole_farm_harvested_liters_per_hour" in payload
    # This fixture deliberately resets coating water to the disabled legacy
    # config; the endpoint must honor that stored snapshot instead of Default.
    assert payload["status_code"] == "water_model_disabled"


def test_explorer_payload_matches_stored_series(client: TestClient, comparison_run: Path) -> None:
    """The chart payload's series come from aligned stored artifact columns."""
    page = client.get(f"/run/{comparison_run.name}").text
    cleanliness = artifacts_module.daily_cleanliness_series(comparison_run)
    assert cleanliness is not None
    assert set(cleanliness["series"]) == {"baseline", "reactive", "coating"}
    rainfall = artifacts_module.daily_rainfall_series(comparison_run)
    assert rainfall is not None
    assert rainfall["dates"] == cleanliness["dates"]
    assert len(rainfall["values"]) == len(rainfall["dates"])
    assert "dailyRainfall:" in page
    humidity = artifacts_module.daily_relative_humidity_series(comparison_run)
    assert humidity is not None
    assert humidity["dates"] == rainfall["dates"]
    assert len(humidity["values"]) == len(humidity["dates"])
    assert all(value is None or 0 <= value <= 100 for value in humidity["values"])
    assert "dailyHumidity:" in page
    clean_reference = artifacts_module.daily_clean_reference_series(comparison_run)
    assert clean_reference is not None
    assert clean_reference["dates"] == rainfall["dates"]
    weather = artifacts_module.daily_weather_diagnostics(comparison_run)
    assert weather is not None
    assert weather["dates"] == rainfall["dates"]
    assert len(weather["daily_ghi_irradiation_kwh_m2"]) == len(rainfall["dates"])
    markers = artifacts_module.daily_event_markers(comparison_run)
    assert markers
    assert {marker["category"] for marker in markers} <= {
        "cleaning",
        "inspection",
        "coating",
        "contamination",
    }
    assert "dailyCleanReference:" in page
    assert "dailyWeather:" in page
    assert "dailyEventMarkers:" in page


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
    assert by_label["External cleaning water consumed (L)"]["best"] == [False, False, False]


def test_financial_ranking_joins_stored_explanation_values_without_recalculation() -> None:
    header = [
        "scenario_name",
        "annual_actual_energy_kwh",
        "annual_revenue_sar",
        "annualized_capex_sar",
        "annual_opex_sar",
        "total_annual_cost_sar",
        "net_annual_benefit_sar",
        "incremental_revenue_vs_baseline_sar",
        "incremental_annual_cost_vs_baseline_sar",
        "incremental_net_annual_benefit_vs_baseline_sar",
        "total_capex_sar",
        "capital_recovery_life_years",
    ]
    rows = [
        ["baseline", "1000", "180", "0", "0", "0", "180", "0", "0", "0", "0", "15"],
        # Deliberately non-arithmetic values prove the dashboard passes stored
        # cells through instead of becoming a second economics engine.
        [
            "reactive",
            "2000",
            "999",
            "111",
            "222",
            "333",
            "777",
            "444",
            "555",
            "-666",
            "1500",
            "3",
        ],
    ]
    ranking = {
        "ranking": [
            {"rank": 1, "scenario_id": "baseline", "net_annual_benefit_sar": 180.0},
            {"rank": 2, "scenario_id": "reactive", "net_annual_benefit_sar": 777.0},
        ]
    }
    metadata = {
        "economics_config": {
            "tariff_sar_per_kwh": 0.18,
            "annualization_method": "capital_recovery_factor",
        }
    }

    result = _financial_ranking(header, rows, ranking, metadata)

    assert result is not None
    assert result["tariff_sar_per_kwh"] == 0.18
    assert result["annualization_method"] == "capital recovery factor"
    reactive = result["rows"][1]
    assert reactive["annual_revenue_sar"] == "999"
    assert reactive["incremental_revenue_sar"] == "444"
    assert reactive["incremental_annual_cost_sar"] == "555"
    assert reactive["incremental_net_annual_benefit_sar"] == "-666"
    assert reactive["net_annual_benefit_sar"] == 777.0


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
            "crew_hours=580.8 hour; unit_rate=35 SAR/hour",
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
    reconciliation = {
        "checks": [
            {
                "name": "reactive_cost_crew_hours_reconciles",
                "passed": True,
                "message": "OK",
            }
        ]
    }
    table = _cost_table(header, rows, reconciliation)
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
    crew_audit = groups["opex"]["components"][0]["audit"]
    assert "crew_hours 580.8 hour × 35 SAR/hour = 20,328 SAR/year" in crew_audit["detail"]
    assert crew_audit["source"] == "scenario_cost_summary.csv · row 3"
    assert "reconciliation check #1 ✓" in crew_audit["check"]


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


def test_config_page_can_reset_to_riyadh_defaults(client: TestClient) -> None:
    page = client.get(f"/config/{DEFAULT_CONFIG_NAME}")
    assert page.status_code == 200
    assert 'id="reset-config-btn"' in page.text
    assert "Reset to Riyadh defaults" in page.text

    script = client.get("/static/dashboard.js").text
    assert "configEditor.originalContent = configEditor.value" in script
    assert "editor.savedContent = payload.content" in script
    assert 'editor.dataset.isDefault !== "true"' in script
    assert '"/factory-default"' in script
    assert "Original Riyadh defaults restored in the editor." in script
    assert "resetContent" not in script
    assert "syncSiteLocationFromEditor(editor)" in script


def test_factory_default_is_immutable_riyadh_preset(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = tmp_path / "configs"
    sandbox.mkdir()
    (sandbox / DEFAULT_CONFIG_NAME).write_text(
        DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(dashboard_app, "_CONFIGS_DIR", sandbox)

    response = client.get(f"/api/configs/{DEFAULT_CONFIG_NAME}/factory-default")
    assert response.status_code == 200
    restored = SolarCleanConfig.model_validate(yaml.safe_load(response.json()["content"]))
    assert restored.site.name == "Riyadh"
    assert restored.site.latitude == pytest.approx(24.7136)
    assert restored.site.longitude == pytest.approx(46.6753)
    assert restored.site.timezone == "Asia/Riyadh"
    assert restored.simulation.target_timezone == "Asia/Riyadh"
    assert restored.simulation.run_id_prefix == "default-riyadh"


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


def test_nondefault_config_page_is_not_saveable(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = tmp_path / "configs"
    sandbox.mkdir()
    content = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    (sandbox / DEFAULT_CONFIG_NAME).write_text(content, encoding="utf-8")
    other_name = "dammam_humid_desert.yaml"
    (sandbox / other_name).write_text(content, encoding="utf-8")
    monkeypatch.setattr(dashboard_app, "_CONFIGS_DIR", sandbox)

    page = client.get(f"/config/{other_name}")
    assert page.status_code == 200
    assert 'id="validate-btn"' in page.text
    assert 'id="save-default-btn"' not in page.text


def test_factory_default_runs_live_weather_for_riyadh() -> None:
    config = load_config(dashboard_app._RIYADH_DEFAULT_CONFIG_PATH)
    # The immutable factory preset stays Riyadh even when the editable Default
    # has been saved with another site through the dashboard.
    assert config.weather.provider == "nasa_power"
    assert config.site.name == "Riyadh"
    assert config.site.latitude == pytest.approx(24.7136)
    assert config.site.longitude == pytest.approx(46.6753)
    assert config.weather.cache_enabled is True


def test_config_page_states_location_semantics(client: TestClient) -> None:
    page = client.get(f"/config/{DEFAULT_CONFIG_NAME}").text
    # States what a location change does (live NASA POWER weather), the fixed
    # calibration assumption, and the humidity-coupled exceptions.
    assert "NASA POWER" in page
    assert "Riyadh central-v2" in page
    assert "humidity-coupled soiling" in page


def test_config_page_has_offline_map_picker(client: TestClient) -> None:
    page = client.get(f"/config/{DEFAULT_CONFIG_NAME}").text
    assert 'id="site-map"' in page
    assert 'viewBox="-180 -90 360 180"' in page  # equirectangular click mapping
    assert 'id="site-lat"' in page and 'id="site-lon"' in page
    assert 'id="site-timezone"' in page
    assert 'id="site-timezone" type="text" readonly' in page
    assert "timezone is detected automatically" in page
    assert 'id="apply-location"' in page
    assert "/static/world_land.js" in page

    # The world outline is vendored (offline; no tile servers) and public domain.
    asset = client.get("/static/world_land.js")
    assert asset.status_code == 200
    assert "SOLARCLEAN_WORLD_LAND" in asset.text
    assert "Natural Earth" in asset.text
    assert "public domain" in asset.text


def test_config_page_prefills_and_sends_site_name(client: TestClient) -> None:
    page = client.get(f"/config/{DEFAULT_CONFIG_NAME}").text
    assert 'id="site-name"' in page

    script = client.get("/static/dashboard.js").text
    assert 'nameInput.value = parseYamlTextScalar(editor.value, "name")' in script
    assert "site_name: nameInput ? nameInput.value : null" in script


def test_apply_location_updates_timezones_and_dst_offsets(client: TestClient) -> None:
    content = dashboard_app._RIYADH_DEFAULT_CONFIG_PATH.read_text(encoding="utf-8").replace(
        'start: "2025-01-01T00:00:00+03:00"',
        'start: "2025-06-01T00:00:00+03:00"',
    )

    response = client.post(
        f"/api/configs/{DEFAULT_CONFIG_NAME}/apply-location",
        json={
            "content": content,
            "latitude": 52.52,
            "longitude": 13.405,
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["valid"] is True
    assert result["timezone"] == "Europe/Berlin"
    assert result["start"] == "2025-06-01T00:00:00+02:00"
    assert result["end"] == "2025-12-31T23:00:00+01:00"
    updated = SolarCleanConfig.model_validate(yaml.safe_load(result["content"]))
    assert updated.site.latitude == pytest.approx(52.52)
    assert updated.site.longitude == pytest.approx(13.405)
    assert updated.site.timezone == "Europe/Berlin"
    assert updated.simulation.target_timezone == "Europe/Berlin"


def test_apply_location_replaces_site_name_with_quoted_yaml(client: TestClient) -> None:
    content = dashboard_app._RIYADH_DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    site_name = 'Berlin Test Site (East): "Array A"'

    response = client.post(
        f"/api/configs/{DEFAULT_CONFIG_NAME}/apply-location",
        json={
            "content": content,
            "site_name": site_name,
            "latitude": 52.52,
            "longitude": 13.405,
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["valid"] is True
    assert f"  name: {json.dumps(site_name)}" in result["content"]
    updated = SolarCleanConfig.model_validate(yaml.safe_load(result["content"]))
    assert updated.site.name == site_name


@pytest.mark.parametrize(
    ("latitude", "longitude", "expected"),
    [
        (24.7136, 46.6753, "Asia/Riyadh"),
        (40.7128, -74.0060, "America/New_York"),
    ],
)
def test_timezone_is_detected_from_coordinates(
    latitude: float, longitude: float, expected: str
) -> None:
    assert dashboard_app._timezone_at(latitude, longitude) == expected


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


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only directory behavior")
def test_delete_run_clears_readonly_directories(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = tmp_path / "outputs"
    run_dir = outputs / "readonly-run"
    nested = run_dir / "readonly-onedrive-placeholder"
    nested.mkdir(parents=True)
    nested.chmod(stat.S_IREAD)
    run_dir.chmod(stat.S_IREAD)
    monkeypatch.setattr(dashboard_app, "_OUTPUTS_DIR", outputs)

    response = client.delete(f"/api/runs/{run_dir.name}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "run_id": run_dir.name}
    assert not run_dir.exists()


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


def test_runs_table_shows_site_from_stored_config(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = tmp_path / "outputs"
    run_dir = outputs / "dammam-compare-all-scenarios-20260711T000000Z-abc123"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text("{}", encoding="utf-8")
    (run_dir / "config_resolved.yaml").write_text(
        yaml.safe_dump({"site": {"name": "Dammam (humid coastal desert)"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_app, "_OUTPUTS_DIR", outputs)

    page = client.get("/")
    assert page.status_code == 200
    assert "Dammam (humid coastal desert)" in page.text


def test_run_entry_reads_current_created_at_timestamp(tmp_path: Path) -> None:
    run_dir = tmp_path / "sample-compare-all-scenarios-20260711T000000Z-abc123"
    run_dir.mkdir()
    (run_dir / "metadata.json").write_text(
        json.dumps({"created_at_utc": "2026-07-11T12:00:00+00:00"}), encoding="utf-8"
    )

    entries = artifacts_module.list_runs(tmp_path)

    assert len(entries) == 1
    assert entries[0].created == "2026-07-11T12:00:00+00:00"


def test_compare_runs_renders_stored_provenance_and_kpis(
    client: TestClient, comparison_run: Path
) -> None:
    other = Path("outputs") / "test-dashboard-compare-runs-other-compare-all-scenarios"
    other.mkdir(parents=True, exist_ok=True)
    (other / "config_resolved.yaml").write_text(
        yaml.safe_dump(
            {
                "site": {
                    "name": "Dammam (humid coastal desert)",
                    "latitude": 26.42,
                    "longitude": 50.09,
                },
                "weather": {"provider": "fixture"},
            }
        ),
        encoding="utf-8",
    )
    (other / "metadata.json").write_text(
        json.dumps({"created_utc": "2026-07-11T12:00:00Z", "weather_checksum": "abc123"}),
        encoding="utf-8",
    )
    (other / "scenario_annual_summary.csv").write_text(
        "scenario_name,annual_actual_energy_kwh,annual_energy_loss_percent,net_annual_benefit_sar\n"
        "baseline,1000,10,100\ncoating,1100,5,200\n",
        encoding="utf-8",
    )
    try:
        page = client.get("/compare-runs", params={"a": comparison_run.name, "b": other.name})
        assert page.status_code == 200
        assert "Two-run comparison" in page.text
        assert comparison_run.name in page.text
        assert other.name in page.text
        assert "Dammam (humid coastal desert)" in page.text
        assert "Annual KPIs" in page.text
        # Different sites are alternatives, not iterations: neutral A/B labels.
        assert "RUN A" in page.text
        assert "A · BEFORE" not in page.text
        assert "diff-value-a" in page.text and "diff-value-b" in page.text
        assert "diff-old" not in page.text and "diff-new" not in page.text
        assert "Run A and Run B use neutral shading." in page.text
    finally:
        client.delete(f"/api/runs/{other.name}")


# --------------------------------------------------------------------------
# Parameter dropdowns
# --------------------------------------------------------------------------


def test_launch_form_offers_parameter_dropdowns(client: TestClient) -> None:
    page = client.get("/").text
    # Native selects remain the state store and no-JS fallback; the JS picker
    # (searchable grouped checklist with inline ranges) mounts next to them.
    assert '<select id="parameters" multiple' in page
    assert '<select id="parameter-a"' in page
    assert '<select id="be-parameter"' in page
    assert 'data-picker-for="parameters"' in page
    assert 'data-picker-for="parameter-a"' in page
    assert 'data-picker-for="be-parameter"' in page
    assert "window.solarcleanParameters" in page
    assert 'id="oneway-workload"' in page
    assert "Choose at least one assumption" in page
    # Options come from the T7-supported registry catalog with their ranges.
    assert 'value="economics.electricity_tariff_sar_per_kwh"' in page
    assert "data-low=" in page
    assert "data-high=" in page
    assert "registry range" in page
    script = client.get("/static/dashboard.js").text
    assert "initParameterPickers" in script
    assert "param-range-tick" in script
    assert 'selectAll.textContent = "Select all"' in script
    assert "comparison evaluations" in script
    assert "Choose at least one parameter for one-way sensitivity." in script
    assert "none selected = all supported" not in script


def test_oneway_launch_requires_an_explicit_parameter(client: TestClient) -> None:
    response = client.post(
        "/api/runs",
        json={"kind": "sensitivity-oneway", "config": DEFAULT_CONFIG_NAME, "parameters": []},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == ("Choose at least one parameter for one-way sensitivity.")


def test_launch_form_asks_the_question_first(client: TestClient) -> None:
    # Analysis kinds are question radio cards; the method name is fine print.
    page = client.get("/").text
    assert 'id="kind-cards"' in page
    assert "What question should the model answer?" in page
    assert "Which strategy wins?" in page
    assert "How sure are we of the winner?" in page
    assert "Which assumption moves the result most?" in page
    assert "Where does the winner flip?" in page
    assert "At what value do two strategies tie?" in page
    for kind in ("compare", "monte-carlo", "sensitivity-oneway", "winner-map", "break-even"):
        assert f'name="kind" value="{kind}"' in page


def test_launch_form_explains_advanced_analysis_fields(client: TestClient) -> None:
    # Explanations sit with the fields they explain (proximity), not in a
    # separate accordion.
    page = client.get("/").text
    flat = " ".join(page.split())
    assert '<details class="analysis-help">' not in page
    assert 'class="field-hint"' in page
    assert "repeated simulations using different random seeds." in flat
    assert "how many values are tested across each range." in flat
    assert "Choose at least one assumption; use Select all only for an exhaustive sweep." in flat
    assert "assumptions varied together" in flat
    assert "grid size; 5 means 5 × 5 = 25 comparisons." in flat
    assert "net annual benefits are equal" in flat
    assert "Baseline has no mitigation" in flat
    assert "Reactive detects then cleans" in flat
    assert "Coating uses coating-based mitigation" in flat


def test_completed_job_moves_out_of_run_sessions(client: TestClient, comparison_run: Path) -> None:
    job = dashboard_app.jobs.submit("compare", "completed.yaml", lambda _job: comparison_run)
    deadline = time.time() + 10
    while job.status != "done" and time.time() < deadline:
        time.sleep(0.01)
    assert job.status == "done"

    try:
        page = client.get("/").text
        # Completed jobs leave the live-session strip, but remain in the
        # embedded persisted history that powers launch-time expectations.
        assert f'data-job="{job.job_id}"' not in page
        assert job.job_id in page
        assert comparison_run.name in page
    finally:
        dashboard_app.jobs.delete(job.job_id)


def test_parameter_catalog_uses_registry_relative_to_custom_config_dir(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "deployment" / "configs"
    registry_dir = config_dir / "registries"
    registry_dir.mkdir(parents=True)
    registry_path = registry_dir / "custom.yaml"
    registry_path.write_text(
        (Path("data/calibration/parameter_registry.yaml")).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    payload = fixture_config().model_dump(mode="json")
    payload["calibration"]["parameter_registry_path"] = "registries/custom.yaml"
    config_path = config_dir / "custom.yaml"
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    catalog = dashboard_app._parameter_catalog(config_path)

    assert catalog
    assert dashboard_app._registry_path(config_path) == registry_path
    assert any(item["name"] == "economics.electricity_tariff_sar_per_kwh" for item in catalog)
    monkeypatch.setattr(dashboard_app, "_CONFIGS_DIR", config_dir)
    response = client.get("/api/configs/custom.yaml/parameters")
    assert response.status_code == 200
    assert response.json() == catalog


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
        assert "Total net annual benefit" in page
        assert "Margin over runner-up" in page
        assert "734,918" in page  # stored value, formatted for reading
    finally:
        _delete_run(client, run_dir)


def test_comparison_page_validation_banner_is_optional_for_old_runs(
    client: TestClient,
) -> None:
    current = Path("outputs") / "test-dashboard-compare-all-scenarios-validation-current"
    old = Path("outputs") / "test-dashboard-compare-all-scenarios-validation-old"
    current.mkdir(parents=True, exist_ok=True)
    old.mkdir(parents=True, exist_ok=True)
    validation_status = {
        "absolute_outputs_field_validated": False,
        "parameter_counts_by_status": {"provisional": 2, "validated": 1},
        "parameter_counts_by_evidence_type": {"assumed": 1, "quoted": 2},
        "lowest_confidence": "low",
        "key_uncertain_parameters": [
            {
                "name": "economics.test_cost",
                "central_value": 10.0,
                "low_value": 2.0,
                "high_value": 30.0,
                "confidence": "low",
                "status": "provisional",
            }
        ],
        "disclaimer": (
            "Internally verified simulation calibrated to literature and provisional "
            "assumptions; absolute energy, cost, and ROI outputs have not been validated "
            "against measured production data from an operating site."
        ),
    }
    (current / "recommendation.json").write_text(
        json.dumps({"validation_status": validation_status}), encoding="utf-8"
    )
    (old / "recommendation.json").write_text(json.dumps({"valid": False}), encoding="utf-8")
    try:
        # Evidence quality now lives in the unified certification block next
        # to the title block, not a separate banner.
        current_page = client.get(f"/run/{current.name}")
        assert current_page.status_code == 200
        assert 'class="certification"' in current_page.text
        assert "Internally verified simulation calibrated" in current_page.text
        assert "economics.test_cost" in current_page.text
        assert "Most uncertain parameters" in current_page.text

        old_page = client.get(f"/run/{old.name}")
        assert old_page.status_code == 200
        assert "Internally verified simulation calibrated" not in old_page.text
        assert "Most uncertain parameters" not in old_page.text
    finally:
        _delete_run(client, current)
        _delete_run(client, old)


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


def test_engineering_document_fingerprint_and_audit_mode_render(
    client: TestClient, comparison_run: Path
) -> None:
    page = client.get(f"/run/{comparison_run.name}").text
    assert 'class="engineering-title-block"' in page
    assert "Engineering run record" in page
    assert "سجل التشغيل الهندسي" in page
    assert "1 OF 1" not in page and "١ من ١" not in page
    assert "Package" in page and "files ·" in page
    assert "fingerprint-medium" in page
    assert "fingerprint-full" in page
    assert 'class="dust-calendar"' in page
    assert 'id="audit-toggle"' in page
    assert "data-audit-source=" in page

    fingerprint = artifacts_module.run_fingerprint(comparison_run)
    assert fingerprint is not None
    assert len(fingerprint["dates"]) == 2
    assert len(fingerprint["ghi"]) == len(fingerprint["cleanliness"])


def test_home_is_configuration_cockpit_and_run_gallery(
    client: TestClient, comparison_run: Path
) -> None:
    page = client.get("/").text
    assert 'class="config-cockpit"' in page
    assert "Site locator" in page
    assert "Weather readiness" in page
    assert "Simulation plan · Form SC-01" in page
    assert 'class="run-gallery"' in page
    assert "fingerprint-tiny" in page
    assert "data-fingerprint-url=" in page
    assert 'id="select-all-runs"' in page
    assert 'id="run-archive-loader"' in page
    assert "runs-pagination" not in page
    assert "Daylight" in page
    assert page.count('class="run-card"') == min(
        len(artifacts_module.list_runs(Path("outputs"))), 24
    )

    first_batch = client.get("/api/run-pages/1")
    assert first_batch.status_code == 200
    assert 'class="run-card"' in first_batch.text
    assert int(first_batch.headers["x-run-total-pages"]) >= 1

    fingerprint = client.get(f"/api/runs/{comparison_run.name}/fingerprint")
    assert fingerprint.status_code == 200
    assert fingerprint.headers["cache-control"] == "private, max-age=300"
    assert fingerprint.json()["dates"]


def test_chart_event_payload_omits_redundant_daily_contamination(
    comparison_run: Path,
) -> None:
    markers = dashboard_app._chart_event_markers(comparison_run)
    assert all(marker["category"] != "contamination" for marker in markers)


def test_failed_check_is_quoted_verbatim_in_finding(client: TestClient) -> None:
    run_dir = Path("outputs") / "test-dashboard-compare-all-scenarios-failed-finding"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "reconciliation_report.json").write_text(
        json.dumps(
            {
                "passed": False,
                "checks": [
                    {
                        "name": "reactive_cost_crew_hours_reconciles",
                        "passed": False,
                        "message": "Crew cost differs from 412.5 × 35 SAR/hour.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    try:
        page = client.get(f"/run/{run_dir.name}").text
        assert "Run not certified" in page
        assert "Crew cost differs from 412.5 × 35 SAR/hour." in page
        assert "reactive_cost_crew_hours_reconciles" in page
    finally:
        _delete_run(client, run_dir)


def test_compare_runs_is_diff_with_collapsed_identical_values(
    client: TestClient, comparison_run: Path
) -> None:
    response = client.get(
        "/compare-runs", params={"a": comparison_run.name, "b": comparison_run.name + "-missing"}
    )
    assert response.status_code == 404

    other = Path("outputs") / "test-dashboard-diff-other-compare-all-scenarios"
    other.mkdir(parents=True, exist_ok=True)
    shutil.copy2(comparison_run / "config_resolved.yaml", other / "config_resolved.yaml")
    shutil.copy2(
        comparison_run / "scenario_annual_summary.csv", other / "scenario_annual_summary.csv"
    )
    try:
        page = client.get("/compare-runs", params={"a": comparison_run.name, "b": other.name}).text
        assert "Changed assumptions" in page
        assert "identical fields collapsed" in page
        assert "Annual KPIs · changed values" in page
        assert "identical KPI values collapsed" in page
        # Identical resolved configs = same study, so before/after framing applies.
        assert "A · BEFORE" in page
    finally:
        _delete_run(client, other)


def test_fonts_themes_and_drawing_hatching_are_self_contained(client: TestClient) -> None:
    css = client.get("/static/dashboard.css").text
    assert 'font-family: "IBM Plex Sans"' in css
    assert "IBMPlexSansArabic-Regular.woff2" in css
    assert "repeating-linear-gradient(135deg" in css
    assert "Night shift" in client.get("/static/dashboard.js").text
    assert client.get("/static/fonts/IBMPlexSans-Regular.woff2").status_code == 200


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
    # Cumulative gain is a metric view of the daily explorer, fed by the same
    # stored column.
    assert 'data-energy-metric="cumgain"' in page
    assert "dailyCumGain:" in page


def test_humidity_chart_is_optional_for_old_and_new_comparison_runs(client: TestClient) -> None:
    fresh = Path("outputs") / "test-dashboard-humidity-compare-all-scenarios-new"
    old = Path("outputs") / "test-dashboard-humidity-compare-all-scenarios-old"
    for run_dir, header in (
        (
            fresh,
            "date,scenario_name,actual_energy_kwh,extension_mean_relative_humidity_pct\n",
        ),
        (old, "date,scenario_name,actual_energy_kwh\n"),
    ):
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "scenario_daily_summary.csv").write_text(
            header + "2025-01-01,baseline,100,42.5\n",
            encoding="utf-8",
        )
    try:
        new_page = client.get(f"/run/{fresh.name}")
        assert new_page.status_code == 200
        assert 'id="daily-humidity-chart"' in new_page.text
        assert "dailyHumidity:" in new_page.text
        assert "daily mean %" in new_page.text
        assert 'id="daily-dew-chart"' not in new_page.text
        old_page = client.get(f"/run/{old.name}")
        assert old_page.status_code == 200
        assert 'id="daily-humidity-chart"' not in old_page.text
    finally:
        for run_dir in (fresh, old):
            client.delete(f"/api/runs/{run_dir.name}")


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


def test_registry_idle_check_and_enqueue_are_atomic() -> None:
    registry = JobRegistry()
    submit_together = threading.Barrier(2)
    release = threading.Event()
    submitted: list[Job] = []
    rejected: list[ActiveJobError] = []

    def work(job: Job) -> Path:
        release.wait(timeout=10)
        return Path("outputs/fake")

    def launch() -> None:
        submit_together.wait(timeout=10)
        try:
            submitted.append(registry.submit("compare", "x.yaml", work, require_idle=True))
        except ActiveJobError as exc:
            rejected.append(exc)

    threads = [threading.Thread(target=launch) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(submitted) == 1
    assert len(rejected) == 1
    assert rejected[0].job is submitted[0]
    release.set()
    deadline = time.time() + 10
    while submitted[0].status != "done" and time.time() < deadline:
        time.sleep(0.01)
    assert submitted[0].status == "done"


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


# --------------------------------------------------------------------------
# Redesign: unified run identity, studies, certification, decision aids
# --------------------------------------------------------------------------


def test_home_unifies_sessions_into_run_cards(client: TestClient) -> None:
    """The sessions table is gone: a launched run is one card in one place."""

    def failing_work(job: object) -> Path:
        raise RuntimeError("kaboom for the card")

    job = dashboard_app.jobs.submit("compare", "boom.yaml", failing_work)
    deadline = time.time() + 10
    while job.status != "failed" and time.time() < deadline:
        time.sleep(0.01)
    assert job.status == "failed"

    try:
        page = client.get("/").text
        assert 'id="jobs-table"' not in page
        assert 'id="job-cards"' in page
        assert "job-card job-card-failed" in page
        assert "kaboom for the card" in page
        assert "Dismiss" in page
    finally:
        dashboard_app.jobs.delete(job.job_id)


def test_runs_archive_is_grouped_by_study(client: TestClient, comparison_run: Path) -> None:
    """Cards carry their study identity and render under study headers."""
    page = client.get("/").text
    assert 'class="study-header"' in page
    assert "data-study=" in page
    # The fixture run's study fields come from its own config_resolved.yaml.
    study = dashboard_app._run_study(comparison_run)
    assert study is not None
    assert study["label"] in page


def test_related_runs_strip_links_same_study_siblings(
    client: TestClient, comparison_run: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = tmp_path / "outputs"
    run_a = outputs / "study-a-compare-all-scenarios-20260717T000000Z-aaa111"
    run_b = outputs / "study-b-compare-all-scenarios-20260717T010000Z-bbb222"
    shutil.copytree(comparison_run, run_a)
    shutil.copytree(comparison_run, run_b)
    monkeypatch.setattr(dashboard_app, "_OUTPUTS_DIR", outputs)

    page = client.get(f"/run/{run_a.name}").text
    assert 'class="related-runs"' in page
    assert run_b.name in page  # same config_resolved.yaml = same study
    assert "Compare against" in page
    assert f'name="a" value="{run_a.name}"' in page


def test_certification_groups_repeated_parameter_warnings() -> None:
    aggregated = dashboard_app._aggregate_warnings(
        [
            {
                "message": "economics.a has status blocked; allow_blocked_with_warnings "
                "permits use for research/sensitivity only."
            },
            {
                "message": "economics.b has status blocked; allow_blocked_with_warnings "
                "permits use for research/sensitivity only."
            },
            {
                "message": "economics.c has status provisional; allow_blocked_with_warnings "
                "permits use for research/sensitivity only."
            },
            "Coating cost assumptions are provisional, not validated field costs.",
        ]
    )
    assert aggregated["total"] == 4
    assert "3 parameters" in aggregated["summary"]
    assert "2 blocked" in aggregated["summary"] and "1 provisional" in aggregated["summary"]
    statuses = {group["status"]: group["parameters"] for group in aggregated["groups"]}
    assert statuses["blocked"] == ["economics.a", "economics.b"]
    assert statuses["provisional"] == ["economics.c"]
    assert aggregated["other"] == [
        "Coating cost assumptions are provisional, not validated field costs."
    ]


def test_headline_relabels_when_baseline_wins() -> None:
    """Baseline winning means the stored margin IS the mitigation shortfall,
    and 'energy gain vs baseline = 0' is a degenerate slot, not a fact."""
    cards = dashboard_app._headline_cards(
        {
            "valid": True,
            "winner": "baseline",
            "decisive_margin_sar": 101046.0,
            "kpi_snapshot": {
                "baseline": {
                    "net_annual_benefit_sar": 1045929.0,
                    "energy_gain_vs_baseline_kwh": 0.0,
                }
            },
        }
    )
    labels = [card["label"] for card in cards]
    assert "Best mitigation falls short by" in labels
    assert "Margin over runner-up" not in labels
    assert "Energy gain vs baseline" not in labels

    mitigation_cards = dashboard_app._headline_cards(
        {
            "valid": True,
            "winner": "coating",
            "decisive_margin_sar": 500.0,
            "kpi_snapshot": {"coating": {"energy_gain_vs_baseline_kwh": 42.0}},
        }
    )
    mitigation_labels = [card["label"] for card in mitigation_cards]
    assert "Margin over runner-up" in mitigation_labels
    assert "Energy gain vs baseline" in mitigation_labels


def test_command_index_lists_runs_and_configs(client: TestClient, comparison_run: Path) -> None:
    response = client.get("/api/command-index")
    assert response.status_code == 200
    payload = response.json()
    assert DEFAULT_CONFIG_NAME in payload["configs"]
    run_ids = [run["run_id"] for run in payload["runs"]]
    assert comparison_run.name in run_ids


def test_command_palette_and_audit_banner_present(client: TestClient) -> None:
    page = client.get("/").text
    assert 'id="command-palette"' in page
    assert 'id="palette-input"' in page
    assert 'id="audit-banner"' in page
    script = client.get("/static/dashboard.js").text
    assert "openPalette" in script
    assert "/api/command-index" in script


def test_apply_location_can_rewrite_the_period(client: TestClient) -> None:
    content = dashboard_app._RIYADH_DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")

    response = client.post(
        f"/api/configs/{DEFAULT_CONFIG_NAME}/apply-location",
        json={
            "content": content,
            "latitude": 24.7136,
            "longitude": 46.6753,
            "start_date": "2025-03-01",
            "end_date": "2025-03-31",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["valid"] is True
    assert result["start"] == "2025-03-01T00:00:00+03:00"
    assert result["end"] == "2025-03-31T23:00:00+03:00"
    updated = SolarCleanConfig.model_validate(yaml.safe_load(result["content"]))
    assert updated.simulation.start.date().isoformat() == "2025-03-01"
    assert updated.simulation.end.date().isoformat() == "2025-03-31"


# --------------------------------------------------------------------------
# Stored-instrument expansion and audit workflow
# --------------------------------------------------------------------------


def test_detection_coating_and_explorer_instruments_render_stored_series(
    client: TestClient, comparison_run: Path
) -> None:
    page = client.get(f"/run/{comparison_run.name}").text

    assert 'id="detection-performance"' in page
    assert "Detection performance" in page
    assert "Whole-farm surveys" in page
    assert "daily TP/FP/FN fields" in page
    assert 'id="coating-service-life"' in page
    assert "Coating service life" in page
    assert "Stored energy-effect decomposition" in page
    for canvas_id in (
        "detection-energy-chart",
        "detection-queue-chart",
        "coating-effectiveness-chart",
        "coating-effects-chart",
        "coating-dew-margin-chart",
    ):
        marker = f'id="{canvas_id}"'
        start = page.index(marker)
        assert "data-audit-source=" in page[start : start + 650]

    for metric in ("bird-loss", "collected-water", "queue"):
        assert f'data-energy-metric="{metric}"' in page
        assert f'data-selected-field="{metric}"' in page
    assert "dailyBirdLoss:" in page
    assert "dailyCollectedWater:" in page
    assert "dailyQueue:" in page
    assert 'id="hourly-detail-chart"' in page
    assert "Stored hourly weather + clean reference" in page
    assert "does not infer hourly scenario energy" in page

    assert 'id="annual-chart"' not in page
    assert "annualCostBars" not in page
    assert 'id="artifact-preview-drawer"' in page
    assert "data-artifact-preview" in page


def test_interactive_chart_frames_use_one_stable_size_owner(client: TestClient) -> None:
    script = client.get("/static/dashboard.js").text
    stylesheet = client.get("/static/dashboard.css").text

    # Fixed-height instrument frames must opt out of Chart.js's default
    # aspect-ratio sizing; mixing both systems stretches the backing bitmap
    # and can trigger resize-observer repaint loops.
    assert "function stabilizeFixedHeightChart(options)" in script
    assert "options.maintainAspectRatio = false" in script
    assert "var options = stabilizeFixedHeightChart(baseOptions(yLabel))" in script
    assert 'stabilizeFixedHeightChart(baseOptions("Effectiveness"))' in script

    # Synchronized explorer cursors render at most once per browser frame.
    assert "window.requestAnimationFrame(function ()" in script
    assert "var explorerRenderFrame = null" in script

    # Export actions are siblings of the fixed frame, never children that
    # increase the plot area's scroll height.
    assert '".energy-main-chart, .record-chart-frame, .hourly-chart-frame"' in script
    assert ".record-chart > .chart-download" in stylesheet
    assert ".hourly-detail > .chart-download" in stylesheet
    assert "overflow: hidden;" in stylesheet


def test_detection_and_coating_contexts_pass_through_stored_columns(
    comparison_run: Path,
) -> None:
    detection = dashboard_app._detection_performance(comparison_run)
    assert detection is not None
    daily = detection["daily"]
    assert isinstance(daily, dict)
    expected_missed = artifacts_module.daily_series(
        comparison_run,
        "extension_missed_contamination_estimated_energy_impact_kwh",
    )
    assert expected_missed is not None
    assert daily["dates"] == expected_missed["dates"]
    assert daily["missed_kwh"] == expected_missed["series"]["reactive"]
    expected_cancellations = artifacts_module.daily_series(
        comparison_run, "extension_weather_cancelled_flight"
    )
    assert expected_cancellations is not None
    assert daily["weather_cancelled"] == expected_cancellations["series"]["reactive"]
    assert set(daily["weather_cancelled"]) <= {0.0, 1.0}
    # Annual facts come from explicit annual columns; no annual confusion
    # total is synthesized from daily TP/FP/FN/TN fields.
    assert set(detection["annual_rows"][0]) == {
        "scenario_id",
        "survey_count",
        "dispatch_count",
        "panels_cleaned",
        "audit_source",
    }

    coating = dashboard_app._coating_service_life(comparison_run)
    assert coating is not None
    expected_optical = artifacts_module.daily_series(comparison_run, "extension_optical_effect_kwh")
    assert expected_optical is not None
    assert coating["dates"] == expected_optical["dates"]
    assert coating["optical_effect_kwh"] == expected_optical["series"]["coating"]


def test_hourly_day_endpoint_returns_only_stored_weather_and_clean_reference(
    client: TestClient, comparison_run: Path
) -> None:
    weather_header, weather_rows = artifacts_module.read_csv_rows(
        comparison_run / "weather_hourly.csv"
    )
    day = weather_rows[0][weather_header.index("timestamp")][:10]

    response = client.get(f"/api/runs/{comparison_run.name}/hourly/{day}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == day
    assert len(payload["timestamps"]) == 24
    assert payload["ghi_w_m2"][0] == pytest.approx(
        float(weather_rows[0][weather_header.index("ghi_w_m2")])
    )
    assert set(payload) == {
        "date",
        "timestamps",
        "ghi_w_m2",
        "temp_air_c",
        "wind_speed_m_s",
        "relative_humidity_pct",
        "clean_ac_energy_kwh",
        "sources",
    }
    assert client.get(f"/api/runs/{comparison_run.name}/hourly/1999-01-01").status_code == 404


def test_artifact_preview_payloads_are_bounded_and_guarded(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = tmp_path / "outputs"
    run_dir = outputs / "preview-compare-all-scenarios-20260717T000000Z-a1"
    run_dir.mkdir(parents=True)
    (run_dir / "rows.csv").write_text(
        "row,value\n" + "".join(f"{index},{index * 2}\n" for index in range(60)),
        encoding="utf-8",
    )
    (run_dir / "record.json").write_text(
        json.dumps({"winner": "coating", "margin": 12.5}), encoding="utf-8"
    )
    (run_dir / "config.yaml").write_text("site:\n  name: Preview\n", encoding="utf-8")
    (run_dir / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(dashboard_app, "_OUTPUTS_DIR", outputs)

    csv_payload = client.get(f"/api/runs/{run_dir.name}/artifact-preview/rows.csv").json()
    assert csv_payload["kind"] == "csv"
    assert len(csv_payload["rows"]) == 50
    assert csv_payload["total_rows"] == 60
    assert csv_payload["truncated"] is True

    json_payload = client.get(f"/api/runs/{run_dir.name}/artifact-preview/record.json").json()
    assert json_payload["kind"] == "json"
    assert '"winner": "coating"' in json_payload["content"]
    yaml_payload = client.get(f"/api/runs/{run_dir.name}/artifact-preview/config.yaml").json()
    assert yaml_payload["kind"] == "text"
    assert "name: Preview" in yaml_payload["content"]
    png_payload = client.get(f"/api/runs/{run_dir.name}/artifact-preview/plot.png").json()
    assert png_payload["kind"] == "png"
    assert png_payload["url"].endswith("/artifact/plot.png")

    escaped = client.get(f"/api/runs/{run_dir.name}/artifact-preview/..%2Foutside.txt")
    assert escaped.status_code in (404, 422)


def test_study_dossier_and_calibration_priority_join_latest_stored_evidence(
    client: TestClient,
    comparison_run: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    comparison = outputs / "study-compare-all-scenarios-20260717T000000Z-a1"
    oneway = outputs / "study-sensitivity-oneway-20260717T010000Z-b2"
    shutil.copytree(comparison_run, comparison)
    oneway.mkdir(parents=True)
    shutil.copy2(comparison / "config_resolved.yaml", oneway / "config_resolved.yaml")

    recommendation = json.loads((comparison / "recommendation.json").read_text(encoding="utf-8"))
    recommendation["validation_status"] = {
        "key_uncertain_parameters": [
            {
                "name": "test.low_swing",
                "low_value": 1,
                "central_value": 2,
                "high_value": 3,
                "status": "provisional",
                "confidence": "low",
            },
            {
                "name": "test.high_swing",
                "low_value": 10,
                "central_value": 20,
                "high_value": 30,
                "status": "blocked",
                "confidence": "low",
            },
        ]
    }
    (comparison / "recommendation.json").write_text(json.dumps(recommendation), encoding="utf-8")
    (oneway / "sensitivity_oneway_summary.json").write_text(
        json.dumps(
            {
                "parameter_results": [
                    {
                        "parameter_name": "test.low_swing",
                        "swing_sar": {"baseline": 10, "reactive": 20, "coating": 15},
                        "winner_changed": False,
                    },
                    {
                        "parameter_name": "test.high_swing",
                        "swing_sar": {"baseline": 90, "reactive": 120, "coating": 80},
                        "winner_changed": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_app, "_OUTPUTS_DIR", outputs)

    comparison_page = client.get(f"/run/{comparison.name}").text
    assert "Where to spend calibration effort" in comparison_page
    priority_section = comparison_page[
        comparison_page.index('id="calibration-priority"') : comparison_page.index(
            'class="run-head run-command-bar"'
        )
    ]
    assert priority_section.index("test.high_swing") < priority_section.index("test.low_swing")
    assert oneway.name in comparison_page
    assert (
        "data-audit-source="
        in priority_section[
            priority_section.index("test.high_swing") - 400 : priority_section.index(
                "test.high_swing"
            )
        ]
    )

    study = dashboard_app._run_study(comparison)
    assert study is not None
    dossier = client.get(f"/study/{quote(study['key'], safe='')}")
    assert dossier.status_code == 200
    assert "Study dossier" in dossier.text
    assert comparison.name in dossier.text
    assert oneway.name in dossier.text
    assert "test.high_swing" in dossier.text
    assert "No Monte Carlo run yet" in dossier.text
    assert "No break-even run yet" in dossier.text
    assert "No winner-map run yet" in dossier.text


def test_launch_history_and_decluttered_static_copy(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history = tmp_path / "jobs.json"
    history.write_text(
        json.dumps(
            {
                "version": 1,
                "jobs": [
                    {
                        "job_id": "historic-job",
                        "kind": "compare",
                        "config_name": DEFAULT_CONFIG_NAME,
                        "status": "done",
                        "created_at": "2026-07-17T10:00:00+00:00",
                        "finished_at": "2026-07-17T10:04:12+00:00",
                        "elapsed_seconds": 252,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_app, "jobs", JobRegistry(history_path=history))

    index_page = client.get("/").text
    assert "window.solarcleanJobHistory" in index_page
    assert '"elapsed_seconds": 252' in index_page
    assert 'id="launch-history-expectation"' in index_page
    assert "Runs &amp; analysis" not in index_page

    config_page = client.get(f"/config/{DEFAULT_CONFIG_NAME}").text
    assert "What the location changes" in config_page
    assert "What stays fixed" in config_page
    assert 'class="provider-note"' in config_page

    script = client.get("/static/dashboard.js").text
    assert "matchingFinishedJob" in script
    assert "formatSeconds(record.elapsed_seconds)" in script
