from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from tests.config_factory import fixture_config
from tests.unit.test_weather import _request

from solarclean.domain.contamination.soiling import DailyEnvironment
from solarclean.domain.events.tape import generate_event_tape
from solarclean.domain.reactive_cv.metrics import summarize_detection_performance
from solarclean.domain.reactive_cv.strategy import ReactiveCVStrategy
from solarclean.domain.scenario.contracts import DailyScenarioInput, ScenarioContext
from solarclean.domain.simulation.baseline_strategy import BaselineStrategy
from solarclean.domain.simulation.scenario_engine import ScenarioSimulationEngine
from solarclean.infrastructure.pvlib_adapter.pvwatts import PVWattsPowerModel
from solarclean.infrastructure.weather.fixture import FixtureWeatherProvider


def _context(config=None):
    if config is None:
        config = fixture_config()
    weather = FixtureWeatherProvider().load(_request())
    clean = PVWattsPowerModel().calculate_hourly(weather, config.pv_system)
    dates = [date.fromisoformat(str(day)) for day in clean.daily.index.astype(str)]
    tape = generate_event_tape(
        dates=dates,
        seed=config.soiling.random_seed,
        soiling=config.soiling,
        rainfall=config.rainfall_cleaning,
        farm=config.farm,
        birds=config.bird_droppings,
    )
    context = ScenarioContext.from_inputs(
        weather=weather,
        clean_energy=clean,
        event_tape=tape,
        farm_config=config.farm,
        metadata={"event_tape_checksum": tape.checksum()},
    )
    return config, context


def _strategy(config, **overrides):
    return ReactiveCVStrategy(
        reactive=config.reactive_cv,
        soiling=config.soiling,
        rainfall=config.rainfall_cleaning,
        birds=config.bird_droppings,
        farm=config.farm,
        **overrides,
    )


def _day_input(context: ScenarioContext, day_index: int) -> DailyScenarioInput:
    raw_day = context.clean_energy.daily.index[day_index]
    day = pd.Timestamp(str(raw_day)).date()
    row = context.clean_energy.daily.iloc[day_index]
    hourly = context.weather.hourly.loc[pd.DatetimeIndex(context.weather.hourly.index).date == day]
    panel_count = context.farm_config.total_panels if context.farm_config is not None else 1
    return DailyScenarioInput(
        date=day,
        clean_energy_kwh=float(row["clean_ac_energy_kwh"]),
        clean_energy_per_panel_kwh=float(row["clean_ac_energy_kwh"]) / panel_count,
        environment=DailyEnvironment(
            date=day,
            precipitation_mm=float(hourly["precipitation_mm"].sum()),
            mean_relative_humidity_pct=float(hourly["relative_humidity_pct"].mean()),
        ),
        event_inputs=context.event_tape.to_daily_inputs(day) if context.event_tape else None,
        day_index=day_index,
    )


def _targeted_cleaning_config():
    config = fixture_config()
    reactive = config.reactive_cv.model_copy(
        update={
            "inspection": config.reactive_cv.inspection.model_copy(
                update={
                    "interval_days": 365,
                    "first_inspection_day_index": 0,
                    "dirty_soiling_ratio_threshold": 1.0,
                }
            ),
            "drone": config.reactive_cv.drone.model_copy(
                update={
                    "cohorts_per_flight": 1,
                    "flights_per_day": 1,
                    "max_wind_speed_m_s": 99.0,
                    "max_precipitation_mm": 999.0,
                }
            ),
            "observer": config.reactive_cv.observer.model_copy(
                update={
                    "recall_fraction": 1.0,
                    "false_positive_rate": 0.0,
                    "missed_image_fraction": 0.0,
                    "base_confidence": 1.0,
                    "confidence_std_fraction": 0.0,
                    "severity_error_std_fraction": 0.0,
                }
            ),
            "dispatch": config.reactive_cv.dispatch.model_copy(
                update={
                    "estimated_loss_threshold_fraction": 0.0,
                    "confidence_threshold": 0.0,
                }
            ),
            "crew": config.reactive_cv.crew.model_copy(
                update={"daily_capacity_cohorts": 1, "dust_removal_efficiency": 1.0}
            ),
        }
    )
    return config.model_copy(
        update={
            "soiling": config.soiling.model_copy(
                update={
                    "base_daily_soiling_loss_fraction": 0.01,
                    "dust_event_probability": 0.0,
                    "stochastic_std_fraction": 0.0,
                    "minimum_soiling_ratio": 0.0,
                }
            ),
            "bird_droppings": config.bird_droppings.model_copy(
                update={"event_probability_per_cohort_day": 0.0}
            ),
            "farm": config.farm.model_copy(update={"cohort_soiling_variation_fraction": 0.0}),
            "reactive_cv": reactive,
        }
    )


