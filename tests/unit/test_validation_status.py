from __future__ import annotations

from pathlib import Path

import yaml

from solarclean.domain.calibration.registry import ParameterRegistry, build_validation_status


def _parameter_record(
    *,
    name: str,
    central_value: float,
    low_value: float,
    high_value: float,
    evidence_type: str,
    confidence: str,
    status: str,
) -> dict[str, object]:
    return {
        "name": name,
        "configuration_path": name,
        "category": "test",
        "central_value": central_value,
        "low_value": low_value,
        "high_value": high_value,
        "unit": "fraction",
        "source": "fabricated test source",
        "evidence_type": evidence_type,
        "source_geography_and_climate": "test",
        "applicability_to_saudi_conditions": "test only",
        "confidence": confidence,
        "status": status,
        "rationale": "exercise evidence summary",
        "limitations": "fabricated",
        "responsible_module_or_owner": "tests",
    }


def test_build_validation_status_counts_and_ranks_relative_ranges(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(
        yaml.safe_dump(
            {
                "metadata": {"version": "test"},
                "parameters": [
                    _parameter_record(
                        name="wide",
                        central_value=10.0,
                        low_value=0.0,
                        high_value=30.0,
                        evidence_type="assumed",
                        confidence="low",
                        status="provisional",
                    ),
                    _parameter_record(
                        name="narrow",
                        central_value=10.0,
                        low_value=9.0,
                        high_value=11.0,
                        evidence_type="inferred",
                        confidence="medium",
                        status="blocked",
                    ),
                    _parameter_record(
                        name="zero-central-skipped",
                        central_value=0.0,
                        low_value=0.0,
                        high_value=5.0,
                        evidence_type="measured",
                        confidence="high",
                        status="validated",
                    ),
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = build_validation_status(ParameterRegistry.from_yaml(registry_path))

    assert summary["absolute_outputs_field_validated"] is False
    assert summary["parameter_counts_by_status"] == {
        "provisional": 1,
        "blocked": 1,
        "validated": 1,
    }
    assert summary["parameter_counts_by_evidence_type"] == {
        "assumed": 1,
        "inferred": 1,
        "measured": 1,
    }
    assert summary["lowest_confidence"] == "low"
    uncertain = summary["key_uncertain_parameters"]
    assert isinstance(uncertain, list)
    assert [parameter["name"] for parameter in uncertain] == ["wide", "narrow"]
    assert uncertain[0] == {
        "name": "wide",
        "central_value": 10.0,
        "low_value": 0.0,
        "high_value": 30.0,
        "confidence": "low",
        "status": "provisional",
    }
