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

import os
from datetime import date, datetime, time, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    COLOMBO_TZ = ZoneInfo("Asia/Colombo")
except Exception:
    COLOMBO_TZ = timezone(timedelta(hours=5, minutes=30))

from sqlalchemy.exc import IntegrityError
from .services_catalog import (
    find_matching_services,
    get_service_by_train_id,
    normalize_station,
    stations_match,
)

BOOKING_HORIZON_DAYS = int(os.getenv("BOOKING_HORIZON_DAYS", "365"))


# ---------------------------------------------------------------------------
# Date Horizon & Travel Date Validation
# ---------------------------------------------------------------------------

def validate_travel_date(travel_date: date) -> None:
    """
    Validate that the travel_date is neither in the past nor beyond the booking horizon,
    evaluated in the Asia/Colombo (UTC+05:30) timezone.
    """
    if os.getenv("ALLOW_PAST_TRAVEL_DATES", "").lower() in ("true", "1", "yes"):
        return

    now_colombo = datetime.now(COLOMBO_TZ).date()
    if travel_date < now_colombo:
        raise InvalidBookingError(
            f"Cannot book or query journeys for past date: {travel_date.isoformat()}. "
            f"Today is {now_colombo.isoformat()} (Asia/Colombo)."
        )
    max_date = now_colombo + timedelta(days=BOOKING_HORIZON_DAYS)
    if travel_date > max_date:
        raise InvalidBookingError(
            f"Travel date {travel_date.isoformat()} exceeds the advance booking limit of {BOOKING_HORIZON_DAYS} days "
            f"(up to {max_date.isoformat()})."
        )


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

    # Validate travel date if present on request
    if hasattr(request, "travel_date") and request.travel_date:
        validate_travel_date(request.travel_date)


# ---------------------------------------------------------------------------
# Train & Schedule Lookups
# ---------------------------------------------------------------------------

