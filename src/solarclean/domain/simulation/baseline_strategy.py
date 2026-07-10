from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from solarclean.config.models import FarmConfig
from solarclean.domain.contamination.soiling import ContaminationState, KimberStyleSoilingModel
from solarclean.domain.farm.representation import CohortFarm, FarmState, advance_dust_ratio
from solarclean.domain.scenario.contracts import (
    DailyScenarioInput,
    DailyScenarioResult,
    DomainEvent,
    ScenarioContext,
    StrategyStep,
)


@dataclass(frozen=True)
class BaselineStrategyState:
    contamination_state: ContaminationState
    farm_state: FarmState | None


class BaselineStrategy:
    name = "baseline"

    def __init__(
        self,
        soiling_model: KimberStyleSoilingModel,
        farm: CohortFarm | None = None,
        farm_config: FarmConfig | None = None,
        name: str = "baseline",
    ) -> None:
        self.soiling_model = soiling_model
        self.farm = farm
        self.farm_config = farm_config
        self.name = name

    def initial_state(
        self,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> BaselineStrategyState:
        farm_state: FarmState | None = None
        if self.farm is not None:
            first_day = next(iter(context.clean_energy.daily.index))
            farm_state = self.farm.initial_state(
                day=pd.Timestamp(str(first_day)).date(),
                rng=rng,
            )
        return BaselineStrategyState(
            contamination_state=ContaminationState(),
            farm_state=farm_state,
        )

    def simulate_day(
        self,
        day_input: DailyScenarioInput,
        state: object,
        context: ScenarioContext,
        rng: np.random.Generator,
    ) -> StrategyStep:
        del context
        typed_state = _coerce_state(state)
        contamination_state = typed_state.contamination_state
        if typed_state.farm_state is not None:
            contamination_state = replace(
                contamination_state,
                dust_soiling_ratio=typed_state.farm_state.aggregate_dust_soiling_ratio,
            )
        update = self.soiling_model.update(
            contamination_state,
            day_input.environment,
            rng,
            event_inputs=day_input.event_inputs,
        )
        events = [
            DomainEvent.from_simulation_event(event, scenario_name=self.name)
            for event in update.events
        ]
        cohort_count = 1
        cohort_records: tuple[dict[str, object], ...] = ()
        farm_state = typed_state.farm_state
        if self.farm is None:
            actual_energy = day_input.clean_energy_kwh * update.state.dust_soiling_ratio
        else:
            if farm_state is None:
                raise ValueError("baseline cohort farm requires an initialized farm state")
            varied_state = _apply_dust_to_farm(
                FarmState(date=day_input.date, cohorts=list(farm_state.cohorts)),
                daily_loss_fraction=sum(
                    event.magnitude
                    for event in update.events
                    if event.event_type == "dust_accumulation"
                ),
                dust_event_loss_fraction=sum(
                    event.magnitude
                    for event in update.events
                    if event.event_type == "heavy_dust_event"
                ),
                precipitation_mm=day_input.environment.precipitation_mm,
                soiling_model=self.soiling_model,
                variation_fraction=(
                    self.farm_config.cohort_soiling_variation_fraction if self.farm_config else 0.0
                ),
                rng=rng,
                cohort_variation_multipliers=dict(
                    day_input.event_inputs.cohort_variation_multipliers
                )
                if day_input.event_inputs is not None
                else None,
            )
            advanced = self.farm.advance_day(
                varied_state,
                day_input.environment.precipitation_mm,
                rng,
                dict(day_input.event_inputs.bird_coverage_additions)
                if day_input.event_inputs is not None
                else None,
            )
            farm_state = advanced.state
            events.extend(
                DomainEvent.from_simulation_event(event, scenario_name=self.name)
                for event in advanced.events
            )
            farm_energy = self.farm.calculate_daily_energy(
                farm_state,
                day_input.clean_energy_per_panel_kwh,
            )
            actual_energy = min(day_input.clean_energy_kwh, farm_energy.actual_energy_kwh)
            cohort_count = len(farm_state.cohorts)
            cohort_records = tuple(
                {
                    "date": day_input.date.isoformat(),
                    "cohort_id": cohort.cohort_id,
                    "panel_count": cohort.panel_count,
                    "dust_soiling_ratio": cohort.dust_soiling_ratio,
                    "bird_drop_coverage_fraction": cohort.bird_drop_coverage_fraction,
                    "bird_drop_loss_fraction": cohort.bird_drop_loss_fraction,
                    "actual_energy_kwh": day_input.clean_energy_per_panel_kwh
                    * cohort.panel_count
                    * cohort.dust_soiling_ratio
                    * (1.0 - cohort.bird_drop_loss_fraction),
                }
                for cohort in farm_state.cohorts
            )
        actual_energy = min(day_input.clean_energy_kwh, max(0.0, actual_energy))
        result = DailyScenarioResult(
            date=day_input.date,
            scenario_name=self.name,
            clean_energy_kwh=day_input.clean_energy_kwh,
            actual_energy_kwh=actual_energy,
            events=tuple(events),
            extensions={
                "dust_soiling_ratio": update.state.dust_soiling_ratio,
                "precipitation_mm": day_input.environment.precipitation_mm,
                "mean_relative_humidity_pct": day_input.environment.mean_relative_humidity_pct,
                "cohort_count": cohort_count,
                "cohort_records": cohort_records,
            },
        )
        return StrategyStep(
            state=BaselineStrategyState(
                contamination_state=update.state,
                farm_state=farm_state,
            ),
            result=result,
        )


def _coerce_state(state: object) -> BaselineStrategyState:
    if not isinstance(state, BaselineStrategyState):
        raise TypeError("baseline strategy state has the wrong type")
    return state


def _apply_dust_to_farm(
    state: FarmState,
    *,
    daily_loss_fraction: float,
    dust_event_loss_fraction: float,
    precipitation_mm: float,
    soiling_model: KimberStyleSoilingModel,
    variation_fraction: float,
    rng: np.random.Generator,
    cohort_variation_multipliers: dict[int, float] | None = None,
) -> FarmState:
    cohorts = []
    for cohort in state.cohorts:
        if cohort_variation_multipliers is not None:
            variation = cohort_variation_multipliers.get(cohort.cohort_id, 1.0)
        elif variation_fraction > 0:
            variation = max(0.0, float(rng.normal(1.0, variation_fraction)))
        else:
            variation = 1.0
        ratio = advance_dust_ratio(
            cohort.dust_soiling_ratio,
            daily_loss_fraction=daily_loss_fraction,
            dust_event_loss_fraction=dust_event_loss_fraction,
            precipitation_mm=precipitation_mm,
            soiling=soiling_model.config,
            rainfall=soiling_model.rainfall,
            cohort_variation_multiplier=variation,
        )
        cohorts.append(replace(cohort, dust_soiling_ratio=ratio))
    return FarmState(date=state.date, cohorts=cohorts)
