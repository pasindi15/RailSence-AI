"""
booking/availability.py
-----------------------
Train, schedule, and seat availability query layer for the Booking Agent.

Responsibilities (Phase 3):
- Deterministic train lookup by public ID (e.g. 'PM-4082').
- Enforcing that train exists and is active.
- Deterministic train schedule/trip lookup by train, route, and travel date.
- Business validation of booking details.
- Deterministic seat availability check derived dynamically from schedule capacity
  and confirmed reservations.

Architectural & Concurrency Rules:
- Dynamic calculation: Available seats = capacity - sum(passenger_count for CONFIRMED bookings).
- CANCELLED bookings are strictly excluded from the booked count.
- Does not decrement schedule capacity permanently during reads.
- Concurrency note: In the final booking creation workflow, seat checking and booking
  insertion should be executed within a controlled database transaction (e.g., locking
  the schedule row or performing an atomic check-and-insert) to prevent race conditions
  and double-booking under concurrent load.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import Booking, BookingStatus, Train, TrainSchedule
from .exceptions import (
    InvalidBookingError,
    RouteMismatchError,
    ScheduleNotFoundError,
    SeatsUnavailableError,
    TrainNotFoundError,
    TrainUnderMaintenanceError,
)

if TYPE_CHECKING:
    from schemas.booking import BookingRequest


# ---------------------------------------------------------------------------
# Seat Class Definitions & Centralized Normalization
# ---------------------------------------------------------------------------

class SeatClass(str, Enum):
    FIRST_CLASS = "First Class"
    SECOND_CLASS = "Second Class"


SUPPORTED_SEAT_CLASSES: tuple[str, ...] = (
    SeatClass.FIRST_CLASS.value,
    SeatClass.SECOND_CLASS.value,
)

_SEAT_CLASS_NORMALIZATION_MAP: dict[str, str] = {
    "first class": SeatClass.FIRST_CLASS.value,
    "first": SeatClass.FIRST_CLASS.value,
    "1st": SeatClass.FIRST_CLASS.value,
    "1st class": SeatClass.FIRST_CLASS.value,
    "second class": SeatClass.SECOND_CLASS.value,
    "second": SeatClass.SECOND_CLASS.value,
    "2nd": SeatClass.SECOND_CLASS.value,
    "2nd class": SeatClass.SECOND_CLASS.value,
}


def normalize_seat_class(seat_class: str) -> str:
    """
    Normalize user or schema input to canonical SeatClass string.

    Prevents scattered case/casing comparisons across files.

    Raises
    ------
    InvalidBookingError: If the seat class is not supported.
    """
    if not seat_class or not seat_class.strip():
        raise InvalidBookingError("Seat class must be provided.")

    clean = seat_class.strip().lower()
    canonical = _SEAT_CLASS_NORMALIZATION_MAP.get(clean)
    if not canonical:
        raise InvalidBookingError(
            f"Unsupported seat class: '{seat_class}'. "
            f"Must be one of: {list(SUPPORTED_SEAT_CLASSES)}"
        )
    return canonical


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_booking_details(request: BookingRequest) -> None:
    """
    Perform business-level validation on a BookingRequest.

    Raises
    ------
    InvalidBookingError: If business validation rules fail.
    """
    if not request.train_id or not request.train_id.strip():
        raise InvalidBookingError("Train ID must be provided.")

    if not request.from_station or not request.from_station.strip():
        raise InvalidBookingError("Departure station must be provided.")

    if not request.to_station or not request.to_station.strip():
        raise InvalidBookingError("Arrival station must be provided.")

    if request.from_station.strip().lower() == request.to_station.strip().lower():
        raise InvalidBookingError("Departure and arrival stations cannot be identical.")

    if request.passenger_count < 1 or request.passenger_count > 10:
        raise InvalidBookingError(
            f"Passenger count must be between 1 and 10, got {request.passenger_count}."
        )

    # Validate seat class format
    normalize_seat_class(request.seat_class)


# ---------------------------------------------------------------------------
# Train & Schedule Lookups
# ---------------------------------------------------------------------------

def get_train_by_public_id(db: Session, train_id: str) -> Train:
    """
    Find an active train by its public train_id identifier.

    Parameters
    ----------
    db:       Active SQLAlchemy database session.
    train_id: Public train identifier (e.g., 'PM-4082').

    Returns
    -------
    Train: Active Train ORM entity.

    Raises
    ------
    TrainNotFoundError: If the train does not exist or active is False.
    """
    clean_id = train_id.strip() if train_id else ""
    if not clean_id:
        raise TrainNotFoundError(train_id=train_id, message="Train ID cannot be empty.")

    train = db.query(Train).filter(Train.train_id == clean_id).first()
    if not train:
        raise TrainNotFoundError(
            train_id=clean_id,
            message=f"Train service '{clean_id}' was not found in the registry.",
        )

    if not train.active:
        raise TrainNotFoundError(
            train_id=clean_id,
            message=f"Train service '{clean_id}' is currently inactive or decommissioned.",
        )

    # Maintenance restriction — separate concept from active/inactive.
    # OUT_OF_SERVICE trains cannot accept new bookings regardless of schedule existence.
    ms = (getattr(train, "maintenance_status", None) or "").strip().upper()
    if ms == "OUT_OF_SERVICE":
        raise TrainUnderMaintenanceError(
            train_id=clean_id,
            maintenance_status=ms,
        )

    return train


def get_schedule_for_trip(
    db: Session,
    train_id: str,
    from_station: str,
    to_station: str,
    travel_date: date,
) -> TrainSchedule:
    """
    Find the matching TrainSchedule record for a specific train, route, and travel date.

    Parameters
    ----------
    db:           Active SQLAlchemy database session.
    train_id:     Public train identifier (e.g., 'PM-4082').
    from_station: Departure station name.
    to_station:   Arrival station name.
    travel_date:  Date of travel.

    Returns
    -------
    TrainSchedule: Matching TrainSchedule ORM entity.

    Raises
    ------
    TrainNotFoundError: If the train does not exist or is inactive.
    ScheduleNotFoundError: If no schedule operates that route on the given date.
    """
    train = get_train_by_public_id(db, train_id)

    clean_from = from_station.strip()
    clean_to = to_station.strip()

    # Route validation against the canonical route stored on the train record.
    # Only enforced when the route field is populated (nullable for backward compat).
    canonical_route = (getattr(train, "route", None) or "").strip()
    if canonical_route:
        # Route format: "Origin Station - Destination Station"
        parts = [p.strip() for p in canonical_route.split(" - ", 1)]
        if len(parts) == 2:
            c_origin, c_dest = parts[0].lower(), parts[1].lower()
            from_ok = clean_from.lower() in c_origin or c_origin in clean_from.lower()
            to_ok = clean_to.lower() in c_dest or c_dest in clean_to.lower()
            if not (from_ok and to_ok):
                raise RouteMismatchError(
                    train_id=train.train_id,
                    requested_route=f"{clean_from} - {clean_to}",
                    canonical_route=canonical_route,
                )

    schedule = (
        db.query(TrainSchedule)
        .filter(
            TrainSchedule.train_id == train.id,
            TrainSchedule.travel_date == travel_date,
            func.lower(func.trim(TrainSchedule.from_station)) == clean_from.lower(),
            func.lower(func.trim(TrainSchedule.to_station)) == clean_to.lower(),
        )
        .first()
    )

    if not schedule:
        route_str = f"{clean_from} -> {clean_to}"
        raise ScheduleNotFoundError(
            train_id=train.train_id,
            travel_date=str(travel_date),
            route=route_str,
        )

    return schedule


# ---------------------------------------------------------------------------
# Seat Availability Calculations
# ---------------------------------------------------------------------------

import os
from datetime import date, datetime, time, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    COLOMBO_TZ = ZoneInfo("Asia/Colombo")
except Exception:
    COLOMBO_TZ = timezone(timedelta(hours=5, minutes=30))

MINIMUM_CONNECTION_MINUTES = int(os.getenv("MIN_CONNECTION_MINUTES", "30"))


def calculate_journey_interval(
    travel_date: date,
    departure_time: time,
    arrival_time: time,
) -> tuple[datetime, datetime]:
    """
    Construct timezone-aware start and end datetimes for a journey (Asia/Colombo UTC+05:30).
    Properly accounts for overnight journeys crossing midnight boundaries.
    """
    dep_dt = datetime.combine(travel_date, departure_time).replace(tzinfo=COLOMBO_TZ)
    if arrival_time < departure_time:
        # Overnight journey spans into next calendar day
        arr_dt = datetime.combine(travel_date + timedelta(days=1), arrival_time).replace(tzinfo=COLOMBO_TZ)
    else:
        arr_dt = datetime.combine(travel_date, arrival_time).replace(tzinfo=COLOMBO_TZ)
    return dep_dt, arr_dt


def validate_journey_connection(
    journey1_end: datetime,
    journey2_start: datetime,
    station1: str,
    station2: str,
    min_connection_minutes: int | None = None,
) -> tuple[bool, str]:
    """
    Validate that a transfer between two sequential train journeys is physically feasible.
    """
    min_minutes = min_connection_minutes if min_connection_minutes is not None else MINIMUM_CONNECTION_MINUTES
    gap_minutes = (journey2_start - journey1_end).total_seconds() / 60.0

    if gap_minutes < 0:
        return False, "NEGATIVE_INTERVAL: Second journey departs before preceding journey arrives."
    elif station1.strip().lower() == station2.strip().lower():
        if gap_minutes < min_minutes:
            return False, f"INSUFFICIENT_TRANSFER_TIME: Only {int(gap_minutes)}m buffer at {station1}, minimum required is {min_minutes}m."
        return True, "FEASIBLE"
    else:
        # Transfer across different stations requires expanded travel buffer
        required_gap = min_minutes * 2
        if gap_minutes < required_gap:
            return False, f"TRANSFER_DATA_UNAVAILABLE_OR_INSUFFICIENT: Inter-station transfer between {station1} and {station2} requires at least {required_gap}m, but only {int(gap_minutes)}m is available."
        return True, "FEASIBLE"


def get_booked_seats(db: Session, schedule_id: int, seat_class: str) -> int:
    """
    Calculate the total number of booked seats for a given schedule and seat class.

    Rules:
    - Counts bookings with status = CONFIRMED.
    - Counts active unexpired SeatHolds (so held seats are not double-allocated).
    - CANCELLED, EXPIRED, and REJECTED bookings do NOT consume capacity.
    - Scoped strictly to the specific schedule and matching seat class.
    """
    canonical_class = normalize_seat_class(seat_class)
    booked_count = (
        db.query(func.coalesce(func.sum(Booking.passenger_count), 0))
        .filter(
            Booking.schedule_id == schedule_id,
            func.lower(func.trim(Booking.seat_class)) == canonical_class.lower(),
            Booking.status == BookingStatus.CONFIRMED,
        )
        .scalar()
    )
    # Include unexpired active seat holds
    try:
        from .lifecycle import get_active_hold_seat_count
        hold_count = get_active_hold_seat_count(db, schedule_id=schedule_id, seat_class=canonical_class)
    except Exception:
        hold_count = 0

    return int(booked_count or 0) + int(hold_count or 0)



def get_available_seats(
    db: Session,
    schedule: TrainSchedule,
    seat_class: str,
) -> int:
    """
    Calculate the remaining available seats for a schedule and class.

    Derived dynamically as:
    available_seats = schedule_capacity - booked_seats

    Parameters
    ----------
    db:         Active SQLAlchemy database session.
    schedule:   TrainSchedule entity.
    seat_class: Desired seat class.

    Returns
    -------
    int: Remaining available seats (minimum 0).
    """
    canonical_class = normalize_seat_class(seat_class)

    if canonical_class == SeatClass.FIRST_CLASS.value:
        capacity = schedule.first_class_capacity
    elif canonical_class == SeatClass.SECOND_CLASS.value:
        capacity = schedule.second_class_capacity
    else:
        raise InvalidBookingError(f"Unsupported seat class: '{seat_class}'")

    booked = get_booked_seats(db, schedule_id=schedule.id, seat_class=canonical_class)
    return max(0, capacity - booked)


def check_seat_availability(
    db: Session,
    schedule: TrainSchedule | int,
    seat_class: str,
    requested_seats: int,
) -> int:
    """
    Verify whether enough seats are available on the schedule for the requested class.

    Availability rule:
    If available_seats >= requested_seats:
        return remaining available_seats
    Else:
        raise SeatsUnavailableError(seat_class, requested=..., available=...)

    Parameters
    ----------
    db:              Active SQLAlchemy database session.
    schedule:        TrainSchedule entity or schedule integer ID.
    seat_class:      Seat class string.
    requested_seats: Number of seats requested (must be >= 1).

    Returns
    -------
    int: Remaining available seats.

    Raises
    ------
    InvalidBookingError: If requested_seats < 1.
    ScheduleNotFoundError: If schedule integer ID is not found.
    SeatsUnavailableError: If available seats < requested seats.
    """
    if requested_seats < 1:
        raise InvalidBookingError(
            f"Requested seats must be at least 1, got {requested_seats}."
        )

    # Resolve schedule entity if schedule_id passed
    if isinstance(schedule, int):
        sched_entity = (
            db.query(TrainSchedule).filter(TrainSchedule.id == schedule).first()
        )
        if not sched_entity:
            raise ScheduleNotFoundError(
                train_id="UNKNOWN",
                travel_date="",
                route=f"schedule_id={schedule}",
            )
        schedule = sched_entity

    canonical_class = normalize_seat_class(seat_class)
    available_seats = get_available_seats(
        db, schedule=schedule, seat_class=canonical_class
    )

    if available_seats < requested_seats:
        raise SeatsUnavailableError(
            seat_class=canonical_class,
            requested=requested_seats,
            available=available_seats,
        )

    return available_seats


def get_schedules_for_route(
    db: Session,
    from_station: str,
    to_station: str,
    travel_date: date,
) -> list[dict]:
    """
    Retrieve active train schedules matching the route and travel date,
    with dynamically derived available seat counts and fare information.
    """
    from .fare import get_fare_per_passenger

    clean_from = from_station.strip()
    clean_to = to_station.strip()

    results = (
        db.query(TrainSchedule, Train)
        .join(Train, TrainSchedule.train_id == Train.id)
        .filter(
            Train.active == True,  # noqa: E712
            func.lower(TrainSchedule.from_station) == clean_from.lower(),
            func.lower(TrainSchedule.to_station) == clean_to.lower(),
            TrainSchedule.travel_date == travel_date,
        )
        .all()
    )

    options: list[dict] = []
    for schedule, train in results:
        available_classes = []
        for s_class in (SeatClass.FIRST_CLASS.value, SeatClass.SECOND_CLASS.value):
            rem_seats = get_available_seats(db, schedule, s_class)
            try:
                base_fare = float(get_fare_per_passenger(clean_from, clean_to, s_class))
            except Exception:
                base_fare = 1500.0 if s_class == SeatClass.SECOND_CLASS.value else 2500.0

            available_classes.append({
                "seat_class": s_class,
                "available_seats": rem_seats,
                "base_fare": base_fare,
            })

        dep_str = (
            schedule.departure_time.strftime("%H:%M:%S")
            if hasattr(schedule.departure_time, "strftime")
            else str(schedule.departure_time)
        )
        arr_str = (
            schedule.arrival_time.strftime("%H:%M:%S")
            if hasattr(schedule.arrival_time, "strftime")
            else str(schedule.arrival_time)
        )

        options.append({
            "schedule_id": schedule.id,
            "train_id": train.train_id,
            "train_name": train.train_name,
            "from_station": schedule.from_station,
            "to_station": schedule.to_station,
            "travel_date": schedule.travel_date.isoformat(),
            "departure_time": dep_str,
            "arrival_time": arr_str,
            "available_classes": available_classes,
        })

    return options


# Convenience aliases adhering to existing naming conventions
verify_train_exists = get_train_by_public_id
get_schedule = get_schedule_for_trip

