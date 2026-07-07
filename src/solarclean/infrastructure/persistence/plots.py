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
        output_dir / "comparison_normalized_performance.png",
        output_dir / "comparison_daily_loss_percent.png",
        output_dir / "comparison_cumulative_energy.png",
        output_dir / "comparison_cumulative_loss.png",
        output_dir / "comparison_soiling_cleanliness.png",
        output_dir / "comparison_coating_diagnostics.png",
        output_dir / "comparison_annual_kpi_breakdown.png",
    )
    _write_daily_energy_plot(paths[0], daily_summary)
    _write_normalized_performance_plot(paths[1], daily_summary)
    _write_daily_loss_percent_plot(paths[2], daily_summary)
    _write_cumulative_energy_plot(paths[3], daily_summary)
    _write_cumulative_loss_plot(paths[4], daily_summary)
    _write_soiling_cleanliness_plot(paths[5], daily_summary)
    _write_coating_diagnostics_plot(paths[6], daily_summary)
    _write_annual_kpi_plot(paths[7], annual_summary, cost_summary)
    return paths


def write_coating_diagnostic_plots(
    *,
    output_dir: Path,
    coating_daily: pd.DataFrame,
    baseline_daily: pd.DataFrame,
) -> tuple[Path, ...]:
    """Write coating-focused diagnostic plots for a standalone coating run."""

    coating = coating_daily.copy()
    coating["scenario_id"] = "coating"
    baseline = baseline_daily.reset_index().copy()
    baseline["scenario_id"] = "baseline"
    baseline = baseline.rename(columns={"index": "date"})
    common = pd.concat(
        [
            baseline.loc[:, ["date", "scenario_id", "clean_energy_kwh", "actual_energy_kwh"]],
            coating.loc[:, ["date", "scenario_id", "clean_energy_kwh", "actual_energy_kwh"]],
        ],
        ignore_index=True,
    )
    paths = (
        output_dir / "coating_daily_energy.png",
        output_dir / "coating_normalized_performance.png",
        output_dir / "coating_daily_loss_percent.png",
        output_dir / "coating_cumulative_loss.png",
        output_dir / "coating_contamination_diagnostics.png",
    )
    _write_daily_energy_plot(paths[0], common)
    _write_normalized_performance_plot(paths[1], common)
    _write_daily_loss_percent_plot(paths[2], common)
    _write_cumulative_loss_plot(paths[3], common)
    _write_coating_contamination_plot(paths[4], coating, baseline_daily)
    return paths


def _write_daily_energy_plot(path: Path, daily_summary: pd.DataFrame) -> None:
    frame = _daily_frame(daily_summary)
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
    frame = _daily_frame(daily_summary)
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


def _write_normalized_performance_plot(path: Path, daily_summary: pd.DataFrame) -> None:
    frame = _daily_frame(daily_summary)
    fig, ax = plt.subplots(figsize=(10, 5))
    for scenario_id, group in frame.groupby("scenario_id", sort=True):
        ordered = group.sort_values("date")
        ax.plot(
            ordered["date"],
            _safe_ratio(ordered["actual_energy_kwh"], ordered["clean_energy_kwh"]),
            label=str(scenario_id),
        )
    ax.axhline(1.0, color="black", linewidth=0.8, alpha=0.45)
    ax.set_ylabel("Actual / clean")
    ax.set_xlabel("Date")
    ax.set_ylim(bottom=0)
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _write_daily_loss_percent_plot(path: Path, daily_summary: pd.DataFrame) -> None:
    frame = _daily_frame(daily_summary)
    fig, ax = plt.subplots(figsize=(10, 5))
    for scenario_id, group in frame.groupby("scenario_id", sort=True):
        ordered = group.sort_values("date")
        loss_pct = (
            1.0 - _safe_ratio(ordered["actual_energy_kwh"], ordered["clean_energy_kwh"])
        ) * 100.0
        ax.plot(ordered["date"], loss_pct, label=str(scenario_id))
    ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.45)
    ax.set_ylabel("Daily loss %")
    ax.set_xlabel("Date")
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _write_cumulative_loss_plot(path: Path, daily_summary: pd.DataFrame) -> None:
    frame = _daily_frame(daily_summary)
    fig, ax = plt.subplots(figsize=(10, 5))
    for scenario_id, group in frame.groupby("scenario_id", sort=True):
        ordered = group.sort_values("date")
        daily_loss = ordered["clean_energy_kwh"] - ordered["actual_energy_kwh"]
        ax.plot(ordered["date"], daily_loss.cumsum(), label=str(scenario_id))
    ax.set_ylabel("Cumulative loss kWh")
    ax.set_xlabel("Date")
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _write_soiling_cleanliness_plot(path: Path, daily_summary: pd.DataFrame) -> None:
    frame = _daily_frame(daily_summary)
    fig, ax = plt.subplots(figsize=(10, 5))
    for scenario_id, group in frame.groupby("scenario_id", sort=True):
        ordered = group.sort_values("date")
        series = _cleanliness_series(ordered)
        if series is not None:
            ax.plot(ordered["date"], series, label=str(scenario_id))
    ax.set_ylabel("Dust / cleanliness ratio")
    ax.set_xlabel("Date")
    ax.set_ylim(0, 1.05)
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _write_coating_diagnostics_plot(path: Path, daily_summary: pd.DataFrame) -> None:
    frame = _daily_frame(daily_summary)
    coating = frame.loc[frame["scenario_id"] == "coating"].sort_values("date")
    _write_coating_contamination_plot(path, coating, None)


