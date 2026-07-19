"""Read-only access to run output directories.

Everything here reads files that the application layer already wrote. The one
transformation allowed is *reshaping* (picking columns out of a CSV so a chart
can plot them). No energy, cost, or statistical values are computed in this
module -- if a number is not in an artifact file, the dashboard does not show it.
"""

from __future__ import annotations

import contextlib
import csv
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast

# Artifacts small enough to inline in a results page. Everything else is
# offered as a download only.
_TEXT_PREVIEW_LIMIT_BYTES = 200_000
# Daily summaries can include serialized cohort-state extension fields. They
# are not parsed by the dashboard, but CSV still has to read past them to pick
# the displayed columns.
_CSV_FIELD_SIZE_LIMIT = 10_000_000


@dataclass
class RunEntry:
    run_id: str
    path: Path
    kind: str  # compare-all-scenarios | monte-carlo | sensitivity-oneway | ...
    created: str
    winner: str | None
    valid: bool | None
    # Stored headline figures read from the same artifacts as winner/valid:
    # the comparison's decisive margin and the MC majority winner's stored
    # win probability. Display data only — never computed here.
    margin_sar: float | None = None
    win_probability: float | None = None


def _detect_kind(run_id: str) -> str:
    # Run ids follow "<config>-<command>-<timestamp>-<hash>" from OutputWriter.
    # Ordering matters: "compare-multi-year" must not match "compare-all-scenarios",
    # and every CLI writer kind is named so run cards never say "unknown" for a
    # directory the tooling itself produced.
    for kind in (
        "compare-all-scenarios",
        "compare-multi-year",
        "monte-carlo",
        "sensitivity-oneway",
        "sensitivity-winner-map",
        "break-even",
        "fetch-weather",
        "run-clean",
        "run-baseline",
        "validate-weather",
        "validate-phase-3-5",
        "profile-full-year",
    ):
        if f"-{kind}-" in run_id:
            return kind
    return "unknown"


def load_json(path: Path) -> dict[str, object] | None:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def list_runs(outputs_dir: Path) -> list[RunEntry]:
    entries: list[RunEntry] = []
    if not outputs_dir.is_dir():
        return entries
    for run_dir in outputs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        if not any(run_dir.iterdir()):
            # Empty shell left behind when a delete raced a sync client's
            # directory handle (OneDrive). The run's data is gone; hide it
            # and quietly finish the removal when the handle is released.
            with contextlib.suppress(OSError):
                run_dir.rmdir()
            continue
        if not any(entry.is_file() for entry in run_dir.iterdir()):
            # A directory of directories is a container (e.g. a test-output
            # root), not a run: a run package always has artifact files at its
            # top level. Listing containers produced unusable "unknown/undated"
            # cards. Left in place — never swept — because their contents are
            # not ours to judge.
            continue
        kind = _detect_kind(run_dir.name)
        winner: str | None = None
        valid: bool | None = None
        margin_sar: float | None = None
        win_probability: float | None = None
        recommendation = load_json(run_dir / "recommendation.json")
        if recommendation is not None:
            winner = recommendation.get("winner")  # type: ignore[assignment]
            # Same reading as the run page header: calculation_valid is the
            # stored "arithmetic reconciles" flag; the legacy valid field also
            # encoded decision-grade policy and made verified exploratory runs
            # show as failed on their cards.
            raw_valid = recommendation.get("calculation_valid", recommendation.get("valid"))
            valid = bool(raw_valid) if raw_valid is not None else None
            raw_margin = recommendation.get("decisive_margin_sar")
            if isinstance(raw_margin, int | float):
                margin_sar = float(raw_margin)
        mc_summary = load_json(run_dir / "monte_carlo_summary.json")
        if mc_summary is not None:
            winner = mc_summary.get("majority_trial_winner")  # type: ignore[assignment]
            summaries = mc_summary.get("scenario_summaries")
            if isinstance(winner, str) and isinstance(summaries, dict):
                winner_summary = summaries.get(winner)
                raw_probability = (
                    winner_summary.get("win_probability")
                    if isinstance(winner_summary, dict)
                    else None
                )
                if isinstance(raw_probability, int | float):
                    win_probability = float(raw_probability)
        created = ""
        metadata = load_json(run_dir / "metadata.json") or load_json(
            run_dir / "comparison_metadata.json"
        )
        if metadata is not None:
            # All current writers use ``created_at_utc``. Keep the legacy key
            # as a fallback so older run directories remain readable.
            created = str(metadata.get("created_at_utc") or metadata.get("created_utc", ""))
        entries.append(
            RunEntry(
                run_id=run_dir.name,
                path=run_dir,
                kind=kind,
                created=created,
                winner=winner,
                valid=valid,
                margin_sar=margin_sar,
                win_probability=win_probability,
            )
        )
    # Timestamps are embedded in the run id, so name order is time order.
    entries.sort(key=lambda entry: entry.run_id, reverse=True)
    return entries