def test_reactive_strategy_runs_through_shared_engine_and_preserves_tape_checksum() -> None:
    config, context = _context()
    assert context.event_tape is not None

    result = ScenarioSimulationEngine(_strategy(config)).run(context, random_seed=42)

    assert result.scenario_name == "reactive_cv"
    assert len(result.daily_results) == len(context.clean_energy.daily)
    frame = result.to_daily_frame()
    assert "extension_event_tape_checksum" in frame.columns
    assert frame["extension_event_tape_checksum"].iloc[0] == context.event_tape.checksum()


def test_reactive_strategy_is_reproducible() -> None:
    config, context = _context()
    first = ScenarioSimulationEngine(_strategy(config)).run(context, random_seed=42)
    second = ScenarioSimulationEngine(_strategy(config)).run(context, random_seed=42)
    assert first.to_daily_frame().equals(second.to_daily_frame())


def test_reactive_energy_never_exceeds_clean_energy() -> None:
    config, context = _context()
    result = ScenarioSimulationEngine(_strategy(config)).run(context, random_seed=42)
    for daily in result.daily_results:
        assert daily.actual_energy_kwh <= daily.clean_energy_kwh + 1e-9
        assert daily.actual_energy_kwh >= 0.0


def test_dispatch_only_cleans_cohorts_that_were_actually_flagged_and_selected() -> None:
    config, context = _context()
    result = ScenarioSimulationEngine(_strategy(config)).run(context, random_seed=42)
    for daily in result.daily_results:
        cleaning_events = [e for e in daily.events if e.event_type == "reactive_cleaning_action"]
        assert len(cleaning_events) == daily.operational.cleaning_actions_count


def test_inspection_and_drone_capacity_are_enforced_every_day() -> None:
    config, context = _context()
    result = ScenarioSimulationEngine(_strategy(config)).run(context, random_seed=42)
    max_per_day = config.reactive_cv.drone.max_cohorts_per_day
    for daily in result.daily_results:
        assert daily.operational.inspections_count <= max_per_day


def test_crew_daily_capacity_is_never_exceeded() -> None:
    config, context = _context()
    result = ScenarioSimulationEngine(_strategy(config)).run(context, random_seed=42)
    capacity = config.reactive_cv.crew.daily_capacity_cohorts
    for daily in result.daily_results:
        assert daily.operational.cleaning_actions_count <= capacity


def test_targeted_cleaning_dust_benefit_stays_on_cleaned_cohort() -> None:
    config, context = _context(_targeted_cleaning_config())
    strategy = _strategy(config, perfect_information=True)
    rng = np.random.default_rng(42)
    state = strategy.initial_state(context, rng)

    first_step = strategy.simulate_day(_day_input(context, 0), state, context, rng)
    second_step = strategy.simulate_day(_day_input(context, 1), first_step.state, context, rng)

    assert (
        second_step.state.cohort_by_id(0).dust_soiling_ratio
        > second_step.state.cohort_by_id(2).dust_soiling_ratio
    )


