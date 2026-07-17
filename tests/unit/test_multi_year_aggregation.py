from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from tests.config_factory import fixture_config

from solarclean.application.multi_year import YearResult, aggregate_years, build_year_config
from solarclean.config.models import SolarCleanConfig

SCENARIOS = ("baseline", "reactive", "coating")


def _values(base: float) -> dict[str, float]:
    return {scenario: base + index for index, scenario in enumerate(SCENARIOS)}


def _year_result(year: int, base: float, winner: str) -> YearResult:
    return YearResult(
        year=year,
        annual_clean_energy_kwh=_values(base),
        annual_actual_energy_kwh=_values(base + 10.0),
        annual_energy_loss_percent=_values(base + 20.0),
        energy_gain_vs_baseline_percent=_values(base + 30.0),
        net_annual_benefit_sar=_values(base + 40.0),
        incremental_net_annual_benefit_vs_baseline_sar=_values(base + 50.0),
        winner=winner,
        reconciled=True,
    )


def test_aggregate_years_computes_metric_statistics_and_winners() -> None:
    results = (
        _year_result(2019, 1.0, "reactive"),
        _year_result(2020, 4.0, "coating"),
        _year_result(2021, 7.0, "reactive"),
    )

    aggregate = aggregate_years(results)

    summaries = aggregate["scenario_summaries"]
    assert isinstance(summaries, dict)
    for scenario_index, scenario_id in enumerate(SCENARIOS):
        scenario_summary = summaries[scenario_id]
        assert isinstance(scenario_summary, dict)
        for offset, metric in (
            (0.0, "annual_clean_energy_kwh"),
            (10.0, "annual_actual_energy_kwh"),
            (20.0, "annual_energy_loss_percent"),
            (30.0, "energy_gain_vs_baseline_percent"),
            (40.0, "net_annual_benefit_sar"),
            (50.0, "incremental_net_annual_benefit_vs_baseline_sar"),
        ):
            values = [
                1.0 + offset + scenario_index,
                4.0 + offset + scenario_index,
                7.0 + offset + scenario_index,
            ]
            assert scenario_summary[f"mean_{metric}"] == statistics.fmean(values)
            assert scenario_summary[f"std_{metric}"] == statistics.stdev(values)
            assert scenario_summary[f"min_{metric}"] == min(values)
            assert scenario_summary[f"max_{metric}"] == max(values)
    assert aggregate["winner_counts"] == {"baseline": 0, "reactive": 2, "coating": 1}
    assert aggregate["winner_by_year"] == {
        2019: "reactive",
        2020: "coating",
        2021: "reactive",
    }


@pytest.mark.parametrize("year", [2019, 2020])
def test_build_year_config_uses_full_riyadh_calendar_year(year: int) -> None:
    config = build_year_config(fixture_config(), year)

    assert config.simulation.start.isoformat() == f"{year}-01-01T00:00:00+03:00"
    assert config.simulation.end.isoformat() == f"{year}-12-31T23:00:00+03:00"
    assert config.simulation.start.utcoffset() == timedelta(hours=3)
    assert config.simulation.end.utcoffset() == timedelta(hours=3)


def test_build_year_config_uses_non_saudi_site_timezone() -> None:
    payload = fixture_config().model_dump(mode="python")
    timezone = ZoneInfo("Europe/Berlin")
    payload["simulation"].update(
        {
            "start": datetime(2025, 1, 1, tzinfo=timezone),
            "end": datetime(2025, 1, 2, 23, tzinfo=timezone),
            "target_timezone": "Europe/Berlin",
        }
    )
    payload["site"]["timezone"] = "Europe/Berlin"
    source = SolarCleanConfig.model_validate(payload)

    config = build_year_config(source, 2024)

    assert config.simulation.start.isoformat() == "2024-01-01T00:00:00+01:00"
    assert config.simulation.end.isoformat() == "2024-12-31T23:00:00+01:00"
    assert getattr(config.simulation.start.tzinfo, "key", None) == "Europe/Berlin"
