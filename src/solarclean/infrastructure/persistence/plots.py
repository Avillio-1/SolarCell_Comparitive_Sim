from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from solarclean.domain.simulation.baseline import BaselineSimulationResult


def write_baseline_diagnostic_plot(path: Path, baseline: BaselineSimulationResult) -> None:
    daily = baseline.daily.reset_index()
    dates = daily["date"]
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    axes[0].plot(dates, daily["clean_energy_kwh"], label="Clean")
    axes[0].plot(dates, daily["actual_energy_kwh"], label="Baseline")
    axes[0].set_ylabel("Energy kWh")
    axes[0].legend()
    axes[1].plot(dates, daily["soiling_ratio"], color="tab:green")
    axes[1].set_ylabel("Soiling ratio")
    axes[1].set_ylim(0, 1.05)
    axes[2].bar(dates, daily["precipitation_mm"], color="tab:blue")
    axes[2].set_ylabel("Rain mm")
    axes[2].set_xlabel("Date")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def write_comparison_diagnostic_plots(
    *,
    output_dir: Path,
    daily_summary: pd.DataFrame,
    annual_summary: pd.DataFrame,
    cost_summary: pd.DataFrame,
) -> tuple[Path, ...]:
    """Write T6 comparison plots from already-exported comparison tables."""

    paths = (
        output_dir / "comparison_daily_energy.png",
        output_dir / "comparison_cumulative_energy.png",
        output_dir / "comparison_annual_kpi_breakdown.png",
    )
    _write_daily_energy_plot(paths[0], daily_summary)
    _write_cumulative_energy_plot(paths[1], daily_summary)
    _write_annual_kpi_plot(paths[2], annual_summary, cost_summary)
    return paths


def _write_daily_energy_plot(path: Path, daily_summary: pd.DataFrame) -> None:
    frame = daily_summary.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    fig, ax = plt.subplots(figsize=(10, 5))
    for scenario_id, group in frame.groupby("scenario_id", sort=True):
        ax.plot(group["date"], group["actual_energy_kwh"], label=str(scenario_id))
    ax.set_ylabel("Daily AC energy kWh")
    ax.set_xlabel("Date")
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _write_cumulative_energy_plot(path: Path, daily_summary: pd.DataFrame) -> None:
    frame = daily_summary.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    fig, ax = plt.subplots(figsize=(10, 5))
    for scenario_id, group in frame.groupby("scenario_id", sort=True):
        ordered = group.sort_values("date")
        ax.plot(
            ordered["date"],
            ordered["actual_energy_kwh"].cumsum(),
            label=str(scenario_id),
        )
    ax.set_ylabel("Cumulative AC energy kWh")
    ax.set_xlabel("Date")
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _write_annual_kpi_plot(
    path: Path,
    annual_summary: pd.DataFrame,
    cost_summary: pd.DataFrame,
) -> None:
    del cost_summary
    frame = annual_summary.sort_values("scenario_id")
    x = range(len(frame))
    width = 0.28
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(
        [position - width for position in x],
        frame["annual_revenue_sar"],
        width=width,
        label="Revenue",
    )
    ax.bar(
        list(x),
        frame["total_annual_cost_sar"],
        width=width,
        label="Annual cost",
    )
    ax.bar(
        [position + width for position in x],
        frame["net_annual_benefit_sar"],
        width=width,
        label="Net benefit",
    )
    ax.set_xticks(list(x), frame["scenario_id"])
    ax.set_ylabel("SAR/year")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
