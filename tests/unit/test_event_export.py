from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pandas as pd
from tests.config_factory import fixture_config

from solarclean.domain.contamination.soiling import SimulationEvent
from solarclean.domain.scenario.contracts import (
    AnnualScenarioResult,
    DailyScenarioResult,
    DomainEvent,
)
from solarclean.domain.simulation.baseline import BaselineSimulationResult
from solarclean.infrastructure.persistence.outputs import OutputWriter


def _writer(tmp_path: Path) -> OutputWriter:
    config = fixture_config(overrides={"output": {"base_directory": tmp_path}})
    return OutputWriter(config)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_scenario_event_csv_exports_json_metadata_integer_cohorts_and_order(
    tmp_path: Path,
) -> None:
    first_day = date(2025, 1, 1)
    second_day = date(2025, 1, 2)
    condensation = DomainEvent(
        date=first_day,
        event_type="coating_condensation",
        magnitude=12.5,
        description="Radiative-cooling coating condensed water.",
        scenario_name="event_export_test",
        metadata={"potentially_collectable_liters": 4.25},
    )
    cleaning = DomainEvent(
        date=second_day,
        event_type="reactive_cleaning_action",
        magnitude=1.0,
        description="Targeted cohort cleaning dispatched from CV inspection.",
        scenario_name="event_export_test",
        cohort_id=28,
        metadata={"cause": "inspection", "confidence": 0.95},
    )
    inspection = DomainEvent(
        date=second_day,
        event_type="reactive_inspection",
        magnitude=1.0,
        description="Drone CV inspection of cohort.",
        scenario_name="event_export_test",
        cohort_id=28,
        metadata={"detected_dirty": True, "threshold": 0.8},
    )
    result = AnnualScenarioResult(
        scenario_name="event_export_test",
        daily_results=(
            DailyScenarioResult(
                date=second_day,
                scenario_name="event_export_test",
                clean_energy_kwh=10.0,
                actual_energy_kwh=9.0,
                events=(cleaning, inspection),
            ),
            DailyScenarioResult(
                date=first_day,
                scenario_name="event_export_test",
                clean_energy_kwh=10.0,
                actual_energy_kwh=9.0,
                events=(condensation,),
            ),
        ),
    )

    _writer(tmp_path).write_scenario_result(tmp_path, result)

    path = tmp_path / "scenario_events.csv"
    raw_csv = path.read_text(encoding="utf-8")
    rows = _read_rows(path)

    assert "28.0" not in raw_csv
    assert [row["date"] for row in rows] == ["2025-01-01", "2025-01-02", "2025-01-02"]
    assert [(row["date"], int(row["event_sequence"])) for row in rows] == sorted(
        (row["date"], int(row["event_sequence"])) for row in rows
    )
    assert rows[0]["cohort_id"] == ""
    assert rows[1]["cohort_id"] == "28"
    assert rows[2]["cohort_id"] == "28"
    assert all(json.loads(row["metadata"]) is not None for row in rows)
    assert rows[0]["event_phase"] == "nighttime_condensation"
    assert rows[0]["effective_for_energy_date"] == "2025-01-02"

    inspection_row = next(row for row in rows if row["event_type"] == "reactive_inspection")
    cleaning_row = next(row for row in rows if row["event_type"] == "reactive_cleaning_action")
    assert int(inspection_row["event_sequence"]) < int(cleaning_row["event_sequence"])


def test_baseline_event_csv_uses_same_export_hygiene(tmp_path: Path) -> None:
    day = date(2025, 1, 1)
    baseline = BaselineSimulationResult(
        daily=pd.DataFrame(
            {"clean_energy_kwh": [10.0], "actual_energy_kwh": [9.0]},
            index=[day.isoformat()],
        ),
        events=[
            SimulationEvent(
                date=day,
                event_type="bird_dropping_event",
                magnitude=0.1,
                description="Sparse cohort-level bird-dropping event.",
                cohort_id=28,
            ),
            SimulationEvent(
                date=day,
                event_type="dust_accumulation",
                magnitude=0.01,
                description="Daily provisional dust accumulation applied.",
            ),
        ],
        annual_clean_energy_kwh=10.0,
        annual_actual_energy_kwh=9.0,
        annual_soiling_loss_kwh=1.0,
        annual_soiling_loss_percent=10.0,
    )

    writer = _writer(tmp_path)
    writer.write_baseline(tmp_path, baseline, writer.config)

    path = tmp_path / "events.csv"
    raw_csv = path.read_text(encoding="utf-8")
    rows = _read_rows(path)

    assert "28.0" not in raw_csv
    assert [row["event_type"] for row in rows] == ["dust_accumulation", "bird_dropping_event"]
    assert [row["event_sequence"] for row in rows] == ["1", "2"]
    assert rows[0]["cohort_id"] == ""
    assert rows[1]["cohort_id"] == "28"
    assert rows[0]["metadata"] == "{}"
    assert all(json.loads(row["metadata"]) == {} for row in rows)


def test_output_include_cohort_daily_details_flag_is_honored(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    config = writer.config.model_copy(
        update={
            "output": writer.config.output.model_copy(
                update={"include_cohort_daily_details": False}
            )
        }
    )
    baseline = BaselineSimulationResult(
        daily=pd.DataFrame(
            {"clean_energy_kwh": [10.0], "actual_energy_kwh": [9.0]},
            index=["2025-01-01"],
        ),
        events=[],
        annual_clean_energy_kwh=10.0,
        annual_actual_energy_kwh=9.0,
        annual_soiling_loss_kwh=1.0,
        annual_soiling_loss_percent=10.0,
        cohort_daily=pd.DataFrame({"cohort_id": [0]}),
    )

    OutputWriter(config).write_baseline(tmp_path, baseline, config)

    assert not (tmp_path / "cohort_daily_results.csv").exists()
