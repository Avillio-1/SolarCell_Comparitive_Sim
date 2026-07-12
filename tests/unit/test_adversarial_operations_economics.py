from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from solarclean.application.comparison import (
    _annual_operational_quantities,
    _reactive_cost_rules,
)
from solarclean.config.models import ReactiveCrewConfig
from solarclean.domain.economics import (
    CostComponent,
    EconomicConfig,
    EconomicEngine,
    ReactiveCostRates,
    ScenarioEconomicInputs,
    UnitCostRate,
    all_reconciled,
    build_reactive_cost_components,
    reconcile_operational_costs,
)
from solarclean.domain.farm.representation import CohortState
from solarclean.domain.reactive_cv.crew import CleaningCrew
from solarclean.domain.reactive_cv.strategy import _apply_cleaning_pass
from solarclean.domain.scenario.contracts import (
    AnnualScenarioResult,
    DailyScenarioResult,
    OperationalQuantities,
)


def _rated_reactive_operations() -> ReactiveCostRates:
    return ReactiveCostRates(
        inspection=UnitCostRate(1.25, "inspection", "adversarial test", "test"),
        cleaning_action=UnitCostRate(2.5, "cleaning", "adversarial test", "test"),
        crew_hour=UnitCostRate(31.75, "hour", "adversarial test", "test"),
        drone_flight_hour=UnitCostRate(19.5, "flight hour", "adversarial test", "test"),
        water_liter=UnitCostRate(0.007, "liter", "adversarial test", "test"),
        energy_kwh=UnitCostRate(0.23, "kWh", "adversarial test", "test"),
    )


def _cohorts() -> dict[int, CohortState]:
    return {
        cohort_id: CohortState(
            cohort_id=cohort_id,
            panel_count=10 + cohort_id,
            dust_soiling_ratio=0.45 + cohort_id * 0.06,
            bird_drop_coverage_fraction=0.10 + cohort_id * 0.01,
            bird_drop_loss_fraction=0.08 + cohort_id * 0.005,
            days_since_effective_rain=cohort_id + 2,
            days_since_manual_cleaning=cohort_id + 7,
            zone_id=f"zone-{cohort_id}",
            metadata={"sentinel": [cohort_id]},
        )
        for cohort_id in range(5)
    }