def get_train_by_public_id(db: Session, train_id: str) -> Train:
    """
    Find an active train by its public train_id identifier.
    If the train is in the canonical daily catalog but not yet in the DB,
    it is automatically registered.

    Parameters
    ----------
    db:       Active SQLAlchemy database session.
    train_id: Public train identifier (e.g., 'PM-4082', '1015').

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
        # Check if train exists in canonical daily services catalog
        catalog_svc = get_service_by_train_id(clean_id)
        if catalog_svc:
            sp = db.begin_nested()
            try:
                train = Train(
                    train_id=catalog_svc.train_id,
                    train_name=catalog_svc.train_name,
                    route=catalog_svc.route,
                    origin_station=catalog_svc.origin_station,
                    destination_station=catalog_svc.destination_station,
                    train_type="Express",
                    active=True,
                )
                db.add(train)
                db.flush()
                sp.commit()
            except IntegrityError:
                sp.rollback()
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
    ms = (getattr(train, "maintenance_status", None) or "").strip().upper()
    if ms == "OUT_OF_SERVICE":
        raise TrainUnderMaintenanceError(
            train_id=clean_id,
            maintenance_status=ms,
        )

    return train


def ensure_journeys_for_date(
    db: Session,
    travel_date: date,
    from_station: str | None = None,
    to_station: str | None = None,
    train_id: str | None = None,
) -> list[TrainSchedule]:
    """
    Idempotently ensure Train and TrainSchedule records exist for the specified
    travel_date matching the given stations and/or train_id based on the daily services catalog.

    Rules:
    - Date must be >= today and within BOOKING_HORIZON_DAYS (in Asia/Colombo).
    - Never overwrite existing TrainSchedule records or alter existing seat capacities.
    - Preserves explicitly CANCELLED, DELAYED, or DEPARTED service statuses.
    - Concurrency-safe: uses savepoint + flush to handle race conditions gracefully.
    - Calculates overnight arrival_date and departure/arrival times per stop sequence.
    - High Performance: batches existence checks into single queries rather than per-service roundtrips.
    """
    validate_travel_date(travel_date)

    matching_services = find_matching_services(
        origin=from_station,
        destination=to_station,
        train_id=train_id,
    )
    if not matching_services:
        return []

    # 1. Batch lookup all required Train records by train_id
    svc_train_ids = {svc.train_id for svc, _, _ in matching_services}
    existing_trains = {
        t.train_id: t
        for t in db.query(Train).filter(Train.train_id.in_(svc_train_ids)).all()
    }

    # Ensure missing trains exist
    for svc, _, _ in matching_services:
        if svc.train_id not in existing_trains:
            sp = db.begin_nested()
            try:
                t = Train(
                    train_id=svc.train_id,
                    train_name=svc.train_name,
                    route=svc.route,
                    origin_station=svc.origin_station,
                    destination_station=svc.destination_station,
                    train_type="Express",
                    active=True,
                )
                db.add(t)
                db.flush()
                sp.commit()
                existing_trains[svc.train_id] = t
            except IntegrityError:
                sp.rollback()
                t = db.query(Train).filter(Train.train_id == svc.train_id).first()
                if t:
                    existing_trains[svc.train_id] = t

    # 2. Batch lookup all existing schedules for these trains on this travel_date
    train_db_ids = [t.id for t in existing_trains.values() if t and t.id]
    existing_schedules_map: dict[tuple[int, str, str], TrainSchedule] = {}
    if train_db_ids:
        all_existing_scheds = (
            db.query(TrainSchedule)
            .filter(
                TrainSchedule.train_id.in_(train_db_ids),
                TrainSchedule.travel_date == travel_date,
            )
            .all()
        )
        for s in all_existing_scheds:
            key = (s.train_id, (s.from_station or "").strip().lower(), (s.to_station or "").strip().lower())
            existing_schedules_map[key] = s

    ensured: list[TrainSchedule] = []

    # 3. Create any missing schedules
    new_schedules_to_add: list[TrainSchedule] = []
    for svc, origin_stop, dest_stop in matching_services:
        train = existing_trains.get(svc.train_id)
        if not train or not train.active:
            continue

        sched_from = origin_stop.station if origin_stop else svc.origin_station
        sched_to = dest_stop.station if dest_stop else svc.destination_station
        dep_time = origin_stop.departure_time if origin_stop and origin_stop.departure_time else svc.departure_time
        arr_time = dest_stop.arrival_time if dest_stop and dest_stop.arrival_time else svc.arrival_time

        day_diff = (dest_stop.day_offset if dest_stop else 0) - (origin_stop.day_offset if origin_stop else 0)
        arrival_date = travel_date + timedelta(days=max(0, day_diff))

        key = (train.id, sched_from.strip().lower(), sched_to.strip().lower())
        existing = existing_schedules_map.get(key)
        if existing:
            ensured.append(existing)
            continue

        new_sched = TrainSchedule(
            train_id=train.id,
            service_id=svc.service_id,
            from_station=sched_from,
            to_station=sched_to,
            travel_date=travel_date,
            arrival_date=arrival_date,
            departure_time=dep_time,
            arrival_time=arr_time,
            first_class_capacity=svc.first_class_capacity,
            second_class_capacity=svc.second_class_capacity,
            service_status="SCHEDULED",
        )
        new_schedules_to_add.append(new_sched)

    if new_schedules_to_add:
        sp = db.begin_nested()
        try:
            for s in new_schedules_to_add:
                db.add(s)
            db.flush()
            sp.commit()
            ensured.extend(new_schedules_to_add)
        except IntegrityError:
            sp.rollback()
            re_queried = (
                db.query(TrainSchedule)
                .filter(
                    TrainSchedule.train_id.in_(train_db_ids),
                    TrainSchedule.travel_date == travel_date,
                )
                .all()
            )
            ensured = re_queried

    return ensured


def get_schedule_for_trip(
    db: Session,
    train_id: str,
    from_station: str,
    to_station: str,
    travel_date: date,
) -> TrainSchedule:
    """
    Find the matching TrainSchedule record for a specific train, route, and travel date.
    Automatically ensures recurring daily service journeys exist if applicable.

    Parameters
    ----------
    db:           Active SQLAlchemy database session.
    train_id:     Public train identifier (e.g., '1015', 'PM-4082').
    from_station: Departure station name.
    to_station:   Arrival station name.
    travel_date:  Date of travel.

    Returns
    -------
    TrainSchedule: Matching TrainSchedule ORM entity.

    Raises
    ------
    TrainNotFoundError: If the train does not exist or is inactive.
    RouteMismatchError: If the route is not operated by this train.
    ScheduleNotFoundError: If no schedule operates that route on the given date.
    InvalidBookingError: If the journey has been cancelled or travel date is invalid.
    """
    clean_from = from_station.strip()
    clean_to = to_station.strip()

    train = get_train_by_public_id(db, train_id)
    canonical_route = (getattr(train, "route", None) or "").strip()

    # Route validation
    catalog_svc = get_service_by_train_id(train_id)
    if catalog_svc:
        matching = find_matching_services(origin=clean_from, destination=clean_to, train_id=train_id)
        if not matching:
            raise RouteMismatchError(
                train_id=train.train_id,
                requested_route=f"{clean_from} -> {clean_to}",
                canonical_route=catalog_svc.route,
            )
    elif canonical_route:
        # Route format: "Origin Station - Destination Station"
        parts = [p.strip() for p in canonical_route.split(" - ", 1)]
        if len(parts) == 2:
            c_origin, c_dest = parts[0].lower(), parts[1].lower()
            from_ok = clean_from.lower() in c_origin or c_origin in clean_from.lower()
            to_ok = clean_to.lower() in c_dest or c_dest in clean_to.lower()
            if not (from_ok and to_ok):
                raise RouteMismatchError(
                    train_id=train.train_id,
                    requested_route=f"{clean_from} -> {clean_to}",
                    canonical_route=canonical_route,
                )

    # 1. Query existing schedule directly
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

    # 2. If not found and train is a catalog service, ensure journey for this date
    if not schedule and catalog_svc:
        ensure_journeys_for_date(
            db=db,
            travel_date=travel_date,
            from_station=clean_from,
            to_station=clean_to,
            train_id=train.train_id,
        )
        all_train_scheds = (
            db.query(TrainSchedule)
            .filter(
                TrainSchedule.train_id == train.id,
                TrainSchedule.travel_date == travel_date,
            )
            .all()
        )
        for s in all_train_scheds:
            if stations_match(s.from_station, clean_from) and stations_match(s.to_station, clean_to):
                schedule = s
                break

    if not schedule:
        route_str = f"{clean_from} -> {clean_to}"
        raise ScheduleNotFoundError(
            train_id=train.train_id,
            travel_date=str(travel_date),
            route=route_str,
        )

    status = (getattr(schedule, "service_status", "SCHEDULED") or "SCHEDULED").upper()
    if status == "CANCELLED":
        raise InvalidBookingError(
            f"Train service '{train.train_id}' on {travel_date.isoformat()} ({clean_from} -> {clean_to}) has been cancelled."
        )

    return schedule


# ---------------------------------------------------------------------------
# Seat Availability Calculations
# ---------------------------------------------------------------------------
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
    If schedule is CANCELLED, available seats are 0.

    Parameters
    ----------
    db:         Active SQLAlchemy database session.
    schedule:   TrainSchedule entity.
    seat_class: Desired seat class.

    Returns
    -------
    int: Remaining available seats (minimum 0).
    """
    status = (getattr(schedule, "service_status", "SCHEDULED") or "SCHEDULED").upper()
    if status == "CANCELLED":
        return 0

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
    Automatically ensures recurring daily service journeys exist if missing.
    Batched implementation: replaces N+1 seat count queries with 2 aggregated batch queries.
    """
    from .fare import get_fare_per_passenger

    clean_from = from_station.strip()
    clean_to = to_station.strip()

    # 1. First query existing active schedules for this travel date
    results = (
        db.query(TrainSchedule, Train)
        .join(Train, TrainSchedule.train_id == Train.id)
        .filter(
            Train.active == True,  # noqa: E712
            TrainSchedule.travel_date == travel_date,
        )
        .all()
    )

    has_matching = any(
        stations_match(s.from_station, clean_from) and stations_match(s.to_station, clean_to)
        for s, t in results
    )

    # 2. Only if no matching schedules exist in the database, lazily materialize from daily catalog
    if not has_matching:
        try:
            ensure_journeys_for_date(
                db=db,
                travel_date=travel_date,
                from_station=clean_from,
                to_station=clean_to,
            )
            results = (
                db.query(TrainSchedule, Train)
                .join(Train, TrainSchedule.train_id == Train.id)
                .filter(
                    Train.active == True,  # noqa: E712
                    TrainSchedule.travel_date == travel_date,
                )
                .all()
            )
        except InvalidBookingError:
            # Invalid date (past or out of horizon) returns empty list
            return []

    # Filter matching route and active trains
    matched_pairs: list[tuple[TrainSchedule, Train]] = []
    for schedule, train in results:
        if not (stations_match(schedule.from_station, clean_from) and stations_match(schedule.to_station, clean_to)):
            continue
        ms = (getattr(train, "maintenance_status", None) or "").strip().upper()
        if ms == "OUT_OF_SERVICE":
            continue
        # Skip historical/test-fixture trains (IC-XXXX, YD-XXXX, ND-XXXX, EXP-OVERLAP, etc.)
        train_type = (getattr(train, "train_type", None) or "").strip().lower()
        if train_type in ("historical_operations", "test_fixture"):
            continue
        matched_pairs.append((schedule, train))

    # Deduplicate: keep one entry per (train_id, departure_time) — prefer lowest schedule.id
    # This prevents duplicate rows caused by multiple seed runs or concurrent materialization.
    seen_keys: dict[tuple[str, str], tuple[TrainSchedule, Train]] = {}
    for schedule, train in matched_pairs:
        dep_str_key = (
            schedule.departure_time.strftime("%H:%M")
            if hasattr(schedule.departure_time, "strftime")
            else str(schedule.departure_time)[:5]
        )
        dedup_key = (train.train_id, dep_str_key)
        existing = seen_keys.get(dedup_key)
        if existing is None or schedule.id < existing[0].id:
            seen_keys[dedup_key] = (schedule, train)
    matched_pairs = list(seen_keys.values())

    if not matched_pairs:
        return []

    sched_ids = [s.id for s, _ in matched_pairs]

    # Batch Query 1: Aggregated booked seats for all candidate schedules
    booked_map: dict[tuple[int, str], int] = {}
    if sched_ids:
        booked_counts = (
            db.query(
                Booking.schedule_id,
                func.lower(func.trim(Booking.seat_class)),
                func.coalesce(func.sum(Booking.passenger_count), 0),
            )
            .filter(
                Booking.schedule_id.in_(sched_ids),
                Booking.status == BookingStatus.CONFIRMED,
            )
            .group_by(Booking.schedule_id, func.lower(func.trim(Booking.seat_class)))
            .all()
        )
        for sid, scls, cnt in booked_counts:
            booked_map[(sid, scls)] = int(cnt)

    # Batch Query 2: Aggregated active unexpired seat holds for all candidate schedules
    hold_map: dict[tuple[int, str], int] = {}
    if sched_ids:
        try:
            from database.models import HoldStatus, SeatHold
            now_utc = datetime.now(timezone.utc)
            hold_counts = (
                db.query(
                    SeatHold.schedule_id,
                    func.lower(func.trim(SeatHold.seat_class)),
                    func.coalesce(func.sum(SeatHold.seat_count), 0),
                )
                .filter(
                    SeatHold.schedule_id.in_(sched_ids),
                    SeatHold.status == HoldStatus.ACTIVE,
                    SeatHold.expires_at > now_utc,
                )
                .group_by(SeatHold.schedule_id, func.lower(func.trim(SeatHold.seat_class)))
                .all()
            )
            for sid, scls, cnt in hold_counts:
                hold_map[(sid, scls)] = int(cnt)
        except Exception:
            pass

    options: list[dict] = []
    for schedule, train in matched_pairs:
        status = (getattr(schedule, "service_status", "SCHEDULED") or "SCHEDULED").upper()
        is_cancelled = status == "CANCELLED"

        available_classes = []
        for s_class in (SeatClass.FIRST_CLASS.value, SeatClass.SECOND_CLASS.value):
            if is_cancelled:
                rem_seats = 0
            else:
                canonical = s_class.strip().lower()
                capacity = (
                    schedule.first_class_capacity
                    if s_class == SeatClass.FIRST_CLASS.value
                    else schedule.second_class_capacity
                )
                booked = booked_map.get((schedule.id, canonical), 0)
                holds = hold_map.get((schedule.id, canonical), 0)
                rem_seats = max(0, capacity - booked - holds)

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

        arr_date_val = schedule.arrival_date or schedule.travel_date
        is_overnight = arr_date_val > schedule.travel_date

        options.append({
            "schedule_id": schedule.id,
            "service_id": getattr(schedule, "service_id", None),
            "train_id": train.train_id,
            "train_name": train.train_name,
            "train_type": getattr(train, "train_type", "Express"),
            "from_station": schedule.from_station,
            "to_station": schedule.to_station,
            "travel_date": schedule.travel_date.isoformat(),
            "arrival_date": arr_date_val.isoformat(),
            "is_overnight": is_overnight,
            "departure_time": dep_str,
            "arrival_time": arr_str,
            "service_status": status,
            "available_classes": available_classes,
        })

    # Sort options chronologically by departure time
    options.sort(key=lambda opt: opt.get("departure_time", ""))
    return options


# Convenience aliases adhering to existing naming conventions
verify_train_exists = get_train_by_public_id
get_schedule = get_schedule_for_trip

