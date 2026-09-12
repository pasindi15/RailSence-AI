"""
fraud/rules.py
--------------
RailSense AI — Hard Deterministic Fraud & Conflict Rules.

Responsibilities:
1. Rule 1: DUPLICATE_NIC_IN_BOOKING
   - Rejects booking if the same normalized NIC appears twice for different passengers.
2. Rule 2: DUPLICATE_ACTIVE_TICKET
   - Rejects booking if the passenger already holds a CONFIRMED ticket for the same train on the same travel date.
3. Rule 3: CONFLICTING_ACTIVE_JOURNEY
   - Rejects booking if the passenger already holds a CONFIRMED ticket for another train whose journey interval
     overlaps with the requested journey interval on the same travel date:
     (existing_dep < requested_arr AND requested_dep < existing_arr).
4. Feature Generation:
   - Derives behavioral numerical features for Security & Fraud Agent ML anomaly scoring.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import (
    AuditLog,
    AuditStatus,
    Booking,
    BookingPassenger,
    BookingStatus,
    CancellationRequest,
    Passenger,
    TrainSchedule,
)

if TYPE_CHECKING:
    from schemas.booking import PassengerDetail


from booking.exceptions import (
    ConflictingActiveJourneyError,
    DuplicateActiveTicketError,
    DuplicateNICInBookingError,
    InvalidBookingError,
)

DeterministicFraudRuleError = InvalidBookingError


def check_duplicate_nic_in_booking(passengers: list[PassengerDetail]) -> None:
    """
    Hard Rule 1: Verify that every passenger in the booking provides a distinct NIC.
    """
    seen: set[str] = set()
    for p in passengers:
        clean = p.nic.strip().upper()
        if clean in seen:
            raise DuplicateNICInBookingError()
        seen.add(clean)


def check_duplicate_active_ticket(
    db: Session,
    nic_hashes: list[str],
    train_id: int,
    travel_date: date,
    train_name: str = "selected train",
) -> None:
    """
    Hard Rule 2: Verify that no passenger already holds an active CONFIRMED ticket
    for the exact same train and travel date.
    """
    if not nic_hashes:
        return

    # Query active bookings matching train_id, travel_date, and any of the passenger nic_hashes
    conflict = (
        db.query(Booking)
        .join(BookingPassenger, Booking.id == BookingPassenger.booking_id)
        .join(Passenger, BookingPassenger.passenger_id == Passenger.id)
        .filter(
            Booking.status == BookingStatus.CONFIRMED,
            Booking.train_id == train_id,
            Booking.travel_date == travel_date,
            Passenger.nic_hash.in_(nic_hashes),
        )
        .first()
    )

    if conflict:
        raise DuplicateActiveTicketError(train_name=train_name, travel_date=travel_date)


def check_conflicting_active_journey(
    db: Session,
    nic_hashes: list[str],
    travel_date: date,
    requested_departure: time,
    requested_arrival: time,
    exclude_booking_id: int | None = None,
) -> None:
    """
    Hard Rule 3: Cross-Train Time Conflict Check.
    Verifies that no passenger already has another CONFIRMED booking on the same date
    whose travel interval overlaps with the requested interval:
    existing_departure < requested_arrival AND requested_departure < existing_arrival
    """
    if not nic_hashes:
        return

    query = (
        db.query(Booking)
        .join(BookingPassenger, Booking.id == BookingPassenger.booking_id)
        .join(Passenger, BookingPassenger.passenger_id == Passenger.id)
        .join(TrainSchedule, Booking.schedule_id == TrainSchedule.id)
        .filter(
            Booking.status == BookingStatus.CONFIRMED,
            Booking.travel_date == travel_date,
            Passenger.nic_hash.in_(nic_hashes),
        )
    )

    if exclude_booking_id is not None:
        query = query.filter(Booking.id != exclude_booking_id)

    confirmed_bookings = query.all()

    req_window = f"{requested_departure.strftime('%H:%M')}–{requested_arrival.strftime('%H:%M')}"

    for b in confirmed_bookings:
        if not b.schedule:
            continue
        ex_dep = b.schedule.departure_time
        ex_arr = b.schedule.arrival_time

        # Strict interval overlap check
        if ex_dep < requested_arrival and requested_departure < ex_arr:
            train_display = b.train.train_name if b.train else f"Train #{b.train_id}"
            ex_window = f"{ex_dep.strftime('%H:%M')}–{ex_arr.strftime('%H:%M')}"
            raise ConflictingActiveJourneyError(
                existing_train=train_display,
                existing_window=ex_window,
                requested_window=req_window,
            )


def compute_passenger_fraud_features(
    db: Session,
    nic_hashes: list[str],
    schedule: TrainSchedule,
) -> dict[str, float]:
    """
    Compute derived numerical behavioral features for the Security & Fraud Agent ML detector.
    Protects privacy: uses only non-plain protected identifiers and derived aggregate counts.
    """
    now = datetime.now(timezone.utc)
    t_1m = now - timedelta(minutes=1)
    t_10m = now - timedelta(minutes=10)
    t_24h = now - timedelta(hours=24)

    if not nic_hashes:
        return {
            "bookings_last_1_minute": 0.0,
            "bookings_last_10_minutes": 0.0,
            "bookings_last_24_hours": 0.0,
            "cancellations_last_24_hours": 0.0,
            "duplicate_attempts": 0.0,
            "active_booking_count": 0.0,
            "overlapping_trip_count": 0.0,
            "conflicting_journey_attempts": 0.0,
            "distinct_routes_last_hour": 1.0,
            "seconds_since_previous_booking": 999999.0,
        }

    # 1. Recent confirmed and pending bookings for these NICs
    recent_bookings = (
        db.query(Booking)
        .join(BookingPassenger, Booking.id == BookingPassenger.booking_id)
        .join(Passenger, BookingPassenger.passenger_id == Passenger.id)
        .filter(Passenger.nic_hash.in_(nic_hashes))
        .all()
    )

    b_1m = 0
    b_10m = 0
    b_24h = 0
    active_count = 0
    latest_created: datetime | None = None
    routes_1h = set()

    for b in recent_bookings:
        if b.status == BookingStatus.CONFIRMED:
            active_count += 1

        b_created = b.created_at
        if b_created is not None:
            if b_created.tzinfo is None:
                b_created = b_created.replace(tzinfo=timezone.utc)
            if b_created >= t_1m:
                b_1m += 1
            if b_created >= t_10m:
                b_10m += 1
            if b_created >= t_24h:
                b_24h += 1
            if b_created >= (now - timedelta(hours=1)):
                routes_1h.add((b.from_station, b.to_station))

            if latest_created is None or b_created > latest_created:
                latest_created = b_created

    sec_since_prev = (now - latest_created).total_seconds() if latest_created else 999999.0
    sec_since_prev = max(0.0, sec_since_prev)

    # 2. Recent cancellations for these NICs
    canc_count = (
        db.query(func.count(CancellationRequest.id))
        .join(Booking, CancellationRequest.booking_id == Booking.id)
        .join(BookingPassenger, Booking.id == BookingPassenger.booking_id)
        .join(Passenger, BookingPassenger.passenger_id == Passenger.id)
        .filter(
            Passenger.nic_hash.in_(nic_hashes),
            CancellationRequest.created_at >= t_24h,
        )
        .scalar()
        or 0
    )

    # 3. Same-day trips count
    same_day_trips = sum(1 for b in recent_bookings if b.travel_date == schedule.travel_date and b.status == BookingStatus.CONFIRMED)

    # 4. Recent rejected reviews for this passenger
    from database.models import FraudReview, FraudReviewStatus
    rejected_attempts = (
        db.query(func.count(FraudReview.id))
        .filter(
            FraudReview.primary_nic_hash.in_(nic_hashes),
            FraudReview.status == FraudReviewStatus.REJECTED,
            FraudReview.created_at >= t_24h,
        )
        .scalar()
        or 0
    )

    return {
        "bookings_last_1_minute": float(b_1m),
        "bookings_last_10_minutes": float(b_10m),
        "bookings_last_24_hours": float(b_24h),
        "cancellations_last_24_hours": float(canc_count),
        "duplicate_attempts": float(min(rejected_attempts, 5)),
        "active_booking_count": float(active_count),
        "overlapping_trip_count": float(same_day_trips),
        "conflicting_journey_attempts": 0.0,
        "distinct_routes_last_hour": float(max(len(routes_1h), 1)),
        "seconds_since_previous_booking": float(sec_since_prev),
    }
