from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import date, timedelta
from itertools import permutations
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import pytest
from tests.config_factory import fixture_config

from solarclean.application import comparison as comparison_module
from solarclean.config.models import SolarCleanConfig
from solarclean.domain.events.tape import ExogenousEvent, ExogenousEventTape
from solarclean.domain.scenario.contracts import (
    AnnualScenarioResult,
    DailyScenarioInput,
    DailyScenarioResult,
    MitigationStrategy,
    ScenarioContext,
    ScenarioOutputBundle,
    StrategyStep,
)
from solarclean.domain.simulation.scenario_engine import ScenarioSimulationEngine
from solarclean.infrastructure.persistence.outputs import OutputWriter
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider


def _shared_context(random_seed: int = 42) -> tuple[SolarCleanConfig, ScenarioContext]:
    config = fixture_config(overrides={"soiling": {"random_seed": random_seed}})
    weather = FixtureWeatherProvider().load(comparison_module._weather_request(config))
    clean_energy = PVWattsPowerModel().calculate_hourly(weather, config.pv_system)
    event_tape = comparison_module._generate_event_tape(config, clean_energy)
    context = ScenarioContext.from_inputs(
        weather=weather,
        clean_energy=clean_energy,
        event_tape=event_tape,
        farm_config=config.farm,
        metadata={
            "weather_checksum": comparison_module._weather_checksum(weather),
            "event_tape_checksum": event_tape.checksum(),
            "provenance": {"tags": ["shared", "adversarial"]},
        },
    )
    return config, context


def _result_fingerprint(result: AnnualScenarioResult) -> dict[str, object]:
    return {
        "summary": result.summary(),
        "daily": [daily.to_record() for daily in result.daily_results],
        "events": [event.to_record() for event in result.events],
    }


def _input_trace(day_input: DailyScenarioInput, context: ScenarioContext) -> tuple[object, ...]:
    event_inputs = day_input.event_inputs
    hourly = context.weather.for_day(day_input.date)
    return (
        day_input.date,
        day_input.day_index,
        day_input.clean_energy_kwh,
        day_input.clean_energy_per_panel_kwh,
        day_input.environment.precipitation_mm,
        day_input.environment.mean_relative_humidity_pct,
        day_input.environment.max_relative_humidity_pct,
        tuple(hourly.index.astype(str)),
        tuple(hourly.columns),
        tuple(map(tuple, hourly.to_numpy(dtype=float))),
        None
        if event_inputs is None
        else (
            event_inputs.date,
            event_inputs.dust_multiplier,
            event_inputs.dust_event_loss_fraction,
            tuple(sorted(event_inputs.cohort_variation_multipliers.items())),
            tuple(sorted(event_inputs.bird_coverage_additions.items())),
        ),
        context.event_tape.checksum() if context.event_tape is not None else None,
    )


