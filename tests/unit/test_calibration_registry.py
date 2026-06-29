from __future__ import annotations

from solarclean.domain.calibration.registry import CalibrationRegistry


def test_riyadh_soiling_presets_are_labelled_and_ordered() -> None:
    registry = CalibrationRegistry.default()

    low = registry.get("riyadh_low_soiling")
    medium = registry.get("riyadh_medium_soiling")
    high = registry.get("riyadh_high_soiling")

    assert "provisional" in low.label.lower()
    assert "provisional" in medium.label.lower()
    assert "provisional" in high.label.lower()
    assert (
        low.soiling.base_daily_soiling_loss_fraction
        < medium.soiling.base_daily_soiling_loss_fraction
    )
    assert (
        medium.soiling.base_daily_soiling_loss_fraction
        < high.soiling.base_daily_soiling_loss_fraction
    )
    assert low.soiling.dust_event_probability < medium.soiling.dust_event_probability
    assert medium.soiling.dust_event_probability < high.soiling.dust_event_probability


def test_registry_serializes_presets_for_documentation() -> None:
    registry = CalibrationRegistry.default()

    records = registry.to_records()

    assert {record["name"] for record in records} == {
        "riyadh_low_soiling",
        "riyadh_medium_soiling",
        "riyadh_high_soiling",
    }
    assert all(record["status"] == "provisional_requires_calibration" for record in records)
