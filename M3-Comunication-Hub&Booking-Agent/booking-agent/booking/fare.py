"""
booking/fare.py
---------------
Deterministic fare calculation engine for the Booking Agent.

Documentation Notice:
---------------------
"Current fare values are development/demo configuration unless official
Railway fare data has been provided."
These values do NOT represent official Sri Lanka Railways tariff schedules
and are provided strictly for development, testing, and demonstration purposes.

Responsibilities (Phase 3):
- Deterministic lookup of base fare per passenger using route and seat class.
- Calculation: total_fare = fare_per_passenger * passenger_count.
- Uses Python Decimal throughout for exact currency representation without
  floating-point rounding inaccuracies.
- Raises clean FareNotFoundError if no rule matches route or class.

Architectural boundaries:
- Strictly algorithmic and deterministic: No LLM, no RAG, no prompt inference.
- Pure calculation: Does NOT create reservations, persist bookings, or issue references.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from .availability import normalize_seat_class
from .exceptions import FareNotFoundError, InvalidBookingError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from database.models import TrainSchedule


# ---------------------------------------------------------------------------
# Demo / Development Fare Rules Table
# ---------------------------------------------------------------------------
# Map: (normalized_origin, normalized_destination) -> {canonical_seat_class: Decimal}
# NOTE: Current fare values are development/demo configuration unless official
# Railway fare data has been provided.
DEMO_FARE_RULES: dict[tuple[str, str], dict[str, Decimal]] = {
    ("colombo", "kandy"): {
        "First Class": Decimal("2500.00"),
        "Second Class": Decimal("1200.00"),
    },
    ("kandy", "colombo"): {
        "First Class": Decimal("2500.00"),
        "Second Class": Decimal("1200.00"),
    },
    ("colombo", "galle"): {
        "First Class": Decimal("1800.00"),
        "Second Class": Decimal("800.00"),
    },
    ("galle", "colombo"): {
        "First Class": Decimal("1800.00"),
        "Second Class": Decimal("800.00"),
    },
    ("colombo", "badulla"): {
        "First Class": Decimal("4000.00"),
        "Second Class": Decimal("2000.00"),
    },
    ("badulla", "colombo"): {
        "First Class": Decimal("4000.00"),
        "Second Class": Decimal("2000.00"),
    },
}


# ---------------------------------------------------------------------------
# Output Schema
# ---------------------------------------------------------------------------

class FareBreakdown(BaseModel):
    """
    Structured breakdown of a deterministic fare calculation.

    Attributes
    ----------
    from_station:        Departure station name.
    to_station:          Arrival station name.
    seat_class:          Canonical seat class name.
    passenger_count:     Number of passengers.
    fare_per_passenger:  Base fare per passenger (Decimal).
    total_fare:          Total calculated fare (fare_per_passenger * passenger_count).
    """

    from_station: str = Field(..., min_length=1, description="Departure station")
    to_station: str = Field(..., min_length=1, description="Arrival station")
    seat_class: str = Field(..., min_length=1, description="Canonical seat class")
    passenger_count: int = Field(..., ge=1, le=10, description="Passenger count")
    fare_per_passenger: Decimal = Field(..., ge=0, description="Base fare per passenger")
    total_fare: Decimal = Field(..., ge=0, description="Total calculated fare")

    model_config = {"str_strip_whitespace": True}


# ---------------------------------------------------------------------------
# Calculation Functions
# ---------------------------------------------------------------------------

def get_fare_per_passenger(
    from_station: str,
    to_station: str,
    seat_class: str,
    fare_rules: dict[tuple[str, str], dict[str, Decimal]] | None = None,
) -> Decimal:
    """
    Look up the base fare per passenger for a given route and class.

    Parameters
    ----------
    from_station: Departure station.
    to_station:   Arrival station.
    seat_class:   Seat class name.
    fare_rules:   Optional custom fare rules map (defaults to DEMO_FARE_RULES).

    Returns
    -------
    Decimal: Base fare per passenger.

    Raises
    ------
    InvalidBookingError: If station names or seat class are missing.
    FareNotFoundError: If no fare rule exists for the route or class.
    """
    if not from_station or not from_station.strip():
        raise InvalidBookingError("Departure station must be provided.")
    if not to_station or not to_station.strip():
        raise InvalidBookingError("Arrival station must be provided.")

    canonical_class = normalize_seat_class(seat_class)
    clean_from = from_station.strip().lower()
    clean_to = to_station.strip().lower()
    route_key = (clean_from, clean_to)

    rules_table = fare_rules if fare_rules is not None else DEMO_FARE_RULES

    route_fares = rules_table.get(route_key)
    if not route_fares or canonical_class not in route_fares:
        route_display = f"{from_station.strip()} -> {to_station.strip()}"
        raise FareNotFoundError(
            route=route_display,
            seat_class=canonical_class,
            message=(
                f"No deterministic fare rule found for route '{route_display}' "
                f"and seat class '{canonical_class}'."
            ),
        )

    return route_fares[canonical_class]


def calculate_fare(
    from_station: str | None = None,
    to_station: str | None = None,
    seat_class: str = "Second Class",
    passenger_count: int = 1,
    schedule: TrainSchedule | None = None,
    db: Session | None = None,
    fare_rules: dict[tuple[str, str], dict[str, Decimal]] | None = None,
) -> FareBreakdown:
    """
    Calculate the total fare for a booking request deterministically.

    Formula:
    total_fare = fare_per_passenger * passenger_count

    Parameters
    ----------
    from_station:    Origin station (optional if schedule provided).
    to_station:      Destination station (optional if schedule provided).
    seat_class:      Seat class (e.g. 'First Class', 'Second Class').
    passenger_count: Number of passengers (1 to 10).
    schedule:        Optional TrainSchedule instance to extract route.
    db:              Optional SQLAlchemy session for future dynamic rule lookups.
    fare_rules:      Optional custom fare table.

    Returns
    -------
    FareBreakdown: Structured fare calculation breakdown with Decimal precision.

    Raises
    ------
    InvalidBookingError: If passenger_count < 1 or route is unspecified.
    FareNotFoundError: If no fare rule is found.
    """
    if passenger_count < 1:
        raise InvalidBookingError(
            f"Passenger count must be at least 1, got {passenger_count}."
        )

    # Extract origin/destination from schedule if not explicitly passed
    resolved_from = from_station or (schedule.from_station if schedule else "")
    resolved_to = to_station or (schedule.to_station if schedule else "")

    if not resolved_from or not resolved_to:
        raise InvalidBookingError("Origin and destination stations must be provided.")

    canonical_class = normalize_seat_class(seat_class)
    fare_per_passenger = get_fare_per_passenger(
        from_station=resolved_from,
        to_station=resolved_to,
        seat_class=canonical_class,
        fare_rules=fare_rules,
    )

    # Decimal arithmetic
    total_fare = (fare_per_passenger * Decimal(passenger_count)).quantize(
        Decimal("0.01")
    )

    return FareBreakdown(
        from_station=resolved_from.strip(),
        to_station=resolved_to.strip(),
        seat_class=canonical_class,
        passenger_count=passenger_count,
        fare_per_passenger=fare_per_passenger,
        total_fare=total_fare,
    )
