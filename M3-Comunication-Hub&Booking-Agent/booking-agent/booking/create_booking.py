"""
booking/create_booking.py
-------------------------
Reservation persistence and reference generation for the Booking Agent.

Responsibilities (Phase 3):
- Generate unique, deterministic or structured booking reference codes.
- Persist confirmed booking records into the `bookings` table via SQLAlchemy.
- Return newly created `Booking` ORM model entities.

Note:
Full persistence and collision-resistant reference generation logic will be
implemented in subsequent steps.
"""

from __future__ import annotations

import secrets
from decimal import Decimal
from typing import TYPE_CHECKING

from database.models import Booking, BookingStatus, TrainSchedule
from .availability import normalize_seat_class

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from schemas.booking import BookingRequest


def generate_booking_reference() -> str:
    """
    Generate a unique, human-readable booking reference identifier.

    Format: 'RS-XXXXX' (e.g. 'RS-84521')
    Requirements:
    - Unique
    - 'RS-' prefix
    - Stored separately from database primary key

    Returns
    -------
    str: Unique booking reference code.
    """
    number = secrets.randbelow(90000) + 10000
    return f"RS-{number}"


def persist_booking(
    db: Session,
    request: BookingRequest,
    schedule: TrainSchedule,
    booking_reference: str | None = None,
    fare: Decimal | None = None,
    user_id: str | None = None,
    passenger_records: list[dict] | None = None,
    idempotency_key: str | None = None,
    actor: str | None = None,
    hold_id: int | None = None,
) -> Booking:
    """
    Persist a new confirmed booking record atomically into the database.

    Concurrency & Idempotency Rules:
    - Locks the TrainSchedule row (via with_for_update on PostgreSQL) to serialize seat allocation.
    - Performs final seat capacity verification inside the protected transaction.
    - Generates opaque, unpredictable ticket_token for server-side verified QR issuance.
    - Transitions linked SeatHold (if any) to CONFIRMED.
    - Atomically persists IdempotencyRecord when an idempotency_key is provided.
    """
    from .availability import SeatsUnavailableError, get_available_seats
    from .qr_service import generate_opaque_ticket_token
    from database.models import (
        BookingPassenger,
        HoldStatus,
        IdempotencyRecord,
        IdempotencyStatus,
        Passenger,
        SeatHold,
    )

    # 1. Row-level concurrency lock on schedule
    try:
        locked_schedule = (
            db.query(TrainSchedule)
            .filter(TrainSchedule.id == schedule.id)
            .with_for_update()
            .first()
        )
    except Exception:
        # Fallback for backends that do not support SELECT FOR UPDATE (e.g. SQLite)
        locked_schedule = db.query(TrainSchedule).filter(TrainSchedule.id == schedule.id).first()

    target_schedule = locked_schedule or schedule
    canonical_class = normalize_seat_class(request.seat_class)

    # 2. Re-verify seat capacity inside locked transaction (if not preceded by an active hold)
    if not hold_id:
        avail = get_available_seats(db, schedule=target_schedule, seat_class=canonical_class)
        if avail < request.passenger_count:
            raise SeatsUnavailableError(
                seat_class=canonical_class,
                requested_seats=request.passenger_count,
                available_seats=avail,
                train_id=target_schedule.train.train_id if target_schedule.train else str(target_schedule.train_id),
                travel_date=str(target_schedule.travel_date),
            )

    # 3. Collision-resistant booking reference generation
    ref = booking_reference
    if not ref:
        for _ in range(10):
            candidate = generate_booking_reference()
            existing = db.query(Booking).filter(Booking.booking_reference == candidate).first()
            if not existing:
                ref = candidate
                break
        if not ref:
            ref = f"RS-{secrets.randbelow(900000) + 100000}"

    resolved_fare = fare if fare is not None else Decimal("0.00")
    resolved_user = user_id or getattr(request, "user_id", None) or "guest_passenger"
    ticket_token = generate_opaque_ticket_token()

    booking = Booking(
        booking_reference=ref,
        ticket_token=ticket_token,
        hold_id=hold_id,
        user_id=resolved_user,
        train_id=target_schedule.train_id,
        schedule_id=target_schedule.id,
        from_station=request.from_station.strip(),
        to_station=request.to_station.strip(),
        travel_date=request.travel_date,
        seat_class=canonical_class,
        passenger_count=request.passenger_count,
        passenger_email=str(request.passenger_email).strip() if getattr(request, "passenger_email", None) else None,
        passenger_phone=(str(getattr(request, "contact_phone", None)).strip() if getattr(request, "contact_phone", None) else None),
        fare=resolved_fare,
        status=BookingStatus.CONFIRMED,
    )

    try:
        db.add(booking)
        db.flush()

        # Link passenger records to booking_passengers (batched)
        p_list = passenger_records
        if not p_list and hasattr(request, "passengers") and request.passengers:
            from shared.nic import hash_nic, mask_nic
            p_list = [
                {"name": p.name, "nic_hash": hash_nic(p.nic), "nic_masked": mask_nic(p.nic), "dob": getattr(p, "dob", None)}
                for p in request.passengers
            ]

        # Contact phone from the booking contact details (shared by all passengers on the booking).
        contact_phone = (getattr(request, "contact_phone", None) or None)
        if contact_phone:
            contact_phone = str(contact_phone).strip() or None

        if p_list:
            all_hashes = [p["nic_hash"] for p in p_list]
            existing_pax_map = {
                p.nic_hash: p
                for p in db.query(Passenger).filter(Passenger.nic_hash.in_(all_hashes)).all()
            }
            new_pax = []
            for p_info in p_list:
                p_hash = p_info["nic_hash"]
                if p_hash not in existing_pax_map:
                    p = Passenger(
                        nic_hash=p_hash,
                        nic_masked=p_info["nic_masked"],
                        full_name=p_info.get("name"),
                        phone=contact_phone,
                        dob=p_info.get("dob"),
                    )
                    db.add(p)
                    new_pax.append(p)
                    existing_pax_map[p_hash] = p
                else:
                    # Backfill contact phone / DOB on the existing passenger profile
                    # when this booking provides fresher details.
                    existing = existing_pax_map[p_hash]
                    if contact_phone and not existing.phone:
                        existing.phone = contact_phone
                    p_dob = p_info.get("dob")
                    if p_dob and not existing.dob:
                        existing.dob = p_dob
            if new_pax:
                db.flush()

            for p_info in p_list:
                passenger = existing_pax_map[p_info["nic_hash"]]
                bp = BookingPassenger(
                    booking_id=booking.id,
                    passenger_id=passenger.id,
                )
                db.add(bp)

        # Transition linked seat hold if present
        if hold_id:
            hold = db.query(SeatHold).filter(SeatHold.id == hold_id).first()
            if hold:
                hold.status = HoldStatus.CONFIRMED

        # Persist idempotency record atomically
        if idempotency_key:
            import hashlib
            import json
            payload_repr = {
                "train_id": request.train_id,
                "from_station": request.from_station.strip(),
                "to_station": request.to_station.strip(),
                "travel_date": request.travel_date.isoformat(),
                "seat_class": request.seat_class,
                "passenger_count": request.passenger_count,
                "passenger_email": str(request.passenger_email).strip() if getattr(request, "passenger_email", None) else None,
                "passengers": [{"nic": p.nic, "name": p.name} for p in (request.passengers or [])],
            }
            req_fingerprint = hashlib.sha256(
                json.dumps(payload_repr, sort_keys=True).encode("utf-8")
            ).hexdigest()

            cached_result = {
                "booking_reference": booking.booking_reference,
                "ticket_token": booking.ticket_token,
                "train_id": target_schedule.train.train_id if target_schedule.train else str(target_schedule.train_id),
                "from_station": booking.from_station,
                "to_station": booking.to_station,
                "travel_date": booking.travel_date.isoformat(),
                "seat_class": booking.seat_class,
                "passenger_count": booking.passenger_count,
                "passenger_email": booking.passenger_email,
                "fare": str(booking.fare),
                "status": "CONFIRMED",
                "risk_level": "LOW",
                "hold_token": getattr(request, "hold_token", None),
            }

            idem = db.query(IdempotencyRecord).filter(
                IdempotencyRecord.idempotency_key == idempotency_key
            ).first()
            if not idem:
                idem = IdempotencyRecord(
                    idempotency_key=idempotency_key,
                    actor=actor or resolved_user,
                    operation="create_booking",
                    request_hash=req_fingerprint,
                    status=IdempotencyStatus.COMMITTED,
                    response_payload=json.dumps(cached_result),
                )
                db.add(idem)
            else:
                idem.request_hash = req_fingerprint
                idem.status = IdempotencyStatus.COMMITTED
                idem.response_payload = json.dumps(cached_result)

        db.commit()
        db.refresh(booking)
        return booking
    except Exception:
        db.rollback()
        raise


