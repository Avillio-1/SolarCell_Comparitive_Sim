from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "convert_field_dataset.py"
_SPEC = importlib.util.spec_from_file_location("convert_field_dataset", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
convert_field_dataset = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(convert_field_dataset)


def _write_day(
    directory: Path,
    day: str,
    *,
    power_w: list[float],
    poa_w_m2: list[float] | None,
    include_power_column: bool = True,
) -> None:
    timestamps = pd.date_range(f"{day} 08:00", periods=len(power_w), freq="15min")
    frame = pd.DataFrame({"measured_on": timestamps.strftime("%Y-%m-%d %H:%M:%S")})
    if include_power_column:
        frame["ac_power_hw__1"] = power_w
    if poa_w_m2 is not None:
        frame["poa_irradiance__2"] = poa_w_m2
    frame.to_csv(directory / f"system_1__date_{day.replace('-', '_')}.csv", index=False)


def test_sunny_dead_meter_day_is_excluded_and_reported(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    _write_day(source, "2019-01-01", power_w=[1000.0, 2000.0], poa_w_m2=[500.0, 700.0])
    _write_day(source, "2019-01-02", power_w=[-200.0, -200.0], poa_w_m2=[900.0, 1000.0])
    output = tmp_path / "measured.csv"

    excluded = convert_field_dataset.convert_pvdaq_power_files(
        source,
        output,
        timezone_name="America/Los_Angeles",
        power_column="ac_power_hw__1",
        irradiance_column="poa_irradiance__2",
    )

    assert excluded == {"dead_meter": ["2019-01-02"], "short_coverage": []}
    result = pd.read_csv(output)
    assert list(result["timestamp"].str[:10]) == ["2019-01-01"]
    assert result["measured_ac_energy_kwh"].iloc[0] == pytest.approx(0.75)


def test_dark_zero_day_is_kept_as_genuine_zero(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    _write_day(source, "2019-01-03", power_w=[0.0, 0.0], poa_w_m2=[50.0, 80.0])
    output = tmp_path / "measured.csv"

    excluded = convert_field_dataset.convert_pvdaq_power_files(
        source,
        output,
        timezone_name="America/Los_Angeles",
        power_column="ac_power_hw__1",
        irradiance_column="poa_irradiance__2",
    )

    assert excluded == {"dead_meter": [], "short_coverage": []}
    result = pd.read_csv(output)
    assert result["measured_ac_energy_kwh"].iloc[0] == pytest.approx(0.0)


def test_day_without_electrical_channels_is_treated_as_missing(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    _write_day(source, "2019-01-04", power_w=[1000.0, 1000.0], poa_w_m2=[600.0, 600.0])
    _write_day(
        source,
        "2019-01-05",
        power_w=[0.0, 0.0],
        poa_w_m2=[600.0, 600.0],
        include_power_column=False,
    )
    output = tmp_path / "measured.csv"

    convert_field_dataset.convert_pvdaq_power_files(
        source,
        output,
        timezone_name="America/Los_Angeles",
        power_column="ac_power_hw__1",
        irradiance_column="poa_irradiance__2",
    )

    result = pd.read_csv(output)
    assert list(result["timestamp"].str[:10]) == ["2019-01-04"]


def test_multiple_power_columns_are_summed(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    timestamps = pd.date_range("2019-01-08 08:00", periods=2, freq="15min")
    frame = pd.DataFrame(
        {
            "measured_on": timestamps.strftime("%Y-%m-%d %H:%M:%S"),
            "inv1_ac_power__1": [1000.0, 1000.0],
            "inv2_ac_power__2": [500.0, 500.0],
        }
    )
    frame.to_csv(source / "system_1__date_2019_01_08.csv", index=False)
    output = tmp_path / "measured.csv"

    convert_field_dataset.convert_pvdaq_power_files(
        source,
        output,
        timezone_name="America/Denver",
        power_column=["inv1_ac_power__1", "inv2_ac_power__2"],
    )

    result = pd.read_csv(output)
    # 1500 W for two 15-minute intervals = 0.75 kWh.
    assert result["measured_ac_energy_kwh"].iloc[0] == pytest.approx(0.75)


def test_day_lacking_one_of_several_power_columns_is_treated_as_missing(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    complete = pd.DataFrame(
        {
            "measured_on": ["2019-01-09 08:00:00", "2019-01-09 08:15:00"],
            "inv1_ac_power__1": [1000.0, 1000.0],
            "inv2_ac_power__2": [500.0, 500.0],
        }
    )
    complete.to_csv(source / "system_1__date_2019_01_09.csv", index=False)
    partial = pd.DataFrame(
        {
            "measured_on": ["2019-01-10 08:00:00", "2019-01-10 08:15:00"],
            "inv1_ac_power__1": [1000.0, 1000.0],
        }
    )
    partial.to_csv(source / "system_1__date_2019_01_10.csv", index=False)
    output = tmp_path / "measured.csv"

    convert_field_dataset.convert_pvdaq_power_files(
        source,
        output,
        timezone_name="America/Denver",
        power_column=["inv1_ac_power__1", "inv2_ac_power__2"],
    )

    result = pd.read_csv(output)
    assert list(result["timestamp"].str[:10]) == ["2019-01-09"]


def test_timestamp_missing_one_channel_is_dropped_not_undercounted(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    frame = pd.DataFrame(
        {
            "measured_on": ["2019-01-11 08:00:00", "2019-01-11 08:15:00", "2019-01-11 08:30:00"],
            "inv1_ac_power__1": [1000.0, 1000.0, 1000.0],
            "inv2_ac_power__2": [500.0, 500.0, None],
        }
    )
    frame.to_csv(source / "system_1__date_2019_01_11.csv", index=False)
    output = tmp_path / "measured.csv"

    convert_field_dataset.convert_pvdaq_power_files(
        source,
        output,
        timezone_name="America/Denver",
        power_column=["inv1_ac_power__1", "inv2_ac_power__2"],
    )

    result = pd.read_csv(output)
    # Only the two complete samples count (1500 W x 2 x 15 min = 0.75 kWh); treating the
    # incomplete 08:30 sample as inverter-1-only would report 1.0 kWh instead.
    assert result["measured_ac_energy_kwh"].iloc[0] == pytest.approx(0.75)


def test_partial_logging_day_is_excluded_when_coverage_floor_is_set(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    # Full day: samples spanning 20 hours.
    full = pd.DataFrame(
        {
            "measured_on": ["2019-01-12 02:00:00", "2019-01-12 12:00:00", "2019-01-12 22:00:00"],
            "ac_power_hw__1": [0.0, 5000.0, 0.0],
            "poa_irradiance__2": [0.0, 900.0, 0.0],
        }
    )
    full.to_csv(source / "system_1__date_2019_01_12.csv", index=False)
    # Night-only logger fragment: 90 minutes of standby tare, no daylight recorded.
    fragment = pd.DataFrame(
        {
            "measured_on": ["2019-01-13 01:00:00", "2019-01-13 01:45:00", "2019-01-13 02:30:00"],
            "ac_power_hw__1": [-90.0, -90.0, -90.0],
            "poa_irradiance__2": [0.0, 0.0, 0.0],
        }
    )
    fragment.to_csv(source / "system_1__date_2019_01_13.csv", index=False)
    output = tmp_path / "measured.csv"

    excluded = convert_field_dataset.convert_pvdaq_power_files(
        source,
        output,
        timezone_name="America/New_York",
        power_column="ac_power_hw__1",
        irradiance_column="poa_irradiance__2",
        minimum_coverage_hours=18.0,
    )

    assert excluded == {"dead_meter": [], "short_coverage": ["2019-01-13"]}
    result = pd.read_csv(output)
    assert list(result["timestamp"].str[:10]) == ["2019-01-12"]


def test_multiple_source_directories_are_merged(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    _write_day(first, "2019-01-06", power_w=[800.0, 800.0], poa_w_m2=[600.0, 600.0])
    _write_day(second, "2019-01-07", power_w=[900.0, 900.0], poa_w_m2=[600.0, 600.0])
    output = tmp_path / "measured.csv"

    convert_field_dataset.convert_pvdaq_power_files(
        [first, second],
        output,
        timezone_name="America/Los_Angeles",
        power_column="ac_power_hw__1",
        irradiance_column="poa_irradiance__2",
    )

    result = pd.read_csv(output)
    assert list(result["timestamp"].str[:10]) == ["2019-01-06", "2019-01-07"]
