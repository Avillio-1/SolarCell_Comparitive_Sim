from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import cast

import numpy as np
import pandas as pd

from solarclean.config.models import (
    BirdDroppingConfig,
    FarmConfig,
    RainfallCleaningConfig,
    ReactiveCVConfig,
    SoilingConfig,
)
from solarclean.domain.contamination.soiling import ContaminationState, KimberStyleSoilingModel
from solarclean.domain.farm.representation import CohortFarm, CohortState, FarmState
from solarclean.domain.reactive_cv.crew import CleaningCrew
from solarclean.domain.reactive_cv.dispatch import ThresholdDispatchPolicy, to_dispatch_signal
from solarclean.domain.reactive_cv.drone import DroneFleet
from solarclean.domain.reactive_cv.observer import (
    CVObserver,
    PerfectInformationObserver,
    StatisticalCVObserver,
)
from solarclean.domain.reactive_cv.scheduler import InspectionScheduler
from solarclean.domain.reactive_cv.state import ReactiveScenarioState
from solarclean.domain.scenario.contracts import (
    DailyScenarioInput,
    DailyScenarioResult,
    DomainEvent,
    OperationalQuantities,
    ScenarioContext,
    StrategyStep,
)


class ReactiveCVStrategy:
    """T2 scenario: periodic drone/CV inspection plus capacity-limited crew cleaning.

    True contamination and bird-dropping state evolve exactly as they do
    in `BaselineStrategy` (same soiling model, same event tape, same
    per-cohort variation) so comparisons stay fair. The CV/drone/dispatch
    pipeline never reads that true state directly -- it only ever sees
    `CVObservation`/`DispatchSignal` values, and all of its own randomness
    is drawn from an independent `cv_rng` spawned once at
    `initial_state()`, so changing CV/drone/dispatch config can never
    perturb the sequence of draws the shared soiling model consumes.
    """

    def __init__(
        self,
        *,
        reactive: ReactiveCVConfig,
        soiling: SoilingConfig,
        rainfall: RainfallCleaningConfig,
        birds: BirdDroppingConfig,
        farm: FarmConfig,
        perfect_information: bool = False,
        name: str | None = None,
    ) -> None:
        self.reactive = reactive
        self.soiling_model = KimberStyleSoilingModel(soiling, rainfall)
        self.birds = birds
        self.farm_config = farm
        self.farm = CohortFarm(farm, birds)
        self.perfect_information = perfect_information
        self.name = name or (
            "reactive_cv_perfect_information" if perfect_information else "reactive_cv"
        )
        self.scheduler = InspectionScheduler(reactive.inspection, farm.cohort_count)
        self.drone_fleet = DroneFleet(reactive.drone)
        self.observer: CVObserver = (
            PerfectInformationObserver(reactive.inspection)
            if perfect_information
            else StatisticalCVObserver(reactive.observer, reactive.inspection)
        )
        self.dispatch_policy = ThresholdDispatchPolicy(reactive.dispatch)
        self.crew = CleaningCrew(reactive.crew)

    def initial_state(
        self,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> ReactiveScenarioState:
        first_day = pd.Timestamp(str(next(iter(context.clean_energy.daily.index)))).date()
        farm_state = self.farm.initial_state(day=first_day, rng=rng)
        # Independent stream for all CV/drone/dispatch stochasticity. `spawn`
        # does not consume from `rng`'s own draw sequence, so true dust/bird
        # evolution (which uses `rng` directly, matching BaselineStrategy)
        # is completely unaffected by CV-side configuration.
        cv_rng = rng.spawn(1)[0]
        return ReactiveScenarioState(
            date=first_day,
            cohorts=tuple(farm_state.cohorts),
            cv_rng=cv_rng,
            days_since_inspection=MappingProxyType(
                {cohort.cohort_id: 10_000 for cohort in farm_state.cohorts}
            ),
        )

    def simulate_day(
        self,
        day_input: DailyScenarioInput,
        state: object,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> StrategyStep:
        typed_state = _coerce_state(state)
        events: list[DomainEvent] = []

        # 1. Advance TRUE contamination/bird state, identically to baseline.
        previous_average_dust = _average_dust(typed_state.cohorts)
        update = self.soiling_model.update(
            ContaminationState(dust_soiling_ratio=previous_average_dust),
            day_input.environment,
            rng,
            event_inputs=day_input.event_inputs,
        )
        events.extend(
            DomainEvent.from_simulation_event(event, scenario_name=self.name)
            for event in update.events
        )
        farm_state = FarmState(date=day_input.date, cohorts=list(typed_state.cohorts))
        varied = _apply_dust_to_farm(
            farm_state,
            update.state.dust_soiling_ratio,
            self.farm_config.cohort_soiling_variation_fraction,
            rng,
            dict(day_input.event_inputs.cohort_variation_multipliers)
            if day_input.event_inputs is not None
            else None,
        )
        advanced = self.farm.advance_day(
            varied,
            day_input.environment.precipitation_mm,
            rng,
            dict(day_input.event_inputs.bird_coverage_additions)
            if day_input.event_inputs is not None
            else None,
        )
        events.extend(
            DomainEvent.from_simulation_event(event, scenario_name=self.name)
            for event in advanced.events
        )
        true_cohorts = {cohort.cohort_id: cohort for cohort in advanced.state.cohorts}

        # 2. Which cohorts are due for inspection today, and can the drone fly.
        due = self.scheduler.due_cohorts(day_input.day_index).due_cohort_ids
        hourly = _hourly_for_day(context.weather.hourly, day_input.date)
        wind_speed = float(hourly["wind_speed_m_s"].max()) if not hourly.empty else 0.0
        flight_plan = self.drone_fleet.plan_flights(
            due,
            wind_speed_m_s=wind_speed,
            precipitation_mm=day_input.environment.precipitation_mm,
        )

        # 3. CV observations, using ONLY the independent cv_rng.
        observations = [
            self.observer.observe(true_cohorts[cohort_id], typed_state.cv_rng)
            for cohort_id in flight_plan.inspected_cohort_ids
        ]
        signals = tuple(
            signal for obs in observations if (signal := to_dispatch_signal(obs)) is not None
        )

        # 4. Dispatch decides who gets cleaned, blind to true state.
        decision = self.dispatch_policy.select_for_cleaning(
            signals,
            current_queue=typed_state.cleaning_queue,
            current_queue_age_days=typed_state.queue_age_days,
            crew_daily_capacity=self.reactive.crew.daily_capacity_cohorts,
        )

        # 5. Crew cleans selected cohorts, mutating true state.
        crew_hours = 0.0
        water_liters = 0.0
        for cohort_id in decision.to_clean_ids:
            outcome = self.crew.clean(true_cohorts[cohort_id])
            true_cohorts[cohort_id] = outcome.cohort
            crew_hours += outcome.crew_hours
            water_liters += outcome.water_liters
            events.append(
                DomainEvent(
                    date=day_input.date,
                    event_type="reactive_cleaning_action",
                    magnitude=1.0,
                    description="Targeted cohort cleaning dispatched from CV inspection.",
                    scenario_name=self.name,
                    cohort_id=cohort_id,
                )
            )
        for cohort_id in flight_plan.inspected_cohort_ids:
            events.append(
                DomainEvent(
                    date=day_input.date,
                    event_type="reactive_inspection",
                    magnitude=1.0,
                    description="Drone CV inspection of cohort.",
                    scenario_name=self.name,
                    cohort_id=cohort_id,
                )
            )

        next_cohorts = tuple(true_cohorts[cohort.cohort_id] for cohort in advanced.state.cohorts)

        # 6. Energy from updated true state (same formula as baseline/CohortFarm).
        farm_energy = self.farm.calculate_daily_energy(
            FarmState(date=day_input.date, cohorts=list(next_cohorts)),
            day_input.clean_energy_per_panel_kwh,
        )
        actual_energy = min(day_input.clean_energy_kwh, max(0.0, farm_energy.actual_energy_kwh))

        # 7. Confusion-matrix counters for offline detection-performance evaluation
        # (never fed back into dispatch -- see metrics.py).
        tp = fp = fn = tn = missed = 0
        for obs in observations:
            if not obs.image_captured:
                missed += 1
            elif obs._ground_truth_dirty and obs.detected_dirty:
                tp += 1
            elif obs._ground_truth_dirty and not obs.detected_dirty:
                fn += 1
            elif not obs._ground_truth_dirty and obs.detected_dirty:
                fp += 1
            else:
                tn += 1

        next_days_since_inspection = dict(typed_state.days_since_inspection)
        for cohort_id in next_days_since_inspection:
            next_days_since_inspection[cohort_id] += 1
        for cohort_id in flight_plan.inspected_cohort_ids:
            next_days_since_inspection[cohort_id] = 0

        result = DailyScenarioResult(
            date=day_input.date,
            scenario_name=self.name,
            clean_energy_kwh=day_input.clean_energy_kwh,
            actual_energy_kwh=actual_energy,
            operational=OperationalQuantities(
                inspections_count=len(flight_plan.inspected_cohort_ids),
                cleaning_actions_count=len(decision.to_clean_ids),
                crew_hours=crew_hours,
                drone_flight_hours=flight_plan.flight_hours,
                water_liters=water_liters,
                energy_used_kwh=flight_plan.drone_energy_kwh + flight_plan.compute_energy_kwh,
            ),
            events=tuple(events),
            extensions={
                "average_dust_soiling_ratio": _average_dust(next_cohorts),
                "queue_length": len(decision.updated_queue),
                "weather_cancelled_flight": flight_plan.weather_cancelled,
                "flights_flown": flight_plan.flights_flown,
                "inspection_true_positive_count": tp,
                "inspection_false_positive_count": fp,
                "inspection_false_negative_count": fn,
                "inspection_true_negative_count": tn,
                "inspection_missed_image_count": missed,
                "event_tape_checksum": (
                    context.event_tape.checksum() if context.event_tape is not None else ""
                ),
            },
        )
        next_state = ReactiveScenarioState(
            date=day_input.date,
            cohorts=next_cohorts,
            cv_rng=typed_state.cv_rng,
            days_since_inspection=MappingProxyType(next_days_since_inspection),
            cleaning_queue=decision.updated_queue,
            queue_age_days=decision.updated_queue_age_days,
        )
        return StrategyStep(state=next_state, result=result)


def _coerce_state(state: object) -> ReactiveScenarioState:
    if not isinstance(state, ReactiveScenarioState):
        raise TypeError("reactive CV strategy state has the wrong type")
    return state


def _apply_dust_to_farm(
    state: FarmState,
    base_ratio: float,
    variation_fraction: float,
    rng: np.random.Generator,
    cohort_variation_multipliers: dict[int, float] | None = None,
) -> FarmState:
    cohorts = []
    for cohort in state.cohorts:
        ratio = base_ratio
        if cohort_variation_multipliers is not None:
            ratio *= cohort_variation_multipliers.get(cohort.cohort_id, 1.0)
        elif variation_fraction > 0:
            ratio *= float(rng.normal(1.0, variation_fraction))
        cohorts.append(replace(cohort, dust_soiling_ratio=max(0.0, min(1.0, ratio))))
    return FarmState(date=state.date, cohorts=cohorts)


def _average_dust(cohorts: tuple[CohortState, ...]) -> float:
    total = sum(cohort.panel_count for cohort in cohorts)
    return sum(cohort.panel_count * cohort.dust_soiling_ratio for cohort in cohorts) / total


def _hourly_for_day(hourly: pd.DataFrame, day: object) -> pd.DataFrame:
    frame = cast(pd.DataFrame, hourly.loc[pd.DatetimeIndex(hourly.index).date == day])
    return frame
