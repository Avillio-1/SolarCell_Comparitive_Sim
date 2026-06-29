from __future__ import annotations

import json
from pathlib import Path

from solarclean.application.phase35 import Phase35Validator
from solarclean.config.loader import load_config


def test_phase35_fixture_report_files_are_serializable(tmp_path: Path) -> None:
    config = load_config(
        Path("configs/offline_fixture.yaml"), overrides={"output": {"base_directory": tmp_path}}
    )

    result = Phase35Validator(config).run()

    report_names = [
        "phase35_weather_report.json",
        "phase35_energy_report.json",
        "phase35_farm_equivalence_report.json",
        "phase35_event_tape.json",
        "phase35_summary.json",
    ]
    for name in report_names:
        path = result.output_directory / name
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8"))