def test_cleaning_pass_changes_exactly_selected_cohorts_for_every_subset() -> None:
    """Exhaust all 2**5 cohort selections, including none and the full farm."""
    crew_config = ReactiveCrewConfig(
        daily_capacity_cohorts=5,
        setup_minutes_per_cohort=13.0,
        cleaning_minutes_per_cohort=29.0,
        water_liters_per_cohort=17.5,
        dust_removal_efficiency=0.75,
        bird_removal_efficiency=0.60,
    )
    crew = CleaningCrew(crew_config)
    clean_energy_per_panel_kwh = 2.25
    actionable_ids = frozenset({0, 2, 4})

    for selection_mask in range(1 << 5):
        input_cohorts = _cohorts()
        input_snapshot = deepcopy(input_cohorts)
        selected_ids = tuple(
            cohort_id for cohort_id in input_cohorts if selection_mask & (1 << cohort_id)
        )

        outcome = _apply_cleaning_pass(
            day=date(2025, 1, 7),
            to_clean_ids=selected_ids,
            true_cohorts=input_cohorts,
            true_actionable_dirty_ids=actionable_ids,
            candidate_cleaning_causes={},
            current_queue_age_by_cohort={},
            clean_energy_per_panel_kwh=clean_energy_per_panel_kwh,
            dispatch_threshold_fraction=0.04,
            scenario_name="reactive_cv",
            crew=crew,
        )

        # The helper must return a new mapping and leave its caller-owned state untouched.
        assert input_cohorts == input_snapshot
        assert outcome.true_cohorts is not input_cohorts
        assert outcome.true_cohorts.keys() == input_cohorts.keys()

        expected_recovered_kwh = 0.0
        for cohort_id, before in input_snapshot.items():
            after = outcome.true_cohorts[cohort_id]
            if cohort_id not in selected_ids:
                assert after is input_cohorts[cohort_id]
                assert after == before
                continue

            assert after is not input_cohorts[cohort_id]
            assert after.cohort_id == before.cohort_id
            assert after.panel_count == before.panel_count
            assert after.zone_id == before.zone_id
            assert after.metadata == before.metadata
            assert after.days_since_effective_rain == before.days_since_effective_rain
            assert after.days_since_manual_cleaning == 0
            assert after.dust_soiling_ratio == pytest.approx(
                before.dust_soiling_ratio
                + (1.0 - before.dust_soiling_ratio) * crew_config.dust_removal_efficiency
            )
            assert after.bird_drop_coverage_fraction == pytest.approx(
                before.bird_drop_coverage_fraction * (1.0 - crew_config.bird_removal_efficiency)
            )
            assert after.bird_drop_loss_fraction == pytest.approx(
                before.bird_drop_loss_fraction * (1.0 - crew_config.bird_removal_efficiency)
            )

            before_energy = (
                clean_energy_per_panel_kwh
                * before.panel_count
                * before.dust_soiling_ratio
                * (1.0 - before.bird_drop_loss_fraction)
            )
            after_energy = (
                clean_energy_per_panel_kwh
                * after.panel_count
                * after.dust_soiling_ratio
                * (1.0 - after.bird_drop_loss_fraction)
            )
            expected_recovered_kwh += after_energy - before_energy

        action_ids = tuple(
            event.cohort_id
            for event in outcome.events
            if event.event_type == "reactive_cleaning_action"
        )
        dispatch_ids = tuple(
            event.cohort_id
            for event in outcome.events
            if event.event_type == "reactive_cleaning_dispatch"
        )
        assert action_ids == selected_ids
        assert dispatch_ids == selected_ids
        assert outcome.crew_hours == pytest.approx(
            len(selected_ids)
            * (crew_config.setup_minutes_per_cohort + crew_config.cleaning_minutes_per_cohort)
            / 60.0
        )
        assert outcome.water_liters == pytest.approx(
            len(selected_ids) * crew_config.water_liters_per_cohort
        )
        assert outcome.recovered_loss_estimated_kwh == pytest.approx(expected_recovered_kwh)
        assert outcome.dirty_cleaning_count == len(set(selected_ids) & actionable_ids)
        assert outcome.false_positive_cleaning_count == len(set(selected_ids) - actionable_ids)


