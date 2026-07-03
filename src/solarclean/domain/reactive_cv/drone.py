from __future__ import annotations

from dataclasses import dataclass

from solarclean.config.models import ReactiveDroneConfig


@dataclass(frozen=True)
class DroneFlightPlan:
    inspected_cohort_ids: tuple[int, ...]
    flights_flown: int
    flight_hours: float
    drone_energy_kwh: float
    compute_energy_kwh: float
    weather_cancelled: bool


class DroneFleet:
    """Applies capacity and weather-cancellation limits to due inspections."""

    def __init__(self, config: ReactiveDroneConfig) -> None:
        self.config = config

    def plan_flights(
        self,
        due_cohort_ids: tuple[int, ...],
        *,
        wind_speed_m_s: float,
        precipitation_mm: float,
    ) -> DroneFlightPlan:
        if not due_cohort_ids:
            return DroneFlightPlan(
                inspected_cohort_ids=(),
                flights_flown=0,
                flight_hours=0.0,
                drone_energy_kwh=0.0,
                compute_energy_kwh=0.0,
                weather_cancelled=False,
            )
        cancelled = (
            wind_speed_m_s > self.config.max_wind_speed_m_s
            or precipitation_mm > self.config.max_precipitation_mm
        )
        if cancelled:
            return DroneFlightPlan(
                inspected_cohort_ids=(),
                flights_flown=0,
                flight_hours=0.0,
                drone_energy_kwh=0.0,
                compute_energy_kwh=0.0,
                weather_cancelled=True,
            )
        capacity = self.config.max_cohorts_per_day
        inspected = due_cohort_ids[:capacity]
        flights = min(
            self.config.flights_per_day,
            -(-len(inspected) // self.config.cohorts_per_flight) if inspected else 0,
        )
        flight_hours = flights * self.config.flight_duration_minutes / 60.0
        drone_energy = flights * self.config.energy_kwh_per_flight
        compute_energy = len(inspected) * self.config.compute_energy_kwh_per_image
        return DroneFlightPlan(
            inspected_cohort_ids=inspected,
            flights_flown=flights,
            flight_hours=flight_hours,
            drone_energy_kwh=drone_energy,
            compute_energy_kwh=compute_energy,
            weather_cancelled=False,
        )