class _RecordingStrategy:
    def __init__(self, delegate: MitigationStrategy) -> None:
        self.delegate = delegate
        self.name = delegate.name
        self.inputs: list[tuple[object, ...]] = []

    def initial_state(self, context: ScenarioContext, rng: np.random.Generator) -> object:
        return self.delegate.initial_state(context, rng)

    def simulate_day(
        self,
        day_input: DailyScenarioInput,
        state: object,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> StrategyStep:
        self.inputs.append(_input_trace(day_input, context))
        return self.delegate.simulate_day(day_input, state, context, rng)


class _BadEchoStrategy:
    name = "bad_echo"

    def __init__(self, mismatch: str) -> None:
        self.mismatch = mismatch

    def initial_state(self, context: ScenarioContext, rng: np.random.Generator) -> None:
        del context, rng

    def simulate_day(
        self,
        day_input: DailyScenarioInput,
        state: object,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> StrategyStep:
        del state, context, rng
        result_date = (
            day_input.date + timedelta(days=1) if self.mismatch == "date" else day_input.date
        )
        scenario_name = "wrong_scenario" if self.mismatch == "scenario_name" else self.name
        clean_energy = (
            day_input.clean_energy_kwh / 2.0
            if self.mismatch == "clean_energy_kwh"
            else day_input.clean_energy_kwh
        )
        return StrategyStep(
            state=None,
            result=DailyScenarioResult(
                date=result_date,
                scenario_name=scenario_name,
                clean_energy_kwh=clean_energy,
                actual_energy_kwh=0.0,
            ),
        )


class _FarmConfigMutatingStrategy:
    name = "farm_config_mutator"

    def initial_state(self, context: ScenarioContext, rng: np.random.Generator) -> None:
        del rng
        assert context.farm_config is not None
        context.farm_config.representation = "representative"
        context.farm_config.total_panels = 1

    def simulate_day(
        self,
        day_input: DailyScenarioInput,
        state: object,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> StrategyStep:
        del state, context, rng
        return StrategyStep(
            state=None,
            result=DailyScenarioResult(
                date=day_input.date,
                scenario_name=self.name,
                clean_energy_kwh=day_input.clean_energy_kwh,
                actual_energy_kwh=0.0,
            ),
        )


class _PanelCountProbeStrategy:
    name = "panel_count_probe"

    def __init__(self) -> None:
        self.clean_energy_per_panel: list[float] = []

    def initial_state(self, context: ScenarioContext, rng: np.random.Generator) -> None:
        del context, rng

    def simulate_day(
        self,
        day_input: DailyScenarioInput,
        state: object,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> StrategyStep:
        del state, context, rng
        self.clean_energy_per_panel.append(day_input.clean_energy_per_panel_kwh)
        return StrategyStep(
            state=None,
            result=DailyScenarioResult(
                date=day_input.date,
                scenario_name=self.name,
                clean_energy_kwh=day_input.clean_energy_kwh,
                actual_energy_kwh=0.0,
            ),
        )


def test_every_scenario_receives_identical_weather_clean_energy_and_event_tape() -> None:
    config, context = _shared_context()
    traces: dict[str, list[tuple[object, ...]]] = {}

    for scenario_id in comparison_module.CANONICAL_SCENARIO_IDS:
        strategy = _RecordingStrategy(comparison_module._build_strategy(scenario_id, config))
        ScenarioSimulationEngine(strategy).run(context, random_seed=config.soiling.random_seed)
        traces[scenario_id] = strategy.inputs

    baseline_trace = traces["baseline"]
    assert baseline_trace
    assert traces["reactive"] == baseline_trace
    assert traces["coating"] == baseline_trace


@pytest.mark.parametrize("mismatch", ["date", "scenario_name", "clean_energy_kwh"])
def test_engine_rejects_strategy_results_that_do_not_echo_shared_daily_inputs(
    mismatch: str,
) -> None:
    _, context = _shared_context()

    with pytest.raises(ValueError, match=mismatch):
        ScenarioSimulationEngine(_BadEchoStrategy(mismatch)).run(context, random_seed=42)


def test_mutating_farm_config_in_one_strategy_cannot_poison_the_next_run() -> None:
    _, context = _shared_context()
    assert context.farm_config is not None
    original_farm = context.farm_config.model_dump(mode="python")

    ScenarioSimulationEngine(_FarmConfigMutatingStrategy()).run(context, random_seed=42)
    probe = _PanelCountProbeStrategy()
    ScenarioSimulationEngine(probe).run(context, random_seed=42)

    assert context.farm_config.model_dump(mode="python") == original_farm
    expected = tuple(
        float(row["clean_ac_energy_kwh"]) / int(original_farm["total_panels"])
        for _, row in context.clean_energy.daily.iterrows()
    )
    assert tuple(probe.clean_energy_per_panel) == expected


def test_all_scenario_execution_orders_are_exactly_independent_and_do_not_mutate_inputs() -> None:
    config, context = _shared_context()
    weather_before = context.weather.hourly
    clean_hourly_before = context.clean_energy.hourly
    clean_daily_before = context.clean_energy.daily
    tape_json_before = context.event_tape.to_json() if context.event_tape is not None else None
    config_before = config.model_dump(mode="python")
    reference: dict[str, dict[str, object]] | None = None

    for raw_order in permutations(comparison_module.CANONICAL_SCENARIO_IDS):
        order = cast(tuple[str, ...], raw_order)
        results = comparison_module._run_scenarios(
            config=config,
            context=context,
            scenario_order=order,
        )
        fingerprints = {
            scenario_id: _result_fingerprint(result) for scenario_id, result in results.items()
        }
        if reference is None:
            reference = fingerprints
        else:
            assert fingerprints == reference

    pd.testing.assert_frame_equal(context.weather.hourly, weather_before, check_exact=True)
    pd.testing.assert_frame_equal(
        context.clean_energy.hourly, clean_hourly_before, check_exact=True
    )
    pd.testing.assert_frame_equal(context.clean_energy.daily, clean_daily_before, check_exact=True)
    assert context.event_tape is not None
    assert context.event_tape.to_json() == tape_json_before
    assert config.model_dump(mode="python") == config_before


@pytest.mark.parametrize("scenario_id", comparison_module.CANONICAL_SCENARIO_IDS)
@pytest.mark.parametrize("seed", [0, 42, 2**32 - 1])
def test_reusing_one_engine_and_strategy_is_fully_deterministic_for_fixed_seed(
    scenario_id: str,
    seed: int,
) -> None:
    config, context = _shared_context(seed)
    engine = ScenarioSimulationEngine(comparison_module._build_strategy(scenario_id, config))

    first = engine.run(context, random_seed=seed)
    second = engine.run(context, random_seed=seed)

    assert _result_fingerprint(second) == _result_fingerprint(first)


def test_daily_energy_and_summary_totals_reconcile_exactly() -> None:
    config, context = _shared_context()
    expected_daily_clean = tuple(
        float(row["clean_ac_energy_kwh"]) for _, row in context.clean_energy.daily.iterrows()
    )
    results = comparison_module._run_scenarios(
        config=config,
        context=context,
        scenario_order=comparison_module.CANONICAL_SCENARIO_IDS,
    )

    for result in results.values():
        daily_clean = tuple(day.clean_energy_kwh for day in result.daily_results)
        daily_actual = tuple(day.actual_energy_kwh for day in result.daily_results)
        summary = result.summary()

        assert daily_clean == expected_daily_clean
        assert result.annual_clean_energy_kwh == sum(daily_clean)
        assert result.annual_actual_energy_kwh == sum(daily_actual)
        assert result.annual_energy_loss_kwh == (
            result.annual_clean_energy_kwh - result.annual_actual_energy_kwh
        )
        assert summary["annual_clean_energy_kwh"] == result.annual_clean_energy_kwh
        assert summary["annual_actual_energy_kwh"] == result.annual_actual_energy_kwh
        assert summary["annual_energy_loss_kwh"] == result.annual_energy_loss_kwh


@pytest.mark.parametrize("seed", [0, 1, 42, 999_999])
def test_canonical_scenario_energy_stays_within_clean_reference_bounds(seed: int) -> None:
    config, context = _shared_context(seed)
    results = comparison_module._run_scenarios(
        config=config,
        context=context,
        scenario_order=comparison_module.CANONICAL_SCENARIO_IDS,
    )

    for result in results.values():
        for daily in result.daily_results:
            assert math.isfinite(daily.clean_energy_kwh)
            assert math.isfinite(daily.actual_energy_kwh)
            assert 0.0 <= daily.actual_energy_kwh <= daily.clean_energy_kwh


def test_nested_shared_input_metadata_is_immutable_but_round_trips_as_plain_containers() -> None:
    _, context = _shared_context()
    coordinates = cast(Mapping[str, object], context.weather.metadata["coordinates"])
    variables = cast(tuple[object, ...], context.weather.metadata["variables"])
    clean_weather = cast(Mapping[str, object], context.clean_energy.metadata["weather_metadata"])
    provenance = cast(Mapping[str, object], context.metadata["provenance"])

    with pytest.raises(TypeError):
        coordinates["latitude"] = 0.0  # type: ignore[index]
    with pytest.raises(AttributeError):
        variables.append("poison")  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        clean_weather["provider"] = "poison"  # type: ignore[index]
    with pytest.raises(AttributeError):
        cast(tuple[object, ...], provenance["tags"]).append("poison")  # type: ignore[attr-defined]

    thawed_weather = context.weather.to_dataset().metadata
    thawed_clean = context.clean_energy.to_profile().metadata
    assert isinstance(thawed_weather["coordinates"], dict)
    assert isinstance(thawed_weather["variables"], list)
    assert isinstance(thawed_clean["weather_metadata"], dict)
    assert isinstance(thawed_clean["weather_metadata"]["variables"], list)


def test_event_tape_and_event_metadata_are_deeply_immutable_and_json_stable() -> None:
    event = ExogenousEvent(
        date=date(2025, 1, 1),
        stream="test",
        event_type="test",
        value=1.0,
        metadata={"audit": {"tags": ["original"]}},  # type: ignore[arg-type]
    )
    tape = ExogenousEventTape(
        seed=123,
        events=(event,),
        metadata={"stream_names": ["test"]},  # type: ignore[arg-type]
    )
    checksum_before = tape.checksum()
    event_audit = cast(Mapping[str, object], tape.events[0].metadata["audit"])

    with pytest.raises(AttributeError):
        cast(tuple[object, ...], tape.metadata["stream_names"]).append("poison")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        cast(tuple[object, ...], event_audit["tags"]).append("poison")  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        event_audit["new"] = "poison"  # type: ignore[index]

    record = tape.to_records()[0]
    assert record["metadata"] == {"audit": {"tags": ["original"]}}
    assert tape.checksum() == checksum_before
    restored = ExogenousEventTape.from_json(tape.to_json())
    assert restored == tape
    assert restored.checksum() == checksum_before


def test_frozen_bundle_summary_persists_nested_values_as_json_containers(
    tmp_path: Path,
) -> None:
    bundle = ScenarioOutputBundle(
        summary={"readiness": {"tags": ["provisional"], "ready": False}},
        daily_frame=pd.DataFrame(),
        events=(),
    )
    writer = OutputWriter(fixture_config(overrides={"output": {"base_directory": tmp_path}}))

    writer.write_scenario_result(tmp_path, bundle)

    persisted = json.loads((tmp_path / "scenario_summary.json").read_text(encoding="utf-8"))
    assert persisted["readiness"] == {"tags": ["provisional"], "ready": False}


@pytest.mark.parametrize(
    ("clean_energy_kwh", "actual_energy_kwh", "allow_above_clean_reference"),
    [
        (math.nan, 1.0, False),
        (math.inf, 1.0, False),
        (-math.inf, 1.0, False),
        (10.0, math.nan, False),
        (10.0, math.inf, True),
        (10.0, -math.inf, False),
    ],
)
def test_daily_results_reject_non_finite_energy_before_it_can_poison_annual_totals(
    clean_energy_kwh: float,
    actual_energy_kwh: float,
    allow_above_clean_reference: bool,
) -> None:
    with pytest.raises(ValueError, match="finite"):
        DailyScenarioResult(
            date=date(2025, 1, 1),
            scenario_name="adversarial",
            clean_energy_kwh=clean_energy_kwh,
            actual_energy_kwh=actual_energy_kwh,
            allow_above_clean_reference=allow_above_clean_reference,
        )
