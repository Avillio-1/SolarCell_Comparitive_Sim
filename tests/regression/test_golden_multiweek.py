from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.config_factory import fixture_config

from solarclean.application.phase35 import Phase35Validator


def test_multiweek_golden_regression_fixture(tmp_path: Path) -> None:
    expected = json.loads(
        Path("data/fixtures/golden_multiweek_expected.json").read_text(encoding="utf-8")
    )
    config = fixture_config(
        overrides={
            "simulation": {
                "start": "2025-01-01T00:00:00+03:00",
                "end": "2025-01-21T23:00:00+03:00",
                "run_id_prefix": "golden-multiweek",
            },
            "output": {"base_directory": tmp_path},
        },
    )

    result = Phase35Validator(config).run()

    assert result.summary["annual_clean_energy_kwh"] == pytest.approx(
        expected["annual_clean_energy_kwh"]
    )
    assert result.summary["annual_actual_energy_kwh"] == pytest.approx(
        expected["annual_actual_energy_kwh"]
    )
    assert result.summary["soiling_loss_percent"] == pytest.approx(expected["soiling_loss_percent"])
    assert result.summary["event_tape_checksum"] == expected["event_tape_checksum"]
