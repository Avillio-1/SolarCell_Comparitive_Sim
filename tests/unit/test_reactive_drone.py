from __future__ import annotations

from solarclean.config.models import ReactiveDroneConfig
from solarclean.domain.reactive_cv.drone import DroneFleet


def _config(**overrides: object) -> ReactiveDroneConfig:
    defaults: dict[str, object] = {
        "cohorts_per_flight": 5,
        "flights_per_day": 2,
        "flight_duration_minutes": 20.0,
        "max_wind_speed_m_s": 10.0,
        "max_precipitation_mm": 0.5,
        "energy_kwh_per_flight": 0.4,
        "compute_energy_kwh_per_image": 0.02,
    }
    defaults.update(overrides)
    return ReactiveDroneConfig(**defaults)  # type: ignore[arg-type]


def test_capacity_caps_inspected_cohorts() -> None:
    fleet = DroneFleet(_config(cohorts_per_flight=5, flights_per_day=2))
    due = tuple(range(30))

    plan = fleet.plan_flights(due, wind_speed_m_s=2.0, precipitation_mm=0.0)

    assert len(plan.inspected_cohort_ids) == 10
    assert plan.inspected_cohort_ids == due[:10]
    assert plan.flights_flown == 2


def test_flights_flown_rounds_up_for_partial_final_flight() -> None:
    fleet = DroneFleet(_config(cohorts_per_flight=5, flights_per_day=4))
    due = tuple(range(7))

    plan = fleet.plan_flights(due, wind_speed_m_s=2.0, precipitation_mm=0.0)

    assert len(plan.inspected_cohort_ids) == 7
    assert plan.flights_flown == 2  # ceil(7/5)


def test_high_wind_cancels_all_flights() -> None:
    fleet = DroneFleet(_config(max_wind_speed_m_s=10.0))
    due = (1, 2, 3)

    plan = fleet.plan_flights(due, wind_speed_m_s=15.0, precipitation_mm=0.0)

    assert plan.weather_cancelled is True
    assert plan.inspected_cohort_ids == ()
    assert plan.flights_flown == 0
    assert plan.drone_energy_kwh == 0.0


def test_rain_cancels_all_flights() -> None:
    fleet = DroneFleet(_config(max_precipitation_mm=0.2))
    due = (1, 2, 3)

    plan = fleet.plan_flights(due, wind_speed_m_s=1.0, precipitation_mm=5.0)

    assert plan.weather_cancelled is True
    assert plan.inspected_cohort_ids == ()


def test_energy_accounting_scales_with_flights_and_images() -> None:
    fleet = DroneFleet(
        _config(
            cohorts_per_flight=5,
            flights_per_day=10,
            energy_kwh_per_flight=1.0,
            compute_energy_kwh_per_image=0.1,
        )
    )
    due = tuple(range(5))

    plan = fleet.plan_flights(due, wind_speed_m_s=1.0, precipitation_mm=0.0)

    assert plan.flights_flown == 1
    assert plan.drone_energy_kwh == 1.0
    assert plan.compute_energy_kwh == 5 * 0.1


def test_no_due_cohorts_means_no_flights() -> None:
    fleet = DroneFleet(_config())
    plan = fleet.plan_flights((), wind_speed_m_s=1.0, precipitation_mm=0.0)
    assert plan.flights_flown == 0
    assert plan.weather_cancelled is False