def test_randomized_daily_operations_reconcile_through_annual_economics() -> None:
    """Property-style seeded trials cross daily, annual, adapter, and engine boundaries."""
    rng = np.random.default_rng(20_260_712)
    rates = _rated_reactive_operations()
    rules = _reactive_cost_rules(rates)
    engine = EconomicEngine(
        EconomicConfig(tariff_sar_per_kwh=0.20, discount_rate=0.08, useful_life_years=7)
    )

    for trial_index in range(32):
        day_count = int(rng.integers(1, 25))
        daily_results: list[DailyScenarioResult] = []
        for day_index in range(day_count):
            operational = OperationalQuantities(
                inspections_count=int(rng.integers(0, 31)),
                cleaning_actions_count=int(rng.integers(0, 9)),
                coated_panel_count=int(rng.integers(0, 501)),
                crew_hours=float(rng.integers(0, 4_001)) / 16.0,
                drone_flight_hours=float(rng.integers(0, 2_001)) / 32.0,
                water_liters=float(rng.integers(0, 100_001)) / 10.0,
                energy_used_kwh=float(rng.integers(0, 20_001)) / 100.0,
            )
            clean_energy = float(rng.integers(1_000, 5_001)) / 10.0
            daily_results.append(
                DailyScenarioResult(
                    date=date(2025, 1, 1) + timedelta(days=day_index),
                    scenario_name="reactive_cv",
                    clean_energy_kwh=clean_energy,
                    actual_energy_kwh=clean_energy * 0.9,
                    operational=operational,
                )
            )

        annual = AnnualScenarioResult(
            scenario_name="reactive_cv",
            daily_results=tuple(daily_results),
        )
        operational = _annual_operational_quantities(annual)

        assert operational.inspections_count == sum(
            day.operational.inspections_count for day in daily_results
        )
        assert operational.cleaning_actions_count == sum(
            day.operational.cleaning_actions_count for day in daily_results
        )
        assert operational.coated_panel_count == max(
            day.operational.coated_panel_count for day in daily_results
        )
        assert operational.crew_hours == sum(day.operational.crew_hours for day in daily_results)
        assert operational.drone_flight_hours == sum(
            day.operational.drone_flight_hours for day in daily_results
        )
        assert operational.water_liters == sum(
            day.operational.water_liters for day in daily_results
        )
        assert operational.energy_used_kwh == sum(
            day.operational.energy_used_kwh for day in daily_results
        )

        equipment_capex = CostComponent(
            name="reactive equipment capex",
            category="capex",
            amount_sar=10_000.0 + trial_index,
            unit="SAR",
            source="adversarial test",
            source_status="test",
        )
        components = build_reactive_cost_components(
            operational_quantities=operational,
            rates=rates,
            additional_components=(equipment_capex,),
        )
        checks = reconcile_operational_costs(
            operational_quantities=operational,
            cost_components=components,
            rules=rules,
        )

        assert len(checks) == 6
        assert all_reconciled(checks)
        for check in checks:
            assert check.recorded_amount_sar == check.expected_amount_sar

        economic = engine.evaluate(
            ScenarioEconomicInputs(
                scenario_name="reactive",
                actual_energy_kwh=annual.annual_actual_energy_kwh,
                clean_energy_kwh=annual.annual_clean_energy_kwh,
                operational_quantities=operational,
                cost_components=components,
            )
        )
        expected_opex = sum(
            component.amount_sar for component in components if component.category == "opex"
        )
        expected_capex = sum(
            component.amount_sar for component in components if component.category == "capex"
        )
        assert economic.annual_opex_sar == expected_opex
        assert economic.total_capex_sar == expected_capex
        assert economic.annualized_capex_sar == pytest.approx(
            engine.annualize_capex(expected_capex)
        )
        assert economic.total_annual_cost_sar == pytest.approx(
            expected_opex + engine.annualize_capex(expected_capex)
        )


def test_reconciliation_detects_each_independently_perturbed_rated_cost() -> None:
    operational = OperationalQuantities(
        inspections_count=11,
        cleaning_actions_count=7,
        crew_hours=5.25,
        drone_flight_hours=2.5,
        water_liters=123.5,
        energy_used_kwh=8.75,
    )
    rates = _rated_reactive_operations()
    components = build_reactive_cost_components(
        operational_quantities=operational,
        rates=rates,
    )
    rules = _reactive_cost_rules(rates)

    for component_to_corrupt in components:
        corrupted = tuple(
            replace(component, amount_sar=component.amount_sar + 0.01)
            if component.name == component_to_corrupt.name
            else component
            for component in components
        )
        checks = reconcile_operational_costs(
            operational_quantities=operational,
            cost_components=corrupted,
            rules=rules,
        )

        failed = [check for check in checks if not check.passed]
        assert [check.cost_component_name for check in failed] == [component_to_corrupt.name]
        assert failed[0].difference_sar == pytest.approx(0.01)


@pytest.mark.parametrize(
    "field_name",
    (
        "inspections_count",
        "cleaning_actions_count",
        "coated_panel_count",
        "crew_hours",
        "drone_flight_hours",
        "water_liters",
        "energy_used_kwh",
        "opex_cost",
        "capex_cost",
    ),
)
def test_operational_quantity_contract_rejects_negative_values(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        OperationalQuantities(**{field_name: -1})


@pytest.mark.parametrize(
    "field_name",
    (
        "crew_hours",
        "drone_flight_hours",
        "water_liters",
        "energy_used_kwh",
        "opex_cost",
        "capex_cost",
    ),
)
@pytest.mark.parametrize("non_finite_value", (float("nan"), float("inf")))
def test_operational_quantity_contract_rejects_non_finite_values(
    field_name: str,
    non_finite_value: float,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        OperationalQuantities(**{field_name: non_finite_value})
