from __future__ import annotations

import argparse
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


def convert_pvdaq_power_files(
    source_directory: Path,
    output_path: Path,
    *,
    timezone_name: str,
    power_column: str,
) -> None:
    """Convert PVDAQ interval AC power files to the field-validation energy contract."""

    timezone = ZoneInfo(timezone_name)
    daily_records: list[dict[str, object]] = []
    for source_path in sorted(source_directory.glob("*.csv")):
        raw = pd.read_csv(source_path, usecols=["measured_on", power_column])
        power = pd.to_numeric(raw[power_column], errors="coerce")
        samples = pd.DataFrame(
            {"power_w": power.to_numpy()},
            index=pd.DatetimeIndex(pd.to_datetime(raw["measured_on"])),
        ).dropna()
        if len(samples) < 2:
            continue
        samples = samples.sort_index()
        interval_hours = samples.index.to_series().diff().shift(-1).dt.total_seconds() / 3600.0
        typical_interval = float(interval_hours.dropna().median())
        interval_hours = interval_hours.fillna(typical_interval).clip(upper=0.5)
        energy_kwh = float(
            (samples["power_w"].clip(lower=0.0) * interval_hours.to_numpy()).sum() / 1000.0
        )
        local_midnight = samples.index[0].date()
        timestamp = pd.Timestamp(local_midnight, tz=timezone)
        daily_records.append(
            {
                "timestamp": timestamp.isoformat(),
                "measured_ac_energy_kwh": energy_kwh,
                "cleaning_event": 0,
            }
        )
    if not daily_records:
        raise ValueError(f"no usable PVDAQ power records found under {source_directory}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame.from_records(daily_records).to_csv(output_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_directory", type=Path)
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--power-column", required=True)
    arguments = parser.parse_args()
    convert_pvdaq_power_files(
        arguments.source_directory,
        arguments.output_path,
        timezone_name=arguments.timezone,
        power_column=arguments.power_column,
    )


if __name__ == "__main__":
    main()
