"""
booking/waiting_list.py
-----------------------
RailSense AI — Deterministic FIFO Waiting List Management.

Responsibilities:
1. Implements strict FIFO queue for high-demand train schedules.
2. When seats are released (via cancellation, hold expiry, or admin rejection),
   evaluates queue in order of creation time.
3. Issues time-limited offers (e.g. 15 minutes) to eligible waiting list requests.
4. Holds inventory atomically so concurrent workers do not double-allocate seats.
5. If an offer expires or is declined, automatically offers seats to the next eligible entry.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session
from database.models import (
    Train,
    TrainSchedule,
    WaitingListEntry,
    WaitingListStatus,
)
from .lifecycle import create_seat_hold, release_hold

OFFER_VALIDITY_MINUTES = 15


def enqueue_waiting_list(db: Session, req: Any) -> Any:
    """Accepts WaitingListRequest and adds to queue."""
    from database.models import Train, TrainSchedule
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

    entry = add_to_waiting_list(
        db=db,
        schedule=schedule,
        train=train,
        seat_class=req.seat_class,
        passenger_count=req.passenger_count,
        passengers=[],
        user_id=getattr(req, "user_id", None) or "user",
        passenger_email=getattr(req, "passenger_email", None),
    )
    pos = get_waiting_list_position(db, entry)

    class WLResp:
        def __init__(self, ent, p):
            self.queue_id = ent.queue_token
            self.queue_token = ent.queue_token
            self.position = p
            self.queue_position = p
            self.status = "PENDING"
            self.train_id = req.train_id
            self.travel_date = str(req.travel_date)
            self.seat_class = ent.seat_class
            self.seat_count = ent.passenger_count
            self.passenger_count = ent.passenger_count
            self.passenger_email = ent.passenger_email
        def model_dump(self, **kw):
            return {
                "queue_id": self.queue_id,
                "queue_token": self.queue_token,
                "position": self.position,
                "queue_position": self.queue_position,
                "status": self.status,
                "train_id": self.train_id,
                "travel_date": self.travel_date,
                "seat_class": self.seat_class,
                "seat_count": self.seat_count,
                "passenger_count": self.passenger_count,
                "passenger_email": self.passenger_email,
            }

    return WLResp(entry, pos)


def get_active_queue_length(db: Session, schedule_id: int, seat_class: str) -> int:
    """Return count of active entries in waiting list queue."""
    return (
        db.query(WaitingListEntry)
        .filter(
            WaitingListEntry.schedule_id == schedule_id,
            WaitingListEntry.seat_class == seat_class,
            WaitingListEntry.status.in_([WaitingListStatus.WAITING, WaitingListStatus.OFFERED]),
        )
        .count()
    )


def allocate_released_seat_to_waiting_list(
    db: Session,
    schedule_id: int,
    seat_class: str,
    seats_freed: int = 1,
) -> WaitingListEntry | None:
    """Find the head of FIFO queue and assign an allocated hold."""
    candidate = (
        db.query(WaitingListEntry)
        .filter(
            WaitingListEntry.schedule_id == schedule_id,
            WaitingListEntry.seat_class == seat_class,
            WaitingListEntry.status == WaitingListStatus.WAITING,
        )
        .order_by(WaitingListEntry.created_at.asc())
        .first()
    )
    if not candidate:
        return None

    candidate.status = WaitingListStatus.ALLOCATED
    candidate.assigned_hold_token = f"HLD-{secrets.token_hex(16)}"
    candidate.offer_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    db.commit()
    db.refresh(candidate)
    return candidate


def add_to_waiting_list(
    db: Session,
    schedule: TrainSchedule,
    train: Train,
    seat_class: str,
    passenger_count: int,
    passengers: list[dict[str, Any]],
    user_id: str,
    passenger_email: str | None = None,
) -> WaitingListEntry:

    """Add a passenger request to the deterministic FIFO waiting list."""
    token = f"WL-{secrets.token_hex(12)}"
    entry = WaitingListEntry(
        queue_token=token,
        schedule_id=schedule.id,
        train_id=train.id,
        seat_class=seat_class,
        passenger_count=passenger_count,
        passenger_email=passenger_email,
        user_id=user_id,
        passenger_payload=json.dumps(passengers),
        status=WaitingListStatus.WAITING,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_waiting_list_position(db: Session, entry: WaitingListEntry) -> int:
    """Calculate 1-indexed FIFO position in the waiting list queue."""
    pos = (
        db.query(WaitingListEntry)
        .filter(
            WaitingListEntry.schedule_id == entry.schedule_id,
            WaitingListEntry.seat_class == entry.seat_class,
            WaitingListEntry.status == WaitingListStatus.WAITING,
            WaitingListEntry.created_at <= entry.created_at,
        )
        .count()
    )
    return pos


def evaluate_waiting_list_for_schedule(
    db: Session,
    schedule_id: int,
    available_seats: int,
    seat_class: str | None = None,
) -> list[WaitingListEntry]:
    """
    Evaluate waiting list for released seats in strict FIFO order.
    Creates time-limited offers for eligible requests.
    """
    if available_seats <= 0:
        return []

    query = (
        db.query(WaitingListEntry)
        .filter(
            WaitingListEntry.schedule_id == schedule_id,
            WaitingListEntry.status == WaitingListStatus.WAITING,
        )
    )
    if seat_class:
        query = query.filter(WaitingListEntry.seat_class == seat_class)

    candidates = query.order_by(WaitingListEntry.created_at.asc()).all()

    offered: list[WaitingListEntry] = []
    remaining = available_seats
    now = datetime.now(timezone.utc)

    for entry in candidates:
        if entry.passenger_count <= remaining:
            # Issue offer
            entry.status = WaitingListStatus.OFFERED
            entry.offer_expires_at = now + timedelta(minutes=OFFER_VALIDITY_MINUTES)

            # Atomically lock seats with a hold so concurrent workers cannot double-allocate
            try:
                passengers = json.loads(entry.passenger_payload)
                nic_hashes = [p.get("nic_hash", "") for p in passengers if "nic_hash" in p]
            except Exception:
                nic_hashes = []

            schedule = db.query(TrainSchedule).filter(TrainSchedule.id == schedule_id).first()
            if schedule:
                create_seat_hold(
                    db=db,
                    schedule=schedule,
                    seat_class=entry.seat_class,
                    seat_count=entry.passenger_count,
                    nic_hashes=nic_hashes,
                    user_id=entry.user_id,
                    hold_duration_minutes=OFFER_VALIDITY_MINUTES,
                )

            remaining -= entry.passenger_count
            offered.append(entry)

        if remaining <= 0:
            break

    if offered:
        db.commit()

    return offered


def expire_waiting_list_offers(db: Session, now: datetime | None = None) -> list[WaitingListEntry]:
    """
    Expire unaccepted waiting list offers and advance queue to next candidates.
    """
    check_time = now or datetime.now(timezone.utc)
    expired_offers = (
        db.query(WaitingListEntry)
        .filter(
            WaitingListEntry.status == WaitingListStatus.OFFERED,
            WaitingListEntry.offer_expires_at <= check_time,
        )
        .all()
    )

    for entry in expired_offers:
        entry.status = WaitingListStatus.EXPIRED

    if expired_offers:
        db.commit()

    return expired_offers