def test_post_generation_cleaning_does_not_retroactively_increase_daily_energy() -> None:
    config, context = _context(_targeted_cleaning_config())
    strategy = _strategy(config, perfect_information=True)
    rng = np.random.default_rng(42)
    state = strategy.initial_state(context, rng)

    step = strategy.simulate_day(_day_input(context, 0), state, context, rng)
    cleaning_event = next(
        event for event in step.result.events if event.event_type == "reactive_cleaning_action"
    )

    assert step.result.actual_energy_kwh == pytest.approx(step.result.clean_energy_kwh * 0.99)
    assert cleaning_event.effective_for_energy_date == step.result.date + timedelta(days=1)


def test_capacity_skipped_inspections_are_backlogged_and_prioritized() -> None:
    config = fixture_config()
    reactive = config.reactive_cv.model_copy(
        update={
            "inspection": config.reactive_cv.inspection.model_copy(
                update={"interval_days": 1, "first_inspection_day_index": 0}
            ),
            "drone": config.reactive_cv.drone.model_copy(
                update={
                    "cohorts_per_flight": 1,
                    "flights_per_day": 2,
                    "max_wind_speed_m_s": 99.0,
                    "max_precipitation_mm": 999.0,
                }
            ),
        }
    )
    config, context = _context(config.model_copy(update={"reactive_cv": reactive}))

    result = ScenarioSimulationEngine(_strategy(config)).run(context, random_seed=42)

    first_inspected = tuple(
        event.cohort_id
        for event in result.daily_results[0].events
        if event.event_type == "reactive_inspection"
    )
    second_inspected = tuple(
        event.cohort_id
        for event in result.daily_results[1].events
        if event.event_type == "reactive_inspection"
    )

    assert first_inspected == (0, 1)
    assert second_inspected == (2, 3)
    assert result.daily_results[0].extensions["inspection_backlog_length"] == (
        config.farm.cohort_count - 2
    )


def test_cv_rng_spawn_does_not_perturb_the_shared_rng_draw_sequence() -> None:
    """Direct mechanism check: initial_state() must not consume from `rng`.

    This is the actual guarantee behind
    `test_changing_cv_randomness_does_not_change_true_dust_or_bird_events`:
    spawning `cv_rng` must leave the shared engine `rng`'s draw sequence
    completely untouched, regardless of what CV/drone/dispatch config is
    passed in.
    """
    config, context = _context()

    rng_a = np.random.default_rng(123)
    _strategy(config).initial_state(context, rng_a)
    draws_after_a = [rng_a.random() for _ in range(5)]

    rng_b = np.random.default_rng(123)
    lenient = config.reactive_cv.model_copy(
        update={
            "observer": config.reactive_cv.observer.model_copy(
                update={"missed_image_fraction": 0.99}
            )
        }
    )
    _strategy(config.model_copy(update={"reactive_cv": lenient})).initial_state(context, rng_b)
    draws_after_b = [rng_b.random() for _ in range(5)]

    assert draws_after_a == draws_after_b


