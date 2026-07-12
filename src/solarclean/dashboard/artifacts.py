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
from pathlib import Path

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


def _detect_kind(run_id: str) -> str:
    # Run ids follow "<config>-<command>-<timestamp>-<hash>" from OutputWriter.
    for kind in (
        "compare-all-scenarios",
        "monte-carlo",
        "sensitivity-oneway",
        "sensitivity-winner-map",
        "break-even",
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
        kind = _detect_kind(run_dir.name)
        winner: str | None = None
        valid: bool | None = None
        recommendation = load_json(run_dir / "recommendation.json")
        if recommendation is not None:
            winner = recommendation.get("winner")  # type: ignore[assignment]
            raw_valid = recommendation.get("valid")
            valid = bool(raw_valid) if raw_valid is not None else None
        mc_summary = load_json(run_dir / "monte_carlo_summary.json")
        if mc_summary is not None:
            winner = mc_summary.get("majority_trial_winner")  # type: ignore[assignment]
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


def read_csv_rows(path: Path, limit: int | None = None) -> tuple[list[str], list[list[str]]]:
    csv.field_size_limit(_CSV_FIELD_SIZE_LIMIT)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        rows = []
        for i, row in enumerate(reader):
            if limit is not None and i >= limit:
                break
            rows.append(row)
    return header, rows


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


def daily_energy_series(run_dir: Path) -> dict[str, object] | None:
    return daily_series(run_dir, "actual_energy_kwh")


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


def text_preview(path: Path) -> str | None:
    try:
        if path.stat().st_size > _TEXT_PREVIEW_LIMIT_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
