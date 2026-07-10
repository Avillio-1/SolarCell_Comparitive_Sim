from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from tests.config_factory import fixture_config

from solarclean.application.use_cases import RunReactiveSimulation
from solarclean.domain.reactive_cv.metrics import SEVERITY_BUCKETS


def _diagnostic_config(tmp_path: Path):
    return fixture_config(
        overrides={
            "output": {"base_directory": tmp_path},
            "soiling": {
                "base_daily_soiling_loss_fraction": 0.10,
                "dust_event_probability": 0.0,
                "stochastic_std_fraction": 0.0,
                "minimum_soiling_ratio": 0.01,
            },
            "bird_droppings": {"event_probability_per_cohort_day": 0.0},
            "reactive_cv": {
                "inspection": {
                    "interval_days": 1,
                    "first_inspection_day_index": 0,
                    "dirty_soiling_ratio_threshold": 0.99,
                },
                "drone": {
                    "cohorts_per_flight": 2,
                    "flights_per_day": 1,
                    "max_wind_speed_m_s": 99.0,
                    "max_precipitation_mm": 999.0,
                },
                "observer": {
                    "recall_fraction": 1.0,
                    "false_positive_rate": 0.0,
                    "missed_image_fraction": 0.0,
                    "base_confidence": 1.0,
                    "confidence_std_fraction": 0.0,
                    "severity_error_std_fraction": 0.0,
                },
                "dispatch": {
                    "estimated_loss_threshold_fraction": 0.0,
                    "confidence_threshold": 0.0,
                    "max_queue_age_days": 14,
                },
                "crew": {
                    "daily_capacity_cohorts": 1,
                    "setup_minutes_per_cohort": 10.0,
                    "cleaning_minutes_per_cohort": 20.0,
                    "water_liters_per_cohort": 123.0,
                    "dust_removal_efficiency": 1.0,
                    "bird_removal_efficiency": 1.0,
                },
            },
        },
    )


def _actionable_mismatch_config(tmp_path: Path):
    return fixture_config(
        overrides={
            "output": {"base_directory": tmp_path},
            "soiling": {
                "base_daily_soiling_loss_fraction": 0.07,
                "dust_event_probability": 0.0,
                "stochastic_std_fraction": 0.0,
                "minimum_soiling_ratio": 0.01,
            },
            "bird_droppings": {"event_probability_per_cohort_day": 0.0},
            "reactive_cv": {
                "inspection": {
                    "interval_days": 1,
                    "first_inspection_day_index": 0,
                    "dirty_soiling_ratio_threshold": 0.92,
                },
                "drone": {
                    "cohorts_per_flight": 1,
                    "flights_per_day": 1,
                    "max_wind_speed_m_s": 99.0,
                    "max_precipitation_mm": 999.0,
                },
                "observer": {
                    "recall_fraction": 1.0,
                    "false_positive_rate": 0.0,
                    "missed_image_fraction": 0.0,
                    "base_confidence": 1.0,
                    "confidence_std_fraction": 0.0,
                    "severity_error_std_fraction": 0.0,
                },
                "dispatch": {
                    "estimated_loss_threshold_fraction": 0.05,
                    "confidence_threshold": 0.0,
                    "max_queue_age_days": 14,
                },
                "crew": {
                    "daily_capacity_cohorts": 1,
                    "setup_minutes_per_cohort": 10.0,
                    "cleaning_minutes_per_cohort": 20.0,
                    "water_liters_per_cohort": 123.0,
                    "dust_removal_efficiency": 1.0,
                    "bird_removal_efficiency": 1.0,
                },
            },
        },
    )


def _event_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_reactive_annual_summary_includes_severity_weighted_diagnostics(
    tmp_path: Path,
) -> None:
    result = RunReactiveSimulation(_diagnostic_config(tmp_path)).run()
    summary = json.loads(
        (result.output_directory / "reactive_comparison_summary.json").read_text(encoding="utf-8")
    )

    detection = summary["detection_performance"]
    missed_counts = summary["missed_contamination_count_by_severity_bucket"]
    missed_energy = summary["missed_contamination_estimated_energy_impact_by_severity_bucket"]
    detected_energy = summary["detected_contamination_estimated_energy_impact_by_severity_bucket"]

    assert set(missed_counts) == set(SEVERITY_BUCKETS)
    assert set(missed_energy) == set(SEVERITY_BUCKETS)
    assert set(detected_energy) == set(SEVERITY_BUCKETS)
    assert sum(missed_counts.values()) == detection["system_missed_dirty_count"]
    assert detection["cv_observation_recall"] == detection["recall"]
    assert detection["cv_observation_precision"] == detection["precision"]
    assert detection["system_dirty_cohort_recall"] == detection["system_detection_recall"]
    assert "actionable_false_negative_count" in detection
    assert "actionable_missed_contamination_count" in detection
    assert summary["missed_contamination_estimated_energy_impact_kwh"] == pytest.approx(
        sum(missed_energy.values())
    )
    assert summary["detected_contamination_estimated_energy_impact_kwh"] == pytest.approx(
        sum(detected_energy.values())
    )
    assert summary["missed_contamination_estimated_energy_impact_kwh"] >= 0.0
    assert summary["detected_contamination_estimated_energy_impact_kwh"] >= 0.0
    assert summary["recovered_loss_estimated_kwh"] >= 0.0
    assert summary["avoided_loss_estimated_kwh"] == pytest.approx(
        summary["recovered_loss_estimated_kwh"]
    )