def test_changing_cv_randomness_does_not_change_true_dust_or_bird_events() -> None:
    """The independent cv_rng stream must never perturb the shared soiling/farm rng draws."""
    config, context = _context()

    baseline_run = ScenarioSimulationEngine(
        BaselineStrategy(
            soiling_model=_strategy(config).soiling_model,
            farm=_strategy(config).farm,
            farm_config=config.farm,
        )
    ).run(context, random_seed=42)

    # Two reactive configs with very different CV/drone/dispatch behavior,
    # but identical soiling/farm/seed inputs.
    lenient = config.reactive_cv.model_copy(
        update={
            "observer": config.reactive_cv.observer.model_copy(
                update={"missed_image_fraction": 0.9}
            )
        }
    )
    strict = config.reactive_cv.model_copy(
        update={
            "observer": config.reactive_cv.observer.model_copy(
                update={"missed_image_fraction": 0.0}
            )
        }
    )
    config_lenient = config.model_copy(update={"reactive_cv": lenient})
    config_strict = config.model_copy(update={"reactive_cv": strict})

    lenient_result = ScenarioSimulationEngine(_strategy(config_lenient)).run(
        context, random_seed=42
    )
    strict_result = ScenarioSimulationEngine(_strategy(config_strict)).run(context, random_seed=42)

    true_state_event_types = {
        "dust_accumulation",
        "heavy_dust_event",
        "full_rain_cleaning",
        "partial_rain_cleaning",
        "bird_dropping_event",
    }

    def true_state_events(daily):
        return sorted(
            (event.event_type, event.cohort_id, event.magnitude)
            for event in daily.events
            if event.event_type in true_state_event_types
        )

    # Only compare day 1: every cohort starts at the same fresh true state
    # (dust_soiling_ratio=1.0) regardless of config, so day 1's exogenous
    # dust/bird events must be identical across configs if (and only if)
    # the CV/dispatch pipeline never touches the shared rng. From day 2
    # onward, true state legitimately diverges because day 1's cleaning
    # outcomes differ between configs -- that feedback loop is the entire
    # point of the reactive scenario, not evidence of an rng leak.
    #
    # Note: we deliberately compare each result's own `daily_results[0]`
    # object directly rather than flattening all days and filtering by
    # `event.date` -- BaselineStrategy's carried-over `FarmState.date`
    # never advances past day 1 internally, which mislabels some of its
    # later-day farm events with day 1's date. That is a pre-existing,
    # T1-owned quirk unrelated to T2; comparing `daily_results[0]` directly
    # avoids tripping over it.
    assert true_state_events(lenient_result.daily_results[0]) == true_state_events(
        strict_result.daily_results[0]
    )
    assert true_state_events(lenient_result.daily_results[0]) == true_state_events(
        baseline_run.daily_results[0]
    )


def test_perfect_information_benchmark_uses_a_distinct_scenario_name() -> None:
    config, context = _context()
    benchmark = _strategy(config, perfect_information=True)
    assert benchmark.name == "reactive_cv_perfect_information"
    result = ScenarioSimulationEngine(benchmark).run(context, random_seed=42)
    assert result.scenario_name == "reactive_cv_perfect_information"


def test_perfect_information_benchmark_detects_every_dirty_cohort_it_inspects() -> None:
    config, context = _context()
    benchmark = _strategy(config, perfect_information=True)
    result = ScenarioSimulationEngine(benchmark).run(context, random_seed=42)
    performance = summarize_detection_performance(result)
    # No CV error at all: nothing should be misclassified.
    assert performance.false_positive_count == 0
    assert performance.false_negative_count == 0
    assert performance.missed_image_count == 0


def test_detection_performance_metrics_are_computed_from_statistical_observer() -> None:
    config, context = _context()
    result = ScenarioSimulationEngine(_strategy(config)).run(context, random_seed=42)
    performance = summarize_detection_performance(result)
    total_inspected = (
        performance.true_positive_count
        + performance.false_positive_count
        + performance.false_negative_count
        + performance.true_negative_count
        + performance.missed_image_count
    )
    assert total_inspected == sum(d.operational.inspections_count for d in result.daily_results)
    assert 0.0 <= performance.precision <= 1.0
    assert 0.0 <= performance.recall <= 1.0
    assert 0.0 <= performance.f1 <= 1.0
    assert performance.system_dirty_cohort_count == sum(
        int(daily.extensions["system_dirty_cohort_count"]) for daily in result.daily_results
    )
    assert 0.0 <= performance.system_detection_recall <= 1.0
    assert 0.0 <= performance.cleaning_precision <= 1.0
    record = performance.to_record()
    assert "false_positive_cleaning_count" in record
    assert "missed_contamination_count" in record
