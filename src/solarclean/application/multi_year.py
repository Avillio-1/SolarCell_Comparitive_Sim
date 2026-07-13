"""Multi-year weather robustness experiment for the three-scenario comparison."""

from __future__ import annotations

import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd

from solarclean.application.comparison import (
    CANONICAL_SCENARIO_IDS,
    CompareAllScenarios,
    ComparisonResult,
)
from solarclean.config.models import SolarCleanConfig
from solarclean.infrastructure.persistence.outputs import OutputWriter
from solarclean.infrastructure.persistence.plots import write_multi_year_net_benefit_plot
from solarclean.infrastructure.persistence.reports import write_json_report
from solarclean.infrastructure.weather.nasa_power import WeatherProviderError

ProgressCallback = Callable[[int, int, str], None]

_NUMERIC_METRICS = (
    "annual_clean_energy_kwh",
    "annual_actual_energy_kwh",
    "annual_energy_loss_percent",
    "energy_gain_vs_baseline_percent",
    "net_annual_benefit_sar",
    "incremental_net_annual_benefit_vs_baseline_sar",
)


@dataclass(frozen=True)
class YearResult:
    year: int
    annual_clean_energy_kwh: Mapping[str, float]
    annual_actual_energy_kwh: Mapping[str, float]
    annual_energy_loss_percent: Mapping[str, float]
    energy_gain_vs_baseline_percent: Mapping[str, float]
    net_annual_benefit_sar: Mapping[str, float]
    incremental_net_annual_benefit_vs_baseline_sar: Mapping[str, float]
    winner: str | None
    reconciled: bool

    def to_scenario_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for scenario_id in CANONICAL_SCENARIO_IDS:
            records.append(
                {
                    "year": self.year,
                    "scenario_id": scenario_id,
                    "annual_clean_energy_kwh": self.annual_clean_energy_kwh[scenario_id],
                    "annual_actual_energy_kwh": self.annual_actual_energy_kwh[scenario_id],
                    "annual_energy_loss_percent": self.annual_energy_loss_percent[scenario_id],
                    "energy_gain_vs_baseline_percent": self.energy_gain_vs_baseline_percent[
                        scenario_id
                    ],
                    "net_annual_benefit_sar": self.net_annual_benefit_sar[scenario_id],
                    "incremental_net_annual_benefit_vs_baseline_sar": (
                        self.incremental_net_annual_benefit_vs_baseline_sar[scenario_id]
                    ),
                    "winner": self.winner,
                    "reconciled": self.reconciled,
                }
            )
        return records


@dataclass(frozen=True)
class MultiYearComparisonResult:
    run_id: str
    output_directory: Path
    years_requested: tuple[int, ...]
    year_results: tuple[YearResult, ...]
    failed_years: Mapping[int, str]
    config_checksums_by_year: Mapping[int, str]
    aggregate: Mapping[str, object]
    output_artifacts: tuple[str, ...]


def build_year_config(config: SolarCleanConfig, year: int) -> SolarCleanConfig:
    """Round-trip the base config with the requested Riyadh calendar-year bounds."""

    payload: dict[str, Any] = config.model_dump(mode="python")
    simulation = payload["simulation"]
    if not isinstance(simulation, dict):
        raise TypeError("config simulation payload must be a mapping")
    simulation["start"] = datetime.fromisoformat(f"{year}-01-01T00:00:00+03:00")
    simulation["end"] = datetime.fromisoformat(f"{year}-12-31T23:00:00+03:00")
    return SolarCleanConfig.model_validate(payload)


def aggregate_years(results: Sequence[YearResult]) -> dict[str, object]:
    """Aggregate numeric scenario metrics and annual winners without side effects."""

    scenario_summaries: dict[str, dict[str, float]] = {}
    for scenario_id in CANONICAL_SCENARIO_IDS:
        summary: dict[str, float] = {}
        for metric in _NUMERIC_METRICS:
            values = [getattr(result, metric)[scenario_id] for result in results]
            if not values:
                raise ValueError("aggregate_years requires at least one year result")
            summary[f"mean_{metric}"] = statistics.fmean(values)
            summary[f"std_{metric}"] = statistics.stdev(values) if len(values) > 1 else 0.0
            summary[f"min_{metric}"] = min(values)
            summary[f"max_{metric}"] = max(values)
        scenario_summaries[scenario_id] = summary

    winner_counts = {scenario_id: 0 for scenario_id in CANONICAL_SCENARIO_IDS}
    winner_by_year: dict[int, str | None] = {}
    for result in results:
        winner_by_year[result.year] = result.winner
        if result.winner in winner_counts:
            winner_counts[result.winner] += 1

    return {
        "scenario_summaries": scenario_summaries,
        "winner_counts": winner_counts,
        "winner_by_year": winner_by_year,
    }


