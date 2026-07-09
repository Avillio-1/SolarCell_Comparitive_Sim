from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from solarclean.application.comparison import CompareAllScenarios
from solarclean.application.monte_carlo import DEFAULT_TRIAL_COUNT, MonteCarloExperiment
from solarclean.application.phase35 import Phase35Validator, validate_weather_dataset
from solarclean.application.sensitivity import (
    DEFAULT_GRID_STEPS,
    DEFAULT_MAX_BREAKEVEN_EVALUATIONS,
    DEFAULT_ONE_WAY_STEPS,
    BreakEvenExperiment,
    OneWaySensitivityExperiment,
    TwoWaySensitivityExperiment,
)
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


@app.command("monte-carlo")
def monte_carlo(
    config: ConfigPath,
    trials: Annotated[int, typer.Option("--trials", "-n")] = DEFAULT_TRIAL_COUNT,
    base_seed: Annotated[int | None, typer.Option("--base-seed")] = None,
) -> None:
    """Repeat compare-all-scenarios across many seeded trials to quantify stochastic uncertainty."""
    outcome = MonteCarloExperiment(
        load_config(config), trial_count=trials, base_seed=base_seed
    ).run()
    result = outcome.result
    typer.echo(
        f"Monte Carlo ({result.reconciled_trial_count}/{result.trial_count} reconciled) "
        f"written to {result.output_directory}"
    )
    typer.echo(f"Central winner across trials: {result.central_winner}")


@app.command("sensitivity-oneway")
def sensitivity_oneway(
    config: ConfigPath,
    parameters: Annotated[
        list[str] | None,
        typer.Option(
            "--parameter",
            "-p",
            help="Registry parameter name to sweep (repeatable). Default: all T7-supported "
            "parameters.",
        ),
    ] = None,
    steps: Annotated[int, typer.Option("--steps")] = DEFAULT_ONE_WAY_STEPS,
) -> None:
    """Sweep each calibration parameter one at a time and report which ones can flip the
    recommended scenario."""
    outcome = OneWaySensitivityExperiment(
        load_config(config), parameter_names=parameters, steps=steps
    ).run()
    result = outcome.result
    flips = [r.spec.name for r in result.parameter_results if r.winner_changed]
    typer.echo(f"One-way sensitivity written to {result.output_directory}")
    typer.echo(f"Base winner: {result.base_winner}")
    typer.echo(f"Parameters that flip the winner: {flips or 'none'}")


@app.command("sensitivity-winner-map")
def sensitivity_winner_map(
    config: ConfigPath,
    parameter_a: Annotated[str, typer.Option("--parameter-a")],
    parameter_b: Annotated[str, typer.Option("--parameter-b")],
    grid_steps: Annotated[int, typer.Option("--grid-steps")] = DEFAULT_GRID_STEPS,
) -> None:
    """Grid two calibration parameters together and map which scenario wins across their
    joint range."""
    outcome = TwoWaySensitivityExperiment(
        load_config(config),
        parameter_name_a=parameter_a,
        parameter_name_b=parameter_b,
        grid_steps=grid_steps,
    ).run()
    typer.echo(f"Winner map written to {outcome.result.output_directory}")


@app.command("break-even")
def break_even(
    config: ConfigPath,
    parameter: Annotated[str, typer.Option("--parameter")],
    scenario_a: Annotated[str, typer.Option("--scenario-a")] = "coating",
    scenario_b: Annotated[str, typer.Option("--scenario-b")] = "baseline",
    max_evaluations: Annotated[
        int, typer.Option("--max-evaluations")
    ] = DEFAULT_MAX_BREAKEVEN_EVALUATIONS,
) -> None:
    """Find the parameter value at which scenario_a and scenario_b tie on net annual benefit."""
    outcome = BreakEvenExperiment(
        load_config(config),
        parameter_name=parameter,
        scenario_a=scenario_a,
        scenario_b=scenario_b,
        max_evaluations=max_evaluations,
    ).run()
    typer.echo(f"Break-even analysis written to {outcome.result.output_directory}")
    typer.echo(outcome.result.message)


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
