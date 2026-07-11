"""Run the dry-desert (Riyadh) vs humid-desert (Dammam) coating experiment.

Executes compare-all-scenarios for both site configs against live NASA POWER
weather (cached per coordinate under data/cache/weather), then writes a
side-by-side summary of how the humid coastal site changes baseline soiling
and the coating's value versus the dry inland reference.

The two configs are identical except site name/coordinates and run prefix, so
every difference in the summary is driven by the weather at each location.

Usage:
    python scripts/compare_dry_vs_humid.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from solarclean.application.comparison import (  # noqa: E402
    CompareAllScenarios,
    CompareAllScenariosResult,
)
from solarclean.config.loader import load_config  # noqa: E402

SITES: tuple[tuple[str, Path], ...] = (
    ("dry_riyadh", PROJECT_ROOT / "configs" / "riyadh_dry_desert.yaml"),
    ("humid_dammam", PROJECT_ROOT / "configs" / "dammam_humid_desert.yaml"),
)


def _site_metrics(result: CompareAllScenariosResult) -> dict[str, object]:
    comparison = result.comparison
    baseline = comparison.scenario_results["baseline"]
    coating = comparison.scenario_results["coating"]
    reactive = comparison.scenario_results["reactive"]

    dew_risks = [float(daily.extensions.get("dew_risk", 0.0)) for daily in baseline.daily_results]
    cementation_indices = [
        float(daily.extensions.get("cementation_index", 0.0)) for daily in baseline.daily_results
    ]
    cementation_events = [
        event for event in baseline.events if event.event_type == "dew_cementation_adhesion"
    ]
    condensed_liters = sum(
        float(daily.extensions.get("condensed_water_liters", 0.0))
        for daily in coating.daily_results
    )
    passive_cleaning_days = sum(
        1 for daily in coating.daily_results if daily.extensions.get("passive_cleaning_day")
    )

    def gain(scenario) -> float:
        return scenario.annual_actual_energy_kwh - baseline.annual_actual_energy_kwh

    net_benefit = {entry.scenario_id: entry.net_annual_benefit_sar for entry in comparison.ranking}
    return {
        "run_id": comparison.run_id,
        "annual_clean_energy_kwh": baseline.annual_clean_energy_kwh,
        "baseline_actual_energy_kwh": baseline.annual_actual_energy_kwh,
        "baseline_soiling_loss_percent": baseline.annual_energy_loss_percent,
        "coating_actual_energy_kwh": coating.annual_actual_energy_kwh,
        "coating_gain_vs_baseline_kwh": gain(coating),
        "coating_gain_vs_baseline_percent": (
            gain(coating) / baseline.annual_actual_energy_kwh * 100.0
        ),
        "reactive_gain_vs_baseline_kwh": gain(reactive),
        "dew_days_over_half_risk": sum(1 for risk in dew_risks if risk >= 0.5),
        "dew_days_any_risk": sum(1 for risk in dew_risks if risk > 0.0),
        "mean_cementation_index": (
            sum(cementation_indices) / len(cementation_indices) if cementation_indices else 0.0
        ),
        "cementation_event_count": len(cementation_events),
        "cementation_extra_soiling_fraction": sum(event.magnitude for event in cementation_events),
        "coating_condensed_water_liters": condensed_liters,
        "coating_passive_cleaning_days": passive_cleaning_days,
        "recommended_winner": comparison.recommendation.winner,
        "coating_net_annual_benefit_sar": net_benefit.get("coating"),
        "reactive_net_annual_benefit_sar": net_benefit.get("reactive"),
    }


def _markdown_table(frame: pd.DataFrame) -> str:
    """Plain-pipe markdown table (avoids the optional tabulate dependency)."""
    headers = ["metric", *frame.columns]
    rows = [[str(index), *(_cell(value) for value in record)] for index, record in frame.iterrows()]
    widths = [max(len(str(cell)) for cell in column) for column in zip(headers, *rows, strict=True)]
    lines = [
        "| "
        + " | ".join(str(cell).ljust(width) for cell, width in zip(row, widths, strict=True))
        + " |"
        for row in ([headers, ["-" * width for width in widths], *rows])
    ]
    return "\n".join(lines)


def _cell(value: object) -> str:
    if isinstance(value, float):
        return f"{value:,.3f}"
    return str(value)


def main() -> None:
    rows: dict[str, dict[str, object]] = {}
    for site_id, config_path in SITES:
        print(f"[{site_id}] running compare-all-scenarios with {config_path.name} ...")
        result = CompareAllScenarios(load_config(config_path)).run()
        rows[site_id] = _site_metrics(result)
        print(f"[{site_id}] done -> {result.output_directory}")

    frame = pd.DataFrame(rows)
    frame.index.name = "metric"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = PROJECT_ROOT / "outputs" / f"dry-vs-humid-desert-{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "dry_vs_humid_summary.csv"
    frame.to_csv(csv_path)

    lines = [
        "# Dry desert (Riyadh) vs humid coastal desert (Dammam)",
        "",
        "Same farm, calibration, seed, and coating in both arms; only the site",
        "coordinates (and therefore the NASA POWER weather) differ.",
        "",
        _markdown_table(frame),
        "",
        "Source runs: "
        + ", ".join(f"{site_id}={metrics['run_id']}" for site_id, metrics in rows.items()),
    ]
    md_path = output_dir / "dry_vs_humid_summary.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print()
    print(frame.to_string())
    print()
    print(f"Summary written to {csv_path} and {md_path}")


if __name__ == "__main__":
    main()
