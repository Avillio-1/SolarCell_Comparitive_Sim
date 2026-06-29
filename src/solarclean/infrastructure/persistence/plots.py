from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

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