def run_multi_year_comparison(
    config: SolarCleanConfig,
    start_year: int,
    end_year: int,
    output_writer_or_path: OutputWriter | Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> MultiYearComparisonResult:
    """Run one artifact-free T6 comparison per year and persist one aggregate package."""

    if end_year < start_year:
        raise ValueError("end_year must be greater than or equal to start_year")
    years = tuple(range(start_year, end_year + 1))
    results: list[YearResult] = []
    failed_years: dict[int, str] = {}
    config_checksums: dict[int, str] = {}

    for index, year in enumerate(years):
        if progress_callback is not None:
            progress_callback(index, len(years), f"Running weather year {year}")
        per_year_config = build_year_config(config, year)
        try:
            comparison = (
                CompareAllScenarios(per_year_config, write_artifacts=False).run().comparison
            )
        except WeatherProviderError as exc:
            failed_years[year] = str(exc)
            continue
        results.append(_extract_year_result(year, comparison))
        config_checksums[year] = comparison.config_checksum

    if progress_callback is not None:
        progress_callback(len(years), len(years), "Multi-year comparisons complete")
    if len(results) < 3:
        failure_detail = "; ".join(
            f"{year}: {message}" for year, message in sorted(failed_years.items())
        )
        suffix = f" Failures: {failure_detail}" if failure_detail else ""
        raise RuntimeError(
            "Multi-year comparison requires at least 3 successful weather years; "
            f"only {len(results)} succeeded.{suffix}"
        )

    aggregate = aggregate_years(results)
    writer = (
        output_writer_or_path
        if isinstance(output_writer_or_path, OutputWriter)
        else OutputWriter(config)
    )
    if isinstance(output_writer_or_path, Path):
        output_dir = output_writer_or_path
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = writer.create_run_directory("compare-multi-year")
    artifacts = _write_multi_year_package(
        output_dir=output_dir,
        writer=writer,
        config=config,
        years_requested=years,
        results=results,
        failed_years=failed_years,
        config_checksums=config_checksums,
        aggregate=aggregate,
    )
    return MultiYearComparisonResult(
        run_id=output_dir.name,
        output_directory=output_dir,
        years_requested=years,
        year_results=tuple(results),
        failed_years=MappingProxyType(dict(failed_years)),
        config_checksums_by_year=MappingProxyType(dict(config_checksums)),
        aggregate=MappingProxyType(aggregate),
        output_artifacts=artifacts,
    )


def _extract_year_result(year: int, comparison: ComparisonResult) -> YearResult:
    scenario_results = comparison.scenario_results
    economic_results = comparison.economic_results
    baseline_net_benefit = economic_results["baseline"].net_annual_benefit_sar

    annual_clean = {
        scenario_id: scenario_results[scenario_id].annual_clean_energy_kwh
        for scenario_id in CANONICAL_SCENARIO_IDS
    }
    annual_actual = {
        scenario_id: scenario_results[scenario_id].annual_actual_energy_kwh
        for scenario_id in CANONICAL_SCENARIO_IDS
    }
    annual_loss = {
        scenario_id: scenario_results[scenario_id].annual_energy_loss_percent
        for scenario_id in CANONICAL_SCENARIO_IDS
    }
    energy_gain = {
        scenario_id: _as_float(
            comparison.energy_gain_vs_baseline[scenario_id]["energy_gain_vs_baseline_percent"]
        )
        for scenario_id in CANONICAL_SCENARIO_IDS
    }
    net_benefit = {
        scenario_id: economic_results[scenario_id].net_annual_benefit_sar
        for scenario_id in CANONICAL_SCENARIO_IDS
    }
    incremental_net_benefit = {
        scenario_id: net_benefit[scenario_id] - baseline_net_benefit
        for scenario_id in CANONICAL_SCENARIO_IDS
    }
    reconciled = (
        comparison.reconciliation_report.passed and comparison.recommendation.calculation_valid
    )
    return YearResult(
        year=year,
        annual_clean_energy_kwh=MappingProxyType(annual_clean),
        annual_actual_energy_kwh=MappingProxyType(annual_actual),
        annual_energy_loss_percent=MappingProxyType(annual_loss),
        energy_gain_vs_baseline_percent=MappingProxyType(energy_gain),
        net_annual_benefit_sar=MappingProxyType(net_benefit),
        incremental_net_annual_benefit_vs_baseline_sar=MappingProxyType(incremental_net_benefit),
        winner=comparison.recommendation.winner if reconciled else None,
        reconciled=reconciled,
    )


def _as_float(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    raise TypeError(f"expected a numeric value, got {type(value).__name__}: {value!r}")


def _write_multi_year_package(
    *,
    output_dir: Path,
    writer: OutputWriter,
    config: SolarCleanConfig,
    years_requested: tuple[int, ...],
    results: Sequence[YearResult],
    failed_years: Mapping[int, str],
    config_checksums: Mapping[int, str],
    aggregate: Mapping[str, object],
) -> tuple[str, ...]:
    artifacts: list[str] = []
    writer.write_config(output_dir)
    artifacts.append("config_resolved.yaml")

    frame = pd.DataFrame.from_records(
        record for result in results for record in result.to_scenario_records()
    )
    frame.to_csv(
        output_dir / "multi_year_scenario_summary.csv",
        index=False,
        float_format=config.output.csv_float_format,
    )
    artifacts.append("multi_year_scenario_summary.csv")

    summary_record: dict[str, object] = {
        **aggregate,
        "metadata": {
            "command": "compare-multi-year",
            "run_id": output_dir.name,
            "years_requested": list(years_requested),
            "years_succeeded": [result.year for result in results],
            "years_failed": {str(year): message for year, message in failed_years.items()},
            "config_checksums_by_year": {
                str(year): checksum for year, checksum in config_checksums.items()
            },
        },
    }
    write_json_report(output_dir / "multi_year_summary.json", summary_record)
    artifacts.append("multi_year_summary.json")

    plot_path = output_dir / "multi_year_net_benefit.png"
    write_multi_year_net_benefit_plot(plot_path, frame)
    artifacts.append(plot_path.name)

    command_summary: dict[str, object] = {
        "command": "compare-multi-year",
        "run_id": output_dir.name,
        "years_requested": list(years_requested),
        "years_succeeded": [result.year for result in results],
        "years_failed": {str(year): message for year, message in failed_years.items()},
        "winner_by_year": aggregate["winner_by_year"],
        "output_artifacts": list(artifacts),
    }
    writer.write_summary(output_dir, command_summary)
    writer.write_text_summary(output_dir, command_summary)
    artifacts.extend(("summary.json", "summary.txt"))
    return tuple(artifacts)
