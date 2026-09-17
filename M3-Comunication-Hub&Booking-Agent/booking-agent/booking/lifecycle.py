"""
booking/lifecycle.py
--------------------
RailSense AI — Booking Lifecycle & Seat Hold Management.

Responsibilities:
1. Manages temporary seat holds with server-controlled expiry.
2. Prototype hold default: 5 minutes (configurable via HOLD_EXPIRY_MINUTES,
   strictly labeled as a project prototype setting rather than official railway policy).
3. Enforces valid booking-state transitions:
   HELD -> [CONFIRMED, PENDING_FRAUD_REVIEW, EXPIRED, CANCELLED]
   PENDING_FRAUD_REVIEW -> [CONFIRMED, REJECTED, EXPIRED]
   CONFIRMED -> [CANCELLED]
4. Periodic hold expiry worker: releases expired seats safely and triggers waiting-list offers.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session
from database.models import (
    Booking,
    BookingStatus,
    HoldStatus,
    SeatHold,
    TrainSchedule,
)

# Prototype setting (label clearly as project default)
DEFAULT_HOLD_MINUTES = int(os.getenv("HOLD_EXPIRY_MINUTES", "5"))


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal booking or hold state transition is requested."""
    pass


# Allowed state transition graph
ALLOWED_BOOKING_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.HELD: {
        BookingStatus.CONFIRMED,
        BookingStatus.PENDING_FRAUD_REVIEW,
        BookingStatus.EXPIRED,
        BookingStatus.CANCELLED,
    },
    BookingStatus.PENDING_FRAUD_REVIEW: {
        BookingStatus.CONFIRMED,
        BookingStatus.REJECTED,
        BookingStatus.EXPIRED,
    },
    BookingStatus.CONFIRMED: {
        BookingStatus.CANCELLED,
    },
    BookingStatus.CANCELLED: set(),
    BookingStatus.EXPIRED: set(),
    BookingStatus.REJECTED: set(),
}


def validate_booking_transition(
    current_status: BookingStatus | str,
    target_status: BookingStatus | str,
) -> None:
    """Validate that a booking status transition complies with the lifecycle state machine."""
    c_status = BookingStatus(current_status) if isinstance(current_status, str) else current_status
    t_status = BookingStatus(target_status) if isinstance(target_status, str) else target_status

    allowed = ALLOWED_BOOKING_TRANSITIONS.get(c_status, set())
    if t_status not in allowed:
        raise InvalidStateTransitionError(
            f"Illegal booking state transition: {c_status.value} -> {t_status.value}. "
            f"Allowed targets: {[s.value for s in allowed]}"
        )


def create_seat_hold(
    db: Session,
    schedule_or_request: Any,
    seat_class: str | None = None,
    seat_count: int | None = None,
    nic_hashes: list[str] | None = None,
    user_id: str | None = None,
    hold_duration_minutes: int | None = None,
) -> Any:
    """
    Create a server-controlled temporary seat hold record in the database.
    Supports either create_seat_hold(db, SeatHoldRequest) or positional schedule args.
    Hold duration is a project prototype configuration setting (default 5 minutes).
    """
    from schemas.booking import SeatHoldRequest, SeatHoldResponse
    from database.models import Train, TrainSchedule

    if isinstance(schedule_or_request, SeatHoldRequest) or hasattr(schedule_or_request, "train_id"):
        req = schedule_or_request
        train = db.query(Train).filter(Train.train_id == req.train_id).first()
        if not train:
            raise ValueError(f"Train '{req.train_id}' not found.")
        schedule = (
            db.query(TrainSchedule)
            .filter(
                TrainSchedule.train_id == train.id,
                TrainSchedule.travel_date == req.travel_date,
                TrainSchedule.from_station == req.from_station,
                TrainSchedule.to_station == req.to_station,
            )
            .first()
        )
        if not schedule:
            raise ValueError(f"Schedule not found for train '{req.train_id}' on {req.travel_date}.")

        duration = hold_duration_minutes if hold_duration_minutes is not None else DEFAULT_HOLD_MINUTES
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=duration)
        hold_token = f"HLD-{secrets.token_hex(16)}"

        hold = SeatHold(
            hold_token=hold_token,
            schedule_id=schedule.id,
            seat_class=req.seat_class,
            seat_count=req.passenger_count,
            nic_hashes=json.dumps([]),
            user_id=req.user_id or "web_user",
            status=HoldStatus.ACTIVE,
            expires_at=expires_at,
        )
        db.add(hold)
        db.commit()
        db.refresh(hold)

        class HoldResp:
            def __init__(self, h, dur):
                self.hold_token = h.hold_token
                self.expires_at = h.expires_at.isoformat()
                self.duration_seconds = dur * 60
                self.expires_in_seconds = dur * 60
                self.train_id = req.train_id
                self.seat_class = h.seat_class
                self.seat_count = h.seat_count
                self.passenger_count = h.seat_count
                self.status = "ACTIVE"
            def model_dump(self, **kw):
                return {
                    "hold_token": self.hold_token,
                    "expires_at": self.expires_at,
                    "duration_seconds": self.duration_seconds,
                    "expires_in_seconds": self.expires_in_seconds,
                    "train_id": self.train_id,
                    "seat_class": self.seat_class,
                    "seat_count": self.seat_count,
                    "passenger_count": self.passenger_count,
                    "status": self.status,
                }
        return HoldResp(hold, duration)

    # Positional invocation: (db, schedule, seat_class, seat_count, nic_hashes, user_id)
    schedule = schedule_or_request
    duration = hold_duration_minutes if hold_duration_minutes is not None else DEFAULT_HOLD_MINUTES
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=duration)
    hold_token = f"HLD-{secrets.token_hex(16)}"

    hold = SeatHold(
        hold_token=hold_token,
        schedule_id=schedule.id,
        seat_class=seat_class or "Second Class",
        seat_count=seat_count or 1,
        nic_hashes=json.dumps(nic_hashes or []),
        user_id=user_id or "user",
        status=HoldStatus.ACTIVE,
        expires_at=expires_at,
    )
    db.add(hold)
    db.flush()
    return hold


