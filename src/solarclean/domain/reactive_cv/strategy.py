from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from types import MappingProxyType

import numpy as np
import pandas as pd

from solarclean.config.models import (
    BirdDroppingConfig,
    FarmConfig,
    RainfallCleaningConfig,
    ReactiveCVConfig,
    SoilingConfig,
)
from solarclean.domain.contamination.soiling import (
    ContaminationState,
    KimberStyleSoilingModel,
    SimulationEvent,
)
from solarclean.domain.farm.representation import (
    CohortFarm,
    CohortState,
    FarmState,
    advance_dust_ratio,
)
from solarclean.domain.reactive_cv.crew import CleaningCrew
from solarclean.domain.reactive_cv.dispatch import (
    DispatchSignal,
    ThresholdDispatchPolicy,
    to_dispatch_signal,
)
from solarclean.domain.reactive_cv.drone import DroneFleet
from solarclean.domain.reactive_cv.metrics import SEVERITY_BUCKETS, contamination_severity_bucket
from solarclean.domain.reactive_cv.observer import (
    CVObservation,
    CVObserver,
    PerfectInformationObserver,
    StatisticalCVObserver,
)
from solarclean.domain.reactive_cv.scheduler import InspectionScheduler
from solarclean.domain.reactive_cv.state import CleaningQueueCause, ReactiveScenarioState
from solarclean.domain.scenario.contracts import (
    DailyScenarioInput,
    DailyScenarioResult,
    DomainEvent,
    OperationalQuantities,
    ScenarioContext,
    StrategyStep,
)


@dataclass(frozen=True)
class ObservationDiagnostics:
    true_actionable_dirty_ids: frozenset[int]
    true_loss_by_cohort: dict[int, float]
    true_loss_energy_by_cohort: dict[int, float]
    detected_actionable_dirty_ids: frozenset[int]
    signals: tuple[DispatchSignal, ...]
    signals_by_cohort: dict[int, DispatchSignal]
    missed_counts_by_severity: dict[str, int]
    missed_energy_by_severity: dict[str, float]
    detected_energy_by_severity: dict[str, float]


@dataclass(frozen=True)
class CleaningPassResult:
    events: list[DomainEvent]
    true_cohorts: dict[int, CohortState]
    crew_hours: float
    water_liters: float
    recovered_loss_estimated_kwh: float
    dirty_cleaning_count: int
    false_positive_cleaning_count: int


