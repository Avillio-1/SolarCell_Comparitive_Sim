"""Regression: the dry-vs-humid experiment configs must stay calibration-consistent.

The dammam/riyadh site configs document themselves as identical except for
site coordinates, naming, and provenance notes, and both claim the Riyadh
central-v2 calibration. Historically they drifted from configs/default.yaml on
crew worker-minutes (8/25 instead of the corrected 2-worker 16/50 billing),
silently halving reactive labour cost in the flagship experiment.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from solarclean.config.loader import load_config
from solarclean.config.models import ReactiveCrewConfig

CONFIGS = Path("configs")
# Fields that are allowed (and expected) to differ between the two site arms.
SITE_IDENTITY_PATHS = (
    ("site",),
    ("simulation", "run_id_prefix"),
    ("calibration", "source_note"),
)


def _without(payload: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> dict[str, Any]:
    pruned = copy.deepcopy(payload)
    for path in paths:
        node = pruned
        for key in path[:-1]:
            node = node[key]
        node.pop(path[-1], None)
    return pruned


@pytest.mark.parametrize(
    "config_name",
    ["riyadh_dry_desert.yaml", "dammam_humid_desert.yaml"],
)
def test_site_configs_bill_crew_labour_like_the_central_calibration(config_name: str) -> None:
    default = load_config(CONFIGS / "default.yaml")
    site = load_config(CONFIGS / config_name)
    # Worker-minutes for a 2-person crew at the registry central 120
    # panels/worker-hour: identical to the documented default calibration.
    assert site.reactive_cv.crew.setup_minutes_per_cohort == pytest.approx(
        default.reactive_cv.crew.setup_minutes_per_cohort
    )
    assert site.reactive_cv.crew.cleaning_minutes_per_cohort == pytest.approx(
        default.reactive_cv.crew.cleaning_minutes_per_cohort
    )


def test_reactive_crew_defaults_bill_worker_minutes_for_the_full_crew() -> None:
    crew = ReactiveCrewConfig()

    assert crew.setup_minutes_per_cohort == pytest.approx(16.0)
    assert crew.cleaning_minutes_per_cohort == pytest.approx(50.0)


def test_dry_and_humid_arms_differ_only_in_site_identity() -> None:
    dry = load_config(CONFIGS / "riyadh_dry_desert.yaml").model_dump(mode="json")
    humid = load_config(CONFIGS / "dammam_humid_desert.yaml").model_dump(mode="json")
    assert _without(dry, SITE_IDENTITY_PATHS) == _without(humid, SITE_IDENTITY_PATHS)