def test_reactive_event_metadata_links_inspection_dispatch_and_cleaning(
    tmp_path: Path,
) -> None:
    result = RunReactiveSimulation(_diagnostic_config(tmp_path)).run()
    rows = _event_rows(result.output_directory / "scenario_events.csv")
    metadata_by_type = [(row["event_type"], json.loads(row["metadata"])) for row in rows]

    inspection_metadata = [
        metadata for event_type, metadata in metadata_by_type if event_type == "reactive_inspection"
    ]
    dispatch_metadata = [
        metadata
        for event_type, metadata in metadata_by_type
        if event_type == "reactive_cleaning_dispatch"
    ]
    cleaning_metadata = [
        metadata
        for event_type, metadata in metadata_by_type
        if event_type == "reactive_cleaning_action"
    ]

    assert inspection_metadata
    assert dispatch_metadata
    assert cleaning_metadata
    assert all(isinstance(metadata, dict) for _, metadata in metadata_by_type)

    inspection_ids = {metadata["inspection_id"] for metadata in inspection_metadata}
    dispatch_ids = {metadata["dispatch_id"] for metadata in dispatch_metadata}
    first_inspection = inspection_metadata[0]
    controller_visible = first_inspection["controller_visible_decision_inputs"]
    assert "true_dirty" not in controller_visible
    assert "true_contamination_loss_fraction" not in controller_visible
    assert "audit" in first_inspection
    audit = first_inspection["audit"]
    assert "true_contaminated" in audit
    assert "true_actionable_dirty" in audit
    assert "true_dirty_threshold_fraction" in audit
    assert "true_dirty_threshold_kwh" in audit

    for metadata in cleaning_metadata:
        assert metadata["triggering_inspection_id"] in inspection_ids
        assert metadata["dispatch_id"] in dispatch_ids
        assert metadata["estimated_loss_kwh"] >= metadata["dispatch_threshold_kwh"]
        assert metadata["pre_clean_dust_state"] <= metadata["post_clean_dust_state"]
        assert "pre_clean_bird_state" in metadata
        assert "post_clean_bird_state" in metadata
        assert metadata["dust_removed"] >= 0.0
        assert metadata["bird_removed"] >= 0.0
        assert metadata["crew_minutes"] == pytest.approx(30.0)
        assert metadata["crew_hours"] == pytest.approx(0.5)
        assert metadata["water_liters"] == pytest.approx(123.0)
        assert "false_positive_cleaning" in metadata["audit"]


def test_true_dirty_audit_uses_actionable_threshold_for_missed_detection(
    tmp_path: Path,
) -> None:
    result = RunReactiveSimulation(_actionable_mismatch_config(tmp_path)).run()
    rows = _event_rows(result.output_directory / "scenario_events.csv")
    inspection_metadata = [
        json.loads(row["metadata"]) for row in rows if row["event_type"] == "reactive_inspection"
    ]
    missed_actionable = [
        metadata
        for metadata in inspection_metadata
        if (
            metadata["audit"]["true_contamination_loss_fraction"]
            > metadata["audit"]["true_dirty_threshold_fraction"]
            and not metadata["detected_dirty"]
        )
    ]

    assert missed_actionable
    metadata = missed_actionable[0]
    audit = metadata["audit"]
    controller_visible = metadata["controller_visible_decision_inputs"]

    assert audit["true_contaminated"] is True
    assert audit["true_actionable_dirty"] is True
    assert audit["true_dirty"] is True
    assert audit["true_observer_dirty"] is False
    assert audit["true_dirty_threshold_fraction"] == pytest.approx(0.05)
    assert audit["true_contamination_loss_fraction"] > audit["true_dirty_threshold_fraction"]
    assert audit["true_contamination_loss_kwh"] > audit["true_dirty_threshold_kwh"]
    assert "true_actionable_dirty" not in controller_visible
    assert "true_dirty_threshold_fraction" not in controller_visible

    summary = json.loads(
        (result.output_directory / "reactive_comparison_summary.json").read_text(encoding="utf-8")
    )
    detection = summary["detection_performance"]

    assert detection["actionable_false_negative_count"] >= 1
    assert detection["actionable_missed_contamination_count"] >= 1
    assert summary["missed_contamination_count_by_severity_bucket"]["medium"] >= 1
