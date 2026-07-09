"""T8 dashboard tests.

The important one is test_displayed_ranking_matches_artifact: T8's completion
criteria require that what the dashboard shows reconciles with what the backend
wrote, so we run one real offline comparison and check the page against the
JSON artifact it claims to display.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="dashboard extra not installed")
from fastapi.testclient import TestClient  # noqa: E402

from solarclean.application.comparison import CompareAllScenarios  # noqa: E402
from solarclean.config.loader import load_config  # noqa: E402
from solarclean.dashboard.app import app  # noqa: E402

OFFLINE_CONFIG = Path("configs/offline_fixture.yaml")


@pytest.fixture(scope="module")
def comparison_run() -> Path:
    result = CompareAllScenarios(load_config(OFFLINE_CONFIG)).run()
    return result.output_directory


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_index_lists_configs_and_runs(client: TestClient, comparison_run: Path) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "offline_fixture.yaml" in response.text
    assert comparison_run.name in response.text


def test_displayed_ranking_matches_artifact(client: TestClient, comparison_run: Path) -> None:
    with (comparison_run / "scenario_ranking.json").open(encoding="utf-8") as handle:
        ranking = json.load(handle)["ranking"]
    page = client.get(f"/run/{comparison_run.name}").text
    for entry in ranking:
        assert entry["scenario_id"] in page
        # Net annual benefit is rendered with %.0f on the ranking table.
        assert f"{entry['net_annual_benefit_sar']:.0f}" in page


def test_reconciliation_chips_rendered(client: TestClient, comparison_run: Path) -> None:
    page = client.get(f"/run/{comparison_run.name}").text
    assert "same_weather_checksum" in page
    assert "same_event_tape_checksum" in page


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


def test_config_validation_paths(client: TestClient) -> None:
    bad_yaml = client.post(
        "/api/configs/offline_fixture.yaml/validate", json={"content": "not: [valid"}
    )
    assert bad_yaml.json()["valid"] is False

    bad_schema = client.post(
        "/api/configs/offline_fixture.yaml/validate", json={"content": "site: {}"}
    )
    assert bad_schema.json()["valid"] is False

    good = client.post(
        "/api/configs/offline_fixture.yaml/validate",
        json={"content": OFFLINE_CONFIG.read_text(encoding="utf-8")},
    )
    assert good.json()["valid"] is True


def test_launch_rejects_unknown_kind(client: TestClient) -> None:
    response = client.post(
        "/api/runs", json={"kind": "warp-drive", "config_name": "offline_fixture.yaml"}
    )
    assert response.status_code == 400