class ReactiveCVStrategy:
    """T2 scenario: periodic drone/CV inspection plus capacity-limited crew cleaning.

    True contamination and bird-dropping state use the same soiling model,
    event tape, and farm contracts as `BaselineStrategy`, while dust remains
    cohort-local after targeted cleaning. The CV/drone/dispatch
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
        self.soiling_config = soiling
        self.rainfall_config = rainfall
        self.soiling_model = KimberStyleSoilingModel(soiling, rainfall)
        self.birds = birds
        self.farm_config = farm
        if farm.representation != "cohort":
            raise ValueError("reactive CV requires farm.representation='cohort'")
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

        # 1. Draw/record the shared daily dust drivers once, then apply them to each
        # cohort from its own prior dust state so targeted cleaning persists.
        previous_average_dust = _average_dust(typed_state.cohorts)
        update = self.soiling_model.update(
            ContaminationState(
                dust_soiling_ratio=previous_average_dust,
                cementation_index=typed_state.cementation_index,
            ),
            day_input.environment,
            rng,
            event_inputs=day_input.event_inputs,
        )
        events.extend(
            DomainEvent.from_simulation_event(event, scenario_name=self.name)
            for event in update.events
        )
        farm_state = FarmState(date=day_input.date, cohorts=list(typed_state.cohorts))
        varied = _advance_dust_for_farm(
            farm_state,
            daily_events=tuple(update.events),
            soiling=self.soiling_config,
            rainfall=self.rainfall_config,
            precipitation_mm=0.0,
            variation_fraction=self.farm_config.cohort_soiling_variation_fraction,
            rng=rng,
            cohort_variation_multipliers=dict(day_input.event_inputs.cohort_variation_multipliers)
            if day_input.event_inputs is not None
            else None,
        )
        advanced = self.farm.advance_day(
            varied,
            0.0,
            rng,
            dict(day_input.event_inputs.bird_coverage_additions)
            if day_input.event_inputs is not None
            else None,
        )
        events.extend(
            DomainEvent.from_simulation_event(event, scenario_name=self.name)
            for event in advanced.events
        )
        energy_cohorts = tuple(advanced.state.cohorts)
        rain_state = self.farm.apply_rain_cleaning(
            advanced.state,
            day_input.environment.precipitation_mm,
            soiling=self.soiling_config,
            rainfall=self.rainfall_config,
            rain_efficiency_multiplier=update.rain_efficiency_multiplier,
        )
        true_cohorts = {cohort.cohort_id: cohort for cohort in rain_state.cohorts}

        # 2. Which cohorts are due for inspection today, and can the drone fly.
        scheduled_due = self.scheduler.due_cohorts(day_input.day_index).due_cohort_ids
        due = _merge_unique(typed_state.inspection_backlog, scheduled_due)
        hourly = context.weather.for_day(day_input.date)
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
        observations_by_cohort = {
            observation.cohort_id: observation for observation in observations
        }
        observation_diagnostics = _diagnose_observations(
            observations=observations,
            true_cohorts=true_cohorts,
            clean_energy_per_panel_kwh=day_input.clean_energy_per_panel_kwh,
            actionable_loss_threshold_fraction=(
                self.reactive.dispatch.estimated_loss_threshold_fraction
            ),
        )
        eligible_cleaning_causes = {
            signal.cohort_id: _cleaning_queue_cause(
                day=day_input.date,
                cohort=true_cohorts[signal.cohort_id],
                clean_energy_per_panel_kwh=day_input.clean_energy_per_panel_kwh,
                estimated_loss_fraction=signal.estimated_loss_fraction,
                confidence=signal.confidence,
                dispatch_threshold_fraction=(
                    self.reactive.dispatch.estimated_loss_threshold_fraction
                ),
            )
            for signal in observation_diagnostics.signals
            if _passes_dispatch_threshold(
                estimated_loss_fraction=signal.estimated_loss_fraction,
                confidence=signal.confidence,
                dispatch_threshold_fraction=self.reactive.dispatch.estimated_loss_threshold_fraction,
                confidence_threshold=self.reactive.dispatch.confidence_threshold,
            )
        }
        # 4. Dispatch decides who gets cleaned, blind to true state.
        decision = self.dispatch_policy.select_for_cleaning(
            observation_diagnostics.signals,
            current_queue=typed_state.cleaning_queue,
            current_queue_age_days=typed_state.queue_age_days,
            crew_daily_capacity=self.reactive.crew.daily_capacity_cohorts,
        )
        current_queue_causes = dict(typed_state.cleaning_queue_causes)
        candidate_cleaning_causes = current_queue_causes | eligible_cleaning_causes
        current_queue_age_by_cohort = dict(
            zip(typed_state.cleaning_queue, typed_state.queue_age_days, strict=True)
        )

        events.extend(
            _inspection_events(
                day=day_input.date,
                inspected_cohort_ids=flight_plan.inspected_cohort_ids,
                observations_by_cohort=observations_by_cohort,
                observation_diagnostics=observation_diagnostics,
                eligible_cleaning_causes=eligible_cleaning_causes,
                true_cohorts=true_cohorts,
                clean_energy_per_panel_kwh=day_input.clean_energy_per_panel_kwh,
                dispatch_threshold_fraction=(
                    self.reactive.dispatch.estimated_loss_threshold_fraction
                ),
                confidence_threshold=self.reactive.dispatch.confidence_threshold,
                scenario_name=self.name,
            )
        )

        # 5. Today's generation uses the pre-clean state. Inspections and crew
        # actions occur after the modeled generation phase and affect tomorrow.
        farm_energy = self.farm.calculate_daily_energy(
            FarmState(date=day_input.date, cohorts=list(energy_cohorts)),
            day_input.clean_energy_per_panel_kwh,
        )
        actual_energy = min(day_input.clean_energy_kwh, max(0.0, farm_energy.actual_energy_kwh))

        # 6. Crew cleans selected cohorts, mutating the next-day true state.
        cleaning_pass = _apply_cleaning_pass(
            day=day_input.date,
            to_clean_ids=decision.to_clean_ids,
            true_cohorts=true_cohorts,
            true_actionable_dirty_ids=observation_diagnostics.true_actionable_dirty_ids,
            candidate_cleaning_causes=candidate_cleaning_causes,
            current_queue_age_by_cohort=current_queue_age_by_cohort,
            clean_energy_per_panel_kwh=day_input.clean_energy_per_panel_kwh,
            dispatch_threshold_fraction=self.reactive.dispatch.estimated_loss_threshold_fraction,
            scenario_name=self.name,
            crew=self.crew,
            dust_efficiency_multiplier=self.soiling_model.rain_efficiency_multiplier(update.state),
        )
        true_cohorts = cleaning_pass.true_cohorts
        events.extend(cleaning_pass.events)

        next_cohorts = tuple(true_cohorts[cohort.cohort_id] for cohort in rain_state.cohorts)

        # 7. Confusion-matrix counters for offline detection-performance evaluation
        # (never fed back into dispatch -- see metrics.py).
        tp, fp, fn, tn, missed = _count_observations(observations)
        actionable_tp, actionable_fp, actionable_fn, actionable_tn, actionable_missed = (
            _count_actionable_observations(
                observations,
                true_actionable_dirty_ids=observation_diagnostics.true_actionable_dirty_ids,
            )
        )

        next_days_since_inspection = dict(typed_state.days_since_inspection)
        for cohort_id in next_days_since_inspection:
            next_days_since_inspection[cohort_id] += 1
        for cohort_id in flight_plan.inspected_cohort_ids:
            next_days_since_inspection[cohort_id] = 0
        inspected_ids = frozenset(flight_plan.inspected_cohort_ids)
        next_inspection_backlog = tuple(
            cohort_id for cohort_id in due if cohort_id not in inspected_ids
        )
        skipped_inspection_count = len(next_inspection_backlog)
        system_missed_dirty_count = len(
            observation_diagnostics.true_actionable_dirty_ids
            - observation_diagnostics.detected_actionable_dirty_ids
        )

        result = DailyScenarioResult(
            date=day_input.date,
            scenario_name=self.name,
            clean_energy_kwh=day_input.clean_energy_kwh,
            actual_energy_kwh=actual_energy,
            operational=OperationalQuantities(
                inspections_count=len(flight_plan.inspected_cohort_ids),
                cleaning_actions_count=len(decision.to_clean_ids),
                crew_hours=cleaning_pass.crew_hours,
                drone_flight_hours=flight_plan.flight_hours,
                water_liters=cleaning_pass.water_liters,
                energy_used_kwh=flight_plan.drone_energy_kwh + flight_plan.compute_energy_kwh,
            ),
            events=tuple(events),
            extensions={
                "average_dust_soiling_ratio": _average_dust(energy_cohorts),
                "next_day_average_dust_soiling_ratio": _average_dust(next_cohorts),
                "queue_length": len(decision.updated_queue),
                "weather_cancelled_flight": flight_plan.weather_cancelled,
                "flights_flown": flight_plan.flights_flown,
                "whole_farm_survey_count": len(flight_plan.inspected_cohort_ids)
                / self.farm_config.cohort_count,
                "block_or_cohort_inspection_count": len(flight_plan.inspected_cohort_ids),
                "cleaning_dispatch_count": len(decision.to_clean_ids),
                "panels_cleaned": len(decision.to_clean_ids) * self.farm_config.panels_per_cohort,
                "scheduled_inspection_count": len(scheduled_due),
                "inspection_due_count": len(due),
                "inspection_skipped_count": skipped_inspection_count,
                "inspection_backlog_length": len(next_inspection_backlog),
                "inspection_true_positive_count": tp,
                "inspection_false_positive_count": fp,
                "inspection_false_negative_count": fn,
                "inspection_true_negative_count": tn,
                "inspection_missed_image_count": missed,
                "actionable_true_positive_count": actionable_tp,
                "actionable_false_positive_count": actionable_fp,
                "actionable_false_negative_count": actionable_fn,
                "actionable_true_negative_count": actionable_tn,
                "actionable_missed_image_count": actionable_missed,
                "system_dirty_cohort_count": len(observation_diagnostics.true_actionable_dirty_ids),
                "system_detected_dirty_count": len(
                    observation_diagnostics.detected_actionable_dirty_ids
                ),
                "system_missed_dirty_count": system_missed_dirty_count,
                "missed_contamination_count": system_missed_dirty_count,
                "missed_contamination_count_by_severity_bucket": (
                    observation_diagnostics.missed_counts_by_severity
                ),
                "missed_contamination_estimated_energy_impact_kwh": sum(
                    observation_diagnostics.missed_energy_by_severity.values()
                ),
                "missed_contamination_estimated_energy_impact_by_severity_bucket": (
                    observation_diagnostics.missed_energy_by_severity
                ),
                "detected_contamination_estimated_energy_impact_kwh": sum(
                    observation_diagnostics.detected_energy_by_severity.values()
                ),
                "detected_contamination_estimated_energy_impact_by_severity_bucket": (
                    observation_diagnostics.detected_energy_by_severity
                ),
                "recovered_loss_estimated_kwh": cleaning_pass.recovered_loss_estimated_kwh,
                "avoided_loss_estimated_kwh": cleaning_pass.recovered_loss_estimated_kwh,
                "diagnostic_energy_impact_basis": (
                    "cohort clean energy times contamination loss fraction; missed impact uses "
                    "audit true-state loss, detected impact uses controller-visible CV estimate"
                ),
                "dirty_cleaning_count": cleaning_pass.dirty_cleaning_count,
                "false_positive_cleaning_count": cleaning_pass.false_positive_cleaning_count,
                "cementation_index": update.state.cementation_index,
                "crew_dust_efficiency_multiplier": (
                    self.soiling_model.rain_efficiency_multiplier(update.state)
                ),
                "event_tape_checksum": str(context.metadata.get("event_tape_checksum", "")),
            },
        )
        next_state = ReactiveScenarioState(
            date=day_input.date,
            cohorts=next_cohorts,
            cv_rng=typed_state.cv_rng,
            cementation_index=update.state.cementation_index,
            days_since_inspection=MappingProxyType(next_days_since_inspection),
            inspection_backlog=next_inspection_backlog,
            cleaning_queue=decision.updated_queue,
            queue_age_days=decision.updated_queue_age_days,
            cleaning_queue_causes=MappingProxyType(
                {
                    cohort_id: candidate_cleaning_causes[cohort_id]
                    for cohort_id in decision.updated_queue
                    if cohort_id in candidate_cleaning_causes
                }
            ),
        )
        return StrategyStep(state=next_state, result=result)


def _coerce_state(state: object) -> ReactiveScenarioState:
    if not isinstance(state, ReactiveScenarioState):
        raise TypeError("reactive CV strategy state has the wrong type")
    return state


def _diagnose_observations(
    *,
    observations: list[CVObservation],
    true_cohorts: dict[int, CohortState],
    clean_energy_per_panel_kwh: float,
    actionable_loss_threshold_fraction: float,
) -> ObservationDiagnostics:
    true_loss_by_cohort = {
        cohort_id: _contamination_loss_fraction(cohort)
        for cohort_id, cohort in true_cohorts.items()
    }
    true_actionable_dirty_ids = frozenset(
        cohort_id
        for cohort_id, loss_fraction in true_loss_by_cohort.items()
        if loss_fraction >= actionable_loss_threshold_fraction
    )
    true_loss_energy_by_cohort = {
        cohort_id: _contamination_loss_kwh(
            cohort,
            clean_energy_per_panel_kwh=clean_energy_per_panel_kwh,
            loss_fraction=true_loss_by_cohort[cohort_id],
        )
        for cohort_id, cohort in true_cohorts.items()
    }
    detected_dirty_ids = frozenset(
        obs.cohort_id
        for obs in observations
        if (
            obs.image_captured and obs.detected_dirty and obs.cohort_id in true_actionable_dirty_ids
        )
    )
    signals = tuple(
        signal for obs in observations if (signal := to_dispatch_signal(obs)) is not None
    )
    missed_counts_by_severity = _empty_bucket_ints()
    missed_energy_by_severity = _empty_bucket_floats()
    for cohort_id in true_actionable_dirty_ids - detected_dirty_ids:
        bucket = contamination_severity_bucket(true_loss_by_cohort[cohort_id])
        missed_counts_by_severity[bucket] += 1
        missed_energy_by_severity[bucket] += true_loss_energy_by_cohort[cohort_id]
    detected_energy_by_severity = _empty_bucket_floats()
    for observation in observations:
        if observation.image_captured and observation.detected_dirty:
            detected_energy_by_severity[
                contamination_severity_bucket(observation.estimated_loss_fraction)
            ] += _estimated_observation_loss_kwh(
                observation,
                true_cohorts[observation.cohort_id],
                clean_energy_per_panel_kwh=clean_energy_per_panel_kwh,
            )
    return ObservationDiagnostics(
        true_actionable_dirty_ids=true_actionable_dirty_ids,
        true_loss_by_cohort=true_loss_by_cohort,
        true_loss_energy_by_cohort=true_loss_energy_by_cohort,
        detected_actionable_dirty_ids=detected_dirty_ids,
        signals=signals,
        signals_by_cohort={signal.cohort_id: signal for signal in signals},
        missed_counts_by_severity=missed_counts_by_severity,
        missed_energy_by_severity=missed_energy_by_severity,
        detected_energy_by_severity=detected_energy_by_severity,
    )


def _inspection_events(
    *,
    day: object,
    inspected_cohort_ids: tuple[int, ...],
    observations_by_cohort: dict[int, CVObservation],
    observation_diagnostics: ObservationDiagnostics,
    eligible_cleaning_causes: dict[int, CleaningQueueCause],
    true_cohorts: dict[int, CohortState],
    clean_energy_per_panel_kwh: float,
    dispatch_threshold_fraction: float,
    confidence_threshold: float,
    scenario_name: str,
) -> list[DomainEvent]:
    events: list[DomainEvent] = []
    for cohort_id in inspected_cohort_ids:
        observation = observations_by_cohort[cohort_id]
        signal = observation_diagnostics.signals_by_cohort.get(cohort_id)
        events.append(
            DomainEvent(
                date=pd.Timestamp(str(day)).date(),
                event_type="reactive_inspection",
                magnitude=1.0,
                description="Drone CV inspection of cohort.",
                scenario_name=scenario_name,
                cohort_id=cohort_id,
                metadata=_inspection_event_metadata(
                    day=day,
                    observation=observation,
                    cohort=true_cohorts[cohort_id],
                    clean_energy_per_panel_kwh=clean_energy_per_panel_kwh,
                    signal_created=signal is not None,
                    dispatch_threshold_passed=cohort_id in eligible_cleaning_causes,
                    dispatch_threshold_fraction=dispatch_threshold_fraction,
                    confidence_threshold=confidence_threshold,
                ),
            )
        )
    return events


def _apply_cleaning_pass(
    *,
    day: object,
    to_clean_ids: tuple[int, ...],
    true_cohorts: dict[int, CohortState],
    true_actionable_dirty_ids: frozenset[int],
    candidate_cleaning_causes: dict[int, CleaningQueueCause],
    current_queue_age_by_cohort: dict[int, int],
    clean_energy_per_panel_kwh: float,
    dispatch_threshold_fraction: float,
    scenario_name: str,
    crew: CleaningCrew,
    dust_efficiency_multiplier: float = 1.0,
) -> CleaningPassResult:
    cleaned_true_cohorts = dict(true_cohorts)
    events: list[DomainEvent] = []
    crew_hours = 0.0
    water_liters = 0.0
    recovered_loss_estimated_kwh = 0.0
    cleaned_ids = frozenset(to_clean_ids)
    for cohort_id in to_clean_ids:
        cause = candidate_cleaning_causes.get(
            cohort_id,
            _fallback_cleaning_cause(
                day=day,
                cohort=cleaned_true_cohorts[cohort_id],
                clean_energy_per_panel_kwh=clean_energy_per_panel_kwh,
                dispatch_threshold_fraction=dispatch_threshold_fraction,
            ),
        )
        pre_clean = cleaned_true_cohorts[cohort_id]
        outcome = crew.clean(
            pre_clean,
            dust_efficiency_multiplier=dust_efficiency_multiplier,
        )
        cleaned_true_cohorts[cohort_id] = outcome.cohort
        crew_hours += outcome.crew_hours
        water_liters += outcome.water_liters
        cleaned_loss_kwh = _cleaned_loss_kwh(
            pre_clean,
            outcome.cohort,
            clean_energy_per_panel_kwh=clean_energy_per_panel_kwh,
        )
        recovered_loss_estimated_kwh += cleaned_loss_kwh
        dispatch_id = _dispatch_id(day, cohort_id)
        events.extend(
            _cleaning_events(
                day=day,
                cohort_id=cohort_id,
                cause=cause,
                dispatch_id=dispatch_id,
                pre_clean=pre_clean,
                post_clean=outcome.cohort,
                cleaned_loss_kwh=cleaned_loss_kwh,
                crew_hours=outcome.crew_hours,
                water_liters=outcome.water_liters,
                effective_dust_removal_efficiency=(outcome.effective_dust_removal_efficiency),
                queue_age_days=current_queue_age_by_cohort.get(cohort_id, 0),
                false_positive_cleaning=cohort_id not in true_actionable_dirty_ids,
                scenario_name=scenario_name,
            )
        )
    return CleaningPassResult(
        events=events,
        true_cohorts=cleaned_true_cohorts,
        crew_hours=crew_hours,
        water_liters=water_liters,
        recovered_loss_estimated_kwh=recovered_loss_estimated_kwh,
        dirty_cleaning_count=len(cleaned_ids & true_actionable_dirty_ids),
        false_positive_cleaning_count=len(cleaned_ids - true_actionable_dirty_ids),
    )


def _cleaned_loss_kwh(
    pre_clean: CohortState,
    post_clean: CohortState,
    *,
    clean_energy_per_panel_kwh: float,
) -> float:
    return max(
        0.0,
        _contamination_loss_kwh(
            pre_clean,
            clean_energy_per_panel_kwh=clean_energy_per_panel_kwh,
        )
        - _contamination_loss_kwh(
            post_clean,
            clean_energy_per_panel_kwh=clean_energy_per_panel_kwh,
        ),
    )


def _cleaning_events(
    *,
    day: object,
    cohort_id: int,
    cause: CleaningQueueCause,
    dispatch_id: str,
    pre_clean: CohortState,
    post_clean: CohortState,
    cleaned_loss_kwh: float,
    crew_hours: float,
    water_liters: float,
    effective_dust_removal_efficiency: float,
    queue_age_days: int,
    false_positive_cleaning: bool,
    scenario_name: str,
) -> list[DomainEvent]:
    event_day = pd.Timestamp(str(day)).date()
    return [
        DomainEvent(
            date=event_day,
            event_type="reactive_cleaning_dispatch",
            magnitude=1.0,
            description="Reactive cleaning dispatch decision for cohort.",
            scenario_name=scenario_name,
            cohort_id=cohort_id,
            metadata=_dispatch_event_metadata(
                dispatch_id=dispatch_id,
                cause=cause,
                queue_age_days=queue_age_days,
            ),
            effective_for_energy_date=event_day + timedelta(days=1),
        ),
        DomainEvent(
            date=event_day,
            event_type="reactive_cleaning_action",
            magnitude=1.0,
            description="Targeted cohort cleaning dispatched from CV inspection.",
            scenario_name=scenario_name,
            cohort_id=cohort_id,
            metadata=_cleaning_event_metadata(
                cause=cause,
                dispatch_id=dispatch_id,
                pre_clean=pre_clean,
                post_clean=post_clean,
                cleaned_loss_kwh=cleaned_loss_kwh,
                crew_hours=crew_hours,
                water_liters=water_liters,
                effective_dust_removal_efficiency=effective_dust_removal_efficiency,
                false_positive_cleaning=false_positive_cleaning,
            ),
            effective_for_energy_date=event_day + timedelta(days=1),
        ),
    ]


def _inspection_id(day: object, cohort_id: int) -> str:
    return f"inspection-{pd.Timestamp(str(day)).date().isoformat()}-cohort-{cohort_id}"


def _dispatch_id(day: object, cohort_id: int) -> str:
    return f"dispatch-{pd.Timestamp(str(day)).date().isoformat()}-cohort-{cohort_id}"


def _contamination_loss_fraction(cohort: CohortState) -> float:
    dust_ratio = max(0.0, min(1.0, cohort.dust_soiling_ratio))
    bird_retained_ratio = 1.0 - max(0.0, min(1.0, cohort.bird_drop_loss_fraction))
    return max(0.0, min(1.0, 1.0 - dust_ratio * bird_retained_ratio))


def _contamination_loss_kwh(
    cohort: CohortState,
    *,
    clean_energy_per_panel_kwh: float,
    loss_fraction: float | None = None,
) -> float:
    bounded_loss = (
        _contamination_loss_fraction(cohort)
        if loss_fraction is None
        else max(0.0, min(1.0, loss_fraction))
    )
    return max(0.0, bounded_loss) * clean_energy_per_panel_kwh * cohort.panel_count


def _estimated_observation_loss_kwh(
    observation: CVObservation,
    cohort: CohortState,
    *,
    clean_energy_per_panel_kwh: float,
) -> float:
    bounded_loss = max(0.0, min(1.0, observation.estimated_loss_fraction))
    return bounded_loss * clean_energy_per_panel_kwh * cohort.panel_count


def _cleaning_queue_cause(
    *,
    day: object,
    cohort: CohortState,
    clean_energy_per_panel_kwh: float,
    estimated_loss_fraction: float,
    confidence: float,
    dispatch_threshold_fraction: float,
) -> CleaningQueueCause:
    return CleaningQueueCause(
        cohort_id=cohort.cohort_id,
        inspection_id=_inspection_id(day, cohort.cohort_id),
        inspection_date=pd.Timestamp(str(day)).date(),
        estimated_loss_fraction=estimated_loss_fraction,
        estimated_loss_kwh=max(0.0, estimated_loss_fraction)
        * clean_energy_per_panel_kwh
        * cohort.panel_count,
        confidence=confidence,
        dispatch_threshold_fraction=dispatch_threshold_fraction,
        dispatch_threshold_kwh=dispatch_threshold_fraction
        * clean_energy_per_panel_kwh
        * cohort.panel_count,
    )


def _fallback_cleaning_cause(
    *,
    day: object,
    cohort: CohortState,
    clean_energy_per_panel_kwh: float,
    dispatch_threshold_fraction: float,
) -> CleaningQueueCause:
    true_loss_fraction = _contamination_loss_fraction(cohort)
    return _cleaning_queue_cause(
        day=day,
        cohort=cohort,
        clean_energy_per_panel_kwh=clean_energy_per_panel_kwh,
        estimated_loss_fraction=true_loss_fraction,
        confidence=0.0,
        dispatch_threshold_fraction=dispatch_threshold_fraction,
    )


def _passes_dispatch_threshold(
    *,
    estimated_loss_fraction: float,
    confidence: float,
    dispatch_threshold_fraction: float,
    confidence_threshold: float,
) -> bool:
    return (
        estimated_loss_fraction >= dispatch_threshold_fraction
        and confidence >= confidence_threshold
    )


def _inspection_event_metadata(
    *,
    day: object,
    observation: CVObservation,
    cohort: CohortState,
    clean_energy_per_panel_kwh: float,
    signal_created: bool,
    dispatch_threshold_passed: bool,
    dispatch_threshold_fraction: float,
    confidence_threshold: float,
) -> dict[str, object]:
    estimated_loss_kwh = _estimated_observation_loss_kwh(
        observation,
        cohort,
        clean_energy_per_panel_kwh=clean_energy_per_panel_kwh,
    )
    true_loss_fraction = _contamination_loss_fraction(cohort)
    true_loss_kwh = _contamination_loss_kwh(
        cohort,
        clean_energy_per_panel_kwh=clean_energy_per_panel_kwh,
        loss_fraction=true_loss_fraction,
    )
    dispatch_threshold_kwh = (
        dispatch_threshold_fraction * clean_energy_per_panel_kwh * cohort.panel_count
    )
    true_actionable_dirty = true_loss_fraction >= dispatch_threshold_fraction
    return {
        "inspection_id": _inspection_id(day, observation.cohort_id),
        "cohort_id": observation.cohort_id,
        "estimated_loss_fraction": observation.estimated_loss_fraction,
        "estimated_loss_kwh": estimated_loss_kwh,
        "cv_confidence": observation.confidence,
        "detected_dirty": observation.detected_dirty,
        "missed_image": not observation.image_captured,
        "controller_visible_decision_inputs": {
            "image_captured": observation.image_captured,
            "detected_dirty": observation.detected_dirty,
            "estimated_loss_fraction": observation.estimated_loss_fraction,
            "estimated_loss_kwh": estimated_loss_kwh,
            "confidence": observation.confidence,
            "dispatch_signal_created": signal_created,
            "dispatch_threshold_passed": dispatch_threshold_passed,
            "dispatch_threshold_fraction": dispatch_threshold_fraction,
            "dispatch_threshold_kwh": dispatch_threshold_kwh,
            "confidence_threshold": confidence_threshold,
        },
        "audit": {
            "true_dirty": true_actionable_dirty,
            "true_contaminated": true_loss_fraction > 0.0,
            "true_actionable_dirty": true_actionable_dirty,
            "true_observer_dirty": observation._ground_truth_dirty,
            "true_dirty_threshold_fraction": dispatch_threshold_fraction,
            "true_dirty_threshold_kwh": dispatch_threshold_kwh,
            "true_contamination_loss_fraction": true_loss_fraction,
            "true_contamination_loss_kwh": true_loss_kwh,
            "true_dust_soiling_ratio": cohort.dust_soiling_ratio,
            "true_bird_drop_coverage_fraction": cohort.bird_drop_coverage_fraction,
            "true_bird_drop_loss_fraction": cohort.bird_drop_loss_fraction,
        },
    }


def _dispatch_event_metadata(
    *,
    dispatch_id: str,
    cause: CleaningQueueCause,
    queue_age_days: int,
) -> dict[str, object]:
    return {
        "dispatch_id": dispatch_id,
        "triggering_inspection_id": cause.inspection_id,
        "triggering_inspection_date": cause.inspection_date.isoformat(),
        "cohort_id": cause.cohort_id,
        "estimated_loss_fraction": cause.estimated_loss_fraction,
        "estimated_loss_kwh": cause.estimated_loss_kwh,
        "dispatch_threshold_fraction": cause.dispatch_threshold_fraction,
        "dispatch_threshold_kwh": cause.dispatch_threshold_kwh,
        "cv_confidence": cause.confidence,
        "queue_age_days": queue_age_days,
        "controller_visible_decision_inputs": {
            "estimated_loss_fraction": cause.estimated_loss_fraction,
            "estimated_loss_kwh": cause.estimated_loss_kwh,
            "confidence": cause.confidence,
            "dispatch_threshold_fraction": cause.dispatch_threshold_fraction,
            "dispatch_threshold_kwh": cause.dispatch_threshold_kwh,
        },
    }


def _cleaning_event_metadata(
    *,
    cause: CleaningQueueCause,
    dispatch_id: str,
    pre_clean: CohortState,
    post_clean: CohortState,
    cleaned_loss_kwh: float,
    crew_hours: float,
    water_liters: float,
    effective_dust_removal_efficiency: float,
    false_positive_cleaning: bool,
) -> dict[str, object]:
    return {
        "triggering_inspection_id": cause.inspection_id,
        "dispatch_id": dispatch_id,
        "estimated_loss_fraction": cause.estimated_loss_fraction,
        "estimated_loss_kwh": cause.estimated_loss_kwh,
        "dispatch_threshold_fraction": cause.dispatch_threshold_fraction,
        "dispatch_threshold_kwh": cause.dispatch_threshold_kwh,
        "cv_confidence": cause.confidence,
        "pre_clean_dust_state": pre_clean.dust_soiling_ratio,
        "pre_clean_bird_state": {
            "coverage_fraction": pre_clean.bird_drop_coverage_fraction,
            "loss_fraction": pre_clean.bird_drop_loss_fraction,
        },
        "dust_removed": max(0.0, post_clean.dust_soiling_ratio - pre_clean.dust_soiling_ratio),
        "bird_removed": max(
            0.0,
            pre_clean.bird_drop_coverage_fraction - post_clean.bird_drop_coverage_fraction,
        ),
        "post_clean_dust_state": post_clean.dust_soiling_ratio,
        "post_clean_bird_state": {
            "coverage_fraction": post_clean.bird_drop_coverage_fraction,
            "loss_fraction": post_clean.bird_drop_loss_fraction,
        },
        "crew_minutes": crew_hours * 60.0,
        "crew_hours": crew_hours,
        "water_liters": water_liters,
        "effective_dust_removal_efficiency": effective_dust_removal_efficiency,
        "recovered_loss_estimated_kwh": cleaned_loss_kwh,
        "avoided_loss_estimated_kwh": cleaned_loss_kwh,
        "audit": {
            "false_positive_cleaning": false_positive_cleaning,
            "pre_clean_contamination_loss_fraction": _contamination_loss_fraction(pre_clean),
            "post_clean_contamination_loss_fraction": _contamination_loss_fraction(post_clean),
        },
    }


def _empty_bucket_ints() -> dict[str, int]:
    return {bucket: 0 for bucket in SEVERITY_BUCKETS}


def _empty_bucket_floats() -> dict[str, float]:
    return {bucket: 0.0 for bucket in SEVERITY_BUCKETS}


def _advance_dust_for_farm(
    state: FarmState,
    *,
    daily_events: tuple[SimulationEvent, ...],
    soiling: SoilingConfig,
    rainfall: RainfallCleaningConfig,
    precipitation_mm: float,
    variation_fraction: float,
    rng: np.random.Generator,
    cohort_variation_multipliers: dict[int, float] | None = None,
) -> FarmState:
    daily_loss = sum(
        event.magnitude
        for event in daily_events
        if event.event_type in ("dust_accumulation", "dew_cementation_adhesion")
    )
    dust_event_loss = sum(
        event.magnitude for event in daily_events if event.event_type == "heavy_dust_event"
    )
    cohorts: list[CohortState] = []
    for cohort in state.cohorts:
        if cohort_variation_multipliers is not None:
            variation = cohort_variation_multipliers.get(cohort.cohort_id, 1.0)
        elif variation_fraction > 0:
            variation = max(0.0, float(rng.normal(1.0, variation_fraction)))
        else:
            variation = 1.0
        ratio = advance_dust_ratio(
            cohort.dust_soiling_ratio,
            daily_loss_fraction=daily_loss,
            dust_event_loss_fraction=dust_event_loss,
            precipitation_mm=precipitation_mm,
            soiling=soiling,
            rainfall=rainfall,
            cohort_variation_multiplier=variation,
        )
        cohorts.append(replace(cohort, dust_soiling_ratio=ratio))
    return FarmState(date=state.date, cohorts=cohorts)


def _average_dust(cohorts: tuple[CohortState, ...]) -> float:
    total = sum(cohort.panel_count for cohort in cohorts)
    return sum(cohort.panel_count * cohort.dust_soiling_ratio for cohort in cohorts) / total


def _merge_unique(*groups: tuple[int, ...]) -> tuple[int, ...]:
    seen: set[int] = set()
    merged: list[int] = []
    for group in groups:
        for cohort_id in group:
            if cohort_id not in seen:
                merged.append(cohort_id)
                seen.add(cohort_id)
    return tuple(merged)


def _count_observations(observations: list[CVObservation]) -> tuple[int, int, int, int, int]:
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
    return tp, fp, fn, tn, missed


def _count_actionable_observations(
    observations: list[CVObservation],
    *,
    true_actionable_dirty_ids: frozenset[int],
) -> tuple[int, int, int, int, int]:
    tp = fp = fn = tn = missed = 0
    for obs in observations:
        true_actionable_dirty = obs.cohort_id in true_actionable_dirty_ids
        if not obs.image_captured:
            missed += 1
        elif true_actionable_dirty and obs.detected_dirty:
            tp += 1
        elif true_actionable_dirty and not obs.detected_dirty:
            fn += 1
        elif not true_actionable_dirty and obs.detected_dirty:
            fp += 1
        else:
            tn += 1
    return tp, fp, fn, tn, missed