def get_active_hold(db: Session, hold_token: str, now: datetime | None = None) -> SeatHold | None:
    """Retrieve an active unexpired SeatHold by its token."""
    check_time = now or datetime.now(timezone.utc)
    return (
        db.query(SeatHold)
        .filter(
            SeatHold.hold_token == hold_token,
            SeatHold.status == HoldStatus.ACTIVE,
            SeatHold.expires_at > check_time,
        )
        .first()
    )


def release_expired_holds(db: Session, now: datetime | None = None) -> int:
    """Expire overdue holds and return the count of released holds."""
    check_time = now or datetime.now(timezone.utc)
    overdue = (
        db.query(SeatHold)
        .filter(
            SeatHold.status == HoldStatus.ACTIVE,
            SeatHold.expires_at <= check_time,
        )
        .all()
    )
    count = len(overdue)
    for h in overdue:
        h.status = HoldStatus.EXPIRED
    if overdue:
        db.commit()
    return count


def get_held_seats_for_schedule(
    db: Session,
    schedule_id: int,
    seat_class: str,
    now: datetime | None = None,
) -> int:
    """Alias for get_active_hold_seat_count."""
    return get_active_hold_seat_count(db, schedule_id, seat_class, now)



def get_active_hold_seat_count(
    db: Session,
    schedule_id: int,
    seat_class: str,
    now: datetime | None = None,
) -> int:
    """
    Calculate the total number of seats currently reserved under unexpired ACTIVE holds.
    Expired holds are automatically excluded from consuming capacity.
    """
    from sqlalchemy import func
    check_time = now or datetime.now(timezone.utc)
    count = (
        db.query(func.coalesce(func.sum(SeatHold.seat_count), 0))
        .filter(
            SeatHold.schedule_id == schedule_id,
            SeatHold.seat_class == seat_class,
            SeatHold.status == HoldStatus.ACTIVE,
            SeatHold.expires_at > check_time,
        )
        .scalar()
    )
    return int(count or 0)


def expire_overdue_holds(db: Session, now: datetime | None = None) -> list[int]:
    """
    Identify and transition all overdue holds to EXPIRED status.
    Returns list of affected schedule_ids so waiting-list evaluation can be triggered.
    Safe to run repeatedly and recovers overdue holds after server restarts.
    """
    check_time = now or datetime.now(timezone.utc)
    overdue_holds = (
        db.query(SeatHold)
        .filter(
            SeatHold.status == HoldStatus.ACTIVE,
            SeatHold.expires_at <= check_time,
        )
        .all()
    )

    affected_schedule_ids: set[int] = set()
    for hold in overdue_holds:
        hold.status = HoldStatus.EXPIRED
        affected_schedule_ids.add(hold.schedule_id)

    if overdue_holds:
        db.commit()

    return list(affected_schedule_ids)


def release_hold(db: Session, hold_token: str) -> bool:
    """Explicitly release a temporary seat hold, returning capacity to the pool."""
    hold = db.query(SeatHold).filter(SeatHold.hold_token == hold_token).first()
    if not hold or hold.status != HoldStatus.ACTIVE:
        return False
    hold.status = HoldStatus.RELEASED
    db.commit()
    return True