def _write_coating_contamination_plot(
    path: Path,
    coating_daily: pd.DataFrame,
    baseline_daily: pd.DataFrame | None,
) -> None:
    coating = _daily_frame(coating_daily)
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    if baseline_daily is not None:
        baseline = baseline_daily.reset_index().rename(columns={"index": "date"})
        baseline["date"] = pd.to_datetime(baseline["date"])
        if "dust_soiling_ratio" in baseline:
            axes[0].plot(
                baseline["date"],
                pd.to_numeric(baseline["dust_soiling_ratio"], errors="coerce"),
                label="baseline dust",
                color="tab:red",
                alpha=0.8,
            )
    if "extension_average_dust_soiling_ratio" in coating:
        axes[0].plot(
            coating["date"],
            pd.to_numeric(coating["extension_average_dust_soiling_ratio"], errors="coerce"),
            label="coating dust",
            color="tab:green",
        )
    if "extension_cleanliness_ratio" in coating:
        axes[0].plot(
            coating["date"],
            pd.to_numeric(coating["extension_cleanliness_ratio"], errors="coerce"),
            label="coating cleanliness",
            color="tab:blue",
            alpha=0.8,
        )
    if "extension_retained_dust_fraction" in coating:
        axes[1].plot(
            coating["date"],
            pd.to_numeric(coating["extension_retained_dust_fraction"], errors="coerce") * 100.0,
            label="retained dust",
            color="tab:brown",
        )
    if "extension_average_bird_loss_fraction" in coating:
        axes[1].plot(
            coating["date"],
            pd.to_numeric(coating["extension_average_bird_loss_fraction"], errors="coerce") * 100.0,
            label="bird loss",
            color="tab:purple",
        )
    dew = _bool_series(coating, "extension_condensation_dew_eligible")
    passive = _bool_series(coating, "extension_passive_cleaning_day")
    bird = _bool_series(coating, "extension_bird_removal_day")
    axes[2].bar(
        coating["date"], dew.astype(int), label="dew eligible", color="tab:cyan", alpha=0.45
    )
    axes[2].bar(
        coating["date"],
        passive.astype(int),
        label="passive cleaning",
        color="tab:green",
        alpha=0.45,
    )
    axes[2].bar(
        coating["date"],
        -bird.astype(int),
        label="bird removal",
        color="tab:purple",
        alpha=0.45,
    )
    axes[0].set_ylabel("Ratio")
    axes[0].set_ylim(0, 1.05)
    axes[0].legend()
    axes[1].set_ylabel("Loss / retained %")
    axes[1].legend()
    axes[2].set_ylabel("Daily flags")
    axes[2].set_xlabel("Date")
    axes[2].legend()
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


def _daily_frame(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = frame.copy()
    prepared["date"] = pd.to_datetime(prepared["date"])
    for column in ("clean_energy_kwh", "actual_energy_kwh"):
        if column in prepared:
            prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    return prepared


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    ratio = numerator / denominator.where(denominator > 0)
    return ratio.fillna(1.0)


def _cleanliness_series(frame: pd.DataFrame) -> pd.Series | None:
    if "extension_cleanliness_ratio" in frame:
        return pd.to_numeric(frame["extension_cleanliness_ratio"], errors="coerce")
    if "extension_dust_soiling_ratio" in frame:
        return pd.to_numeric(frame["extension_dust_soiling_ratio"], errors="coerce")
    if "soiling_ratio" in frame:
        return pd.to_numeric(frame["soiling_ratio"], errors="coerce")
    return None


def _bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series([False] * len(frame), index=frame.index)
    values = frame[column]
    if values.dtype == bool:
        return values
    return values.astype(str).str.lower().isin({"true", "1", "yes"})