def resolve_run_dir(outputs_dir: Path, run_id: str) -> Path | None:
    """Resolve a run id to its directory, rejecting path traversal."""
    candidate = (outputs_dir / run_id).resolve()
    if candidate.parent != outputs_dir.resolve() or not candidate.is_dir():
        return None
    return candidate


def resolve_artifact(run_dir: Path, name: str) -> Path | None:
    candidate = (run_dir / name).resolve()
    if candidate.parent != run_dir.resolve() or not candidate.is_file():
        return None
    return candidate


def list_artifacts(run_dir: Path) -> list[dict[str, object]]:
    files = []
    for path in sorted(run_dir.iterdir()):
        if path.is_file():
            files.append({"name": path.name, "size_bytes": path.stat().st_size})
    return files


@lru_cache(maxsize=24)
def _read_csv_rows_cached(
    path_text: str, mtime_ns: int, limit: int | None
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Read an immutable CSV snapshot keyed by path and modification time."""

    del mtime_ns  # Part of the cache key; the file contents are read below.
    csv.field_size_limit(_CSV_FIELD_SIZE_LIMIT)
    with Path(path_text).open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = tuple(next(reader, []))
        rows: list[tuple[str, ...]] = []
        for i, row in enumerate(reader):
            if limit is not None and i >= limit:
                break
            rows.append(tuple(row))
    return header, tuple(rows)


def read_csv_rows(path: Path, limit: int | None = None) -> tuple[list[str], list[list[str]]]:
    """Read CSV rows, reusing an unchanged artifact within this process."""

    header, rows = _read_csv_rows_cached(str(path.resolve()), path.stat().st_mtime_ns, limit)
    return list(header), [list(row) for row in rows]


def daily_series(run_dir: Path, value_column: str) -> dict[str, object] | None:
    """Reshape scenario_daily_summary.csv into per-scenario chart series.

    Column selection only: dates on the x axis, the stored value of
    ``value_column`` per scenario on the y axis. No values are computed.
    """
    path = run_dir / "scenario_daily_summary.csv"
    if not path.is_file():
        return None
    header, rows = read_csv_rows(path)
    try:
        date_col = header.index("date")
        scenario_col = header.index("scenario_name")
        value_col = header.index(value_column)
    except ValueError:
        return None
    dates: list[str] = []
    series: dict[str, dict[str, float | None]] = {}
    for row in rows:
        date, scenario, raw = row[date_col], row[scenario_col], row[value_col]
        if date not in dates:
            dates.append(date)
        normalized = raw.strip().lower()
        if normalized == "true":
            value: float | None = 1.0
        elif normalized == "false":
            value = 0.0
        else:
            try:
                value = float(raw)
            except ValueError:
                value = None
        series.setdefault(scenario, {})[date] = value
    return {
        "dates": dates,
        "series": {
            scenario: [values.get(date) for date in dates] for scenario, values in series.items()
        },
    }


def daily_energy_series(run_dir: Path) -> dict[str, object] | None:
    return daily_series(run_dir, "actual_energy_kwh")


def daily_clean_reference_series(run_dir: Path) -> dict[str, object] | None:
    """Read the one clean-reference series shared by every scenario."""

    reshaped = daily_series(run_dir, "clean_energy_kwh")
    if reshaped is None:
        return None
    series = reshaped.get("series")
    if not isinstance(series, dict):
        return None
    values = series.get("baseline")
    if not isinstance(values, list):
        return None
    return {"dates": reshaped["dates"], "values": values}


def daily_rainfall_series(run_dir: Path) -> dict[str, object] | None:
    """Read the shared daily rainfall values stored with the baseline result."""

    reshaped = daily_series(run_dir, "extension_precipitation_mm")
    if reshaped is None:
        return None
    series = reshaped.get("series")
    if not isinstance(series, dict):
        return None
    values = series.get("baseline")
    if not isinstance(values, list):
        return None
    return {"dates": reshaped["dates"], "values": values}


def daily_relative_humidity_series(run_dir: Path) -> dict[str, object] | None:
    """Read the persisted daily-mean RH shared by every scenario."""

    reshaped = daily_series(run_dir, "extension_mean_relative_humidity_pct")
    if reshaped is None:
        return None
    series = reshaped.get("series")
    if not isinstance(series, dict):
        return None
    values = series.get("baseline")
    if not isinstance(values, list):
        return None
    return {"dates": reshaped["dates"], "values": values}


def daily_weather_diagnostics(run_dir: Path) -> dict[str, object] | None:
    """Select persisted daily irradiance and temperature diagnostics."""

    path = run_dir / "daily_weather_diagnostics.csv"
    if not path.is_file():
        return None
    header, rows = read_csv_rows(path)
    required = (
        "date",
        "daily_ghi_irradiation_kwh_m2",
        "daylight_mean_ambient_temperature_c",
        "daylight_mean_cell_temperature_c",
    )
    if any(column not in header for column in required):
        return None
    indices = {column: header.index(column) for column in required}
    dates: list[str] = []
    values: dict[str, list[float | None]] = {column: [] for column in required[1:]}
    for row in rows:
        dates.append(row[indices["date"]])
        for column in required[1:]:
            try:
                value: float | None = float(row[indices[column]])
            except (IndexError, ValueError):
                value = None
            values[column].append(value)
    return {"dates": dates, **values}


def daily_event_markers(run_dir: Path) -> list[dict[str, object]]:
    """Collapse stored scenario events into date/category chart markers."""

    path = run_dir / "scenario_events.csv"
    if not path.is_file():
        return []
    header, rows = read_csv_rows(path)
    required = ("date", "scenario_name", "event_type", "description")
    if any(column not in header for column in required):
        return []
    indices = {column: header.index(column) for column in required}
    grouped: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        event_type = row[indices["event_type"]]
        category = _event_marker_category(event_type)
        if category is None:
            continue
        date = row[indices["date"]]
        scenario = row[indices["scenario_name"]]
        key = (date, scenario, category)
        marker = grouped.setdefault(
            key,
            {
                "date": date,
                "scenario": scenario,
                "category": category,
                "count": 0,
            },
        )
        marker["count"] = cast(int, marker["count"]) + 1
    return list(grouped.values())


def _event_marker_category(event_type: str) -> str | None:
    normalized = event_type.lower()
    if "inspection" in normalized:
        return "inspection"
    if "cleaning" in normalized:
        return "cleaning"
    if normalized.startswith("coating_"):
        return "coating"
    if any(token in normalized for token in ("dust", "bird", "cementation", "contamination")):
        return "contamination"
    return None


def daily_cleanliness_series(run_dir: Path) -> dict[str, object] | None:
    """Read the contamination ratio actually used for each day's generation."""

    path = run_dir / "scenario_daily_summary.csv"
    if not path.is_file():
        return None
    header, rows = read_csv_rows(path)
    try:
        date_col = header.index("date")
        scenario_col = header.index("scenario_name")
    except ValueError:
        return None
    preferred_columns = {
        "baseline": "extension_dust_soiling_ratio",
        "reactive": "extension_average_dust_soiling_ratio",
        "coating": "extension_cleanliness_ratio",
    }
    fallback_col = header.index("soiling_ratio") if "soiling_ratio" in header else None
    dates: list[str] = []
    series: dict[str, dict[str, float | None]] = {}
    for row in rows:
        date, scenario = row[date_col], row[scenario_col]
        if date not in dates:
            dates.append(date)
        column_name = preferred_columns.get(scenario)
        value_col = header.index(column_name) if column_name in header else fallback_col
        raw = row[value_col] if value_col is not None else ""
        try:
            value: float | None = float(raw)
        except ValueError:
            value = None
        series.setdefault(scenario, {})[date] = value
    return {
        "dates": dates,
        "series": {
            scenario: [values.get(date) for date in dates] for scenario, values in series.items()
        },
    }


def run_fingerprint(run_dir: Path) -> dict[str, object] | None:
    """Stored daily climate/contamination values used to draw a run fingerprint.

    This deliberately returns the original GHI and cleanliness values. Colour
    mapping is a display concern handled by the browser; no physical quantity
    is inferred or re-simulated here.
    """

    weather = daily_weather_diagnostics(run_dir)
    cleanliness = daily_cleanliness_series(run_dir)
    if weather is None or cleanliness is None:
        return None
    weather_dates = weather.get("dates")
    clean_dates = cleanliness.get("dates")
    clean_series = cleanliness.get("series")
    if not isinstance(weather_dates, list) or weather_dates != clean_dates:
        return None
    if not isinstance(clean_series, dict):
        return None
    baseline = clean_series.get("baseline")
    ghi = weather.get("daily_ghi_irradiation_kwh_m2")
    if not isinstance(baseline, list) or not isinstance(ghi, list):
        return None
    cleaning_dates = sorted(
        {
            str(marker["date"])
            for marker in daily_event_markers(run_dir)
            if marker.get("category") == "cleaning" and marker.get("date")
        }
    )
    return {
        "dates": weather_dates,
        "ghi": ghi,
        "cleanliness": baseline,
        "cleaning_dates": cleaning_dates,
        "sources": [
            "daily_weather_diagnostics.csv",
            "scenario_daily_summary.csv",
            "scenario_events.csv",
        ],
    }


def dust_calendar(run_dir: Path) -> dict[str, object] | None:
    """Scenario cleanliness and stored action markers for calendar rendering."""

    cleanliness = daily_cleanliness_series(run_dir)
    if cleanliness is None:
        return None
    dates = cleanliness.get("dates")
    series = cleanliness.get("series")
    if not isinstance(dates, list) or not isinstance(series, dict):
        return None
    events_by_scenario: dict[str, dict[str, list[str]]] = {}
    for marker in daily_event_markers(run_dir):
        scenario = marker.get("scenario")
        day = marker.get("date")
        category = marker.get("category")
        if not isinstance(scenario, str) or not isinstance(day, str):
            continue
        if not isinstance(category, str):
            continue
        categories = events_by_scenario.setdefault(scenario, {}).setdefault(day, [])
        if category not in categories:
            categories.append(category)
    return {
        "dates": dates,
        "series": series,
        "events": events_by_scenario,
        "sources": ["scenario_daily_summary.csv", "scenario_events.csv"],
    }


def text_preview(path: Path) -> str | None:
    try:
        if path.stat().st_size > _TEXT_PREVIEW_LIMIT_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
