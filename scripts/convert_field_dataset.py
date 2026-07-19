from __future__ import annotations

import argparse
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

DEAD_DAY_MIN_IRRADIANCE_W_M2 = 200.0


def convert_pvdaq_power_files(
    source_directory: Path | list[Path],
    output_path: Path,
    *,
    timezone_name: str,
    power_column: str | list[str],
    irradiance_column: str | None = None,
    minimum_coverage_hours: float = 0.0,
) -> dict[str, list[str]]:
    """Convert PVDAQ interval AC power files to the field-validation energy contract.

    ``power_column`` may name several columns (e.g. one channel per inverter); they are
    summed per timestamp, and a timestamp where any requested channel is missing is
    dropped rather than allowed to undercount the site total. A day file lacking any
    requested channel in its header is treated as missing, not zero.

    When ``irradiance_column`` is given, days where the plane-of-array sensor saw real
    sun (peak above ``DEAD_DAY_MIN_IRRADIANCE_W_M2``) while the meter recorded zero
    positive AC power are excluded as instrument/inverter outages: they are availability
    losses, not soiling behavior, and comparing the soiling model against a dead meter
    only corrupts the validation metrics.

    When ``minimum_coverage_hours`` is positive, days whose recorded electrical samples
    span less than that many hours are excluded as partial-logging outages: a file that
    only captured a fragment of the day (for example a logger that ran for 90 minutes at
    night) cannot measure the day's energy, so keeping its near-zero total would compare
    the simulator against a data gap.

    Returns the excluded dates by category (``dead_meter``, ``short_coverage``) for
    reporting.
    """

    timezone = ZoneInfo(timezone_name)
    directories = source_directory if isinstance(source_directory, list) else [source_directory]
    power_columns = [power_column] if isinstance(power_column, str) else list(power_column)
    if not power_columns:
        raise ValueError("at least one power column is required")
    source_paths = sorted(path for directory in directories for path in directory.glob("*.csv"))
    daily_records: list[dict[str, object]] = []
    excluded: dict[str, list[str]] = {"dead_meter": [], "short_coverage": []}
    for source_path in source_paths:
        available = pd.read_csv(source_path, nrows=0).columns
        if any(column not in available for column in power_columns):
            # Logger recorded no (or not all) electrical channels that day: the day is
            # missing data, not zero production, so it must not appear in the output.
            continue
        columns = ["measured_on", *power_columns]
        if irradiance_column is not None and irradiance_column in available:
            columns.append(irradiance_column)
        raw = pd.read_csv(source_path, usecols=columns)
        power = (
            raw[power_columns]
            .apply(pd.to_numeric, errors="coerce")
            .sum(axis=1, min_count=len(power_columns))
        )
        samples = pd.DataFrame(
            {"power_w": power.to_numpy()},
            index=pd.DatetimeIndex(pd.to_datetime(raw["measured_on"])),
        ).dropna()
        if len(samples) < 2:
            continue
        samples = samples.sort_index()
        local_midnight = samples.index[0].date()
        coverage_hours = (samples.index[-1] - samples.index[0]).total_seconds() / 3600.0
        if minimum_coverage_hours > 0.0 and coverage_hours < minimum_coverage_hours:
            excluded["short_coverage"].append(local_midnight.isoformat())
            continue
        interval_hours = samples.index.to_series().diff().shift(-1).dt.total_seconds() / 3600.0
        typical_interval = float(interval_hours.dropna().median())
        interval_hours = interval_hours.fillna(typical_interval).clip(upper=0.5)
        energy_kwh = float(
            (samples["power_w"].clip(lower=0.0) * interval_hours.to_numpy()).sum() / 1000.0
        )
        if irradiance_column is not None and irradiance_column in raw.columns and energy_kwh == 0.0:
            irradiance = pd.to_numeric(raw[irradiance_column], errors="coerce")
            peak_irradiance = float(irradiance.max()) if irradiance.notna().any() else 0.0
            if peak_irradiance > DEAD_DAY_MIN_IRRADIANCE_W_M2:
                excluded["dead_meter"].append(local_midnight.isoformat())
                continue
        timestamp = pd.Timestamp(local_midnight, tz=timezone)
        daily_records.append(
            {
                "timestamp": timestamp.isoformat(),
                "measured_ac_energy_kwh": energy_kwh,
                "cleaning_event": 0,
            }
        )
    if not daily_records:
        raise ValueError(f"no usable PVDAQ power records found under {directories}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame.from_records(daily_records).to_csv(output_path, index=False)
    return excluded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_directory", type=Path, nargs="+")
    parser.add_argument("--output", dest="output_path", type=Path, required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument(
        "--power-column",
        dest="power_columns",
        action="append",
        required=True,
        help="Interval power column in watts; repeat the flag to sum several channels.",
    )
    parser.add_argument(
        "--irradiance-column",
        default=None,
        help=(
            "Optional plane-of-array irradiance column. When given, zero-production days "
            "with real sun are excluded as instrument outages and printed for the record."
        ),
    )
    parser.add_argument(
        "--minimum-coverage-hours",
        type=float,
        default=0.0,
        help=(
            "Exclude days whose recorded electrical samples span fewer hours than this "
            "(partial-logging outages). 0 disables the check."
        ),
    )
    arguments = parser.parse_args()
    excluded = convert_pvdaq_power_files(
        arguments.source_directory,
        arguments.output_path,
        timezone_name=arguments.timezone,
        power_column=arguments.power_columns,
        irradiance_column=arguments.irradiance_column,
        minimum_coverage_hours=arguments.minimum_coverage_hours,
    )
    for category, label in [
        ("dead_meter", "dead-meter"),
        ("short_coverage", "short-coverage"),
    ]:
        if excluded[category]:
            dates = ", ".join(excluded[category])
            print(f"excluded {len(excluded[category])} {label} day(s): {dates}")


if __name__ == "__main__":
    main()
