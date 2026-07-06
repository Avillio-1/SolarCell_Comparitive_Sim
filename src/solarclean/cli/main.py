from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from solarclean.application.comparison import CompareAllScenarios
from solarclean.application.phase35 import Phase35Validator, validate_weather_dataset
from solarclean.application.use_cases import (
    FetchWeather,
    RunBaselineSimulation,
    RunCleanPVSimulation,
    RunCoatingSimulation,
    RunReactiveSimulation,
    _weather_provider,
    _weather_request,
)
from solarclean.config.loader import load_config
from solarclean.infrastructure.persistence.outputs import OutputWriter
from solarclean.infrastructure.persistence.reports import write_json_report

app = typer.Typer(help="SolarClean-DT Phase 1-3 command line tools.")
ConfigPath = Annotated[Path, typer.Option("--config", "-c", exists=True, readable=True)]


@app.command("fetch-weather")
def fetch_weather(config: ConfigPath) -> None:
    result = FetchWeather(load_config(config)).run()
    typer.echo(f"Weather written to {result.output_directory}")


@app.command("run-clean")
def run_clean(config: ConfigPath) -> None:
    result = RunCleanPVSimulation(load_config(config)).run()
    typer.echo(f"Clean PV run written to {result.output_directory}")


@app.command("run-baseline")
def run_baseline(config: ConfigPath) -> None:
    result = RunBaselineSimulation(load_config(config)).run()
    typer.echo(f"Baseline run written to {result.output_directory}")


@app.command("run-coating")
def run_coating(config: ConfigPath) -> None:
    result = RunCoatingSimulation(load_config(config)).run()
    typer.echo(f"Coating scenario run written to {result.output_directory}")


@app.command("run-reactive")
def run_reactive(config: ConfigPath) -> None:
    result = RunReactiveSimulation(load_config(config)).run()
    typer.echo(f"Reactive CV scenario run written to {result.output_directory}")


@app.command("compare-all-scenarios")
def compare_all_scenarios(config: ConfigPath) -> None:
    result = CompareAllScenarios(load_config(config)).run()
    typer.echo(f"Scenario comparison written to {result.output_directory}")


@app.command("validate-weather")
def validate_weather(config: ConfigPath) -> None:
    loaded = load_config(config)
    request = _weather_request(loaded)
    weather = _weather_provider(loaded).load(request)
    writer = OutputWriter(loaded)
    output_dir = writer.create_run_directory("validate-weather")
    writer.write_config(output_dir)
    writer.write_weather(output_dir, weather)
    report = validate_weather_dataset(
        weather,
        expected_start=loaded.simulation.start,
        expected_end=loaded.simulation.end,
    )
    write_json_report(output_dir / "phase35_weather_report.json", report.to_dict())
    typer.echo(f"Weather validation written to {output_dir}")


@app.command("validate-phase-3-5")
def validate_phase_3_5(config: ConfigPath) -> None:
    result = Phase35Validator(load_config(config)).run()
    typer.echo(f"Phase 3.5 validation written to {result.output_directory}")


@app.command("profile-full-year")
def profile_full_year(config: ConfigPath) -> None:
    result = Phase35Validator(load_config(config)).run()
    typer.echo(f"Full-year profile written to {result.output_directory}")


if __name__ == "__main__":
    app()
