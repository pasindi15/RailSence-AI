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
) -> Booking:
    """
    Persist a new confirmed booking record into the database.

    Parameters
    ----------
    db:                SQLAlchemy database session.
    request:           Validated BookingRequest payload.
    schedule:          TrainSchedule instance corresponding to the booking.
    booking_reference: Generated unique booking reference string (optional; generated if absent).
    fare:              Calculated fare amount (Decimal).
    user_id:           Identifier of the booking owner / passenger.

    Returns
    -------
    Booking: Newly created and committed Booking ORM instance with status CONFIRMED.
    """
    ref = booking_reference
    if not ref:
        # Collision-resistant generation
        for _ in range(10):
            candidate = generate_booking_reference()
            existing = db.query(Booking).filter(Booking.booking_reference == candidate).first()
            if not existing:
                ref = candidate
                break
        if not ref:
            ref = f"RS-{secrets.randbelow(900000) + 100000}"

    resolved_fare = fare if fare is not None else Decimal("0.00")
    # Phase 3 development note: 'guest_passenger' safely remains as the temporary default when omitted.
    # In Phase 4, the Passenger Agent authentication layer should pass the real authenticated passenger user_id.
    resolved_user = user_id or getattr(request, "user_id", None) or "guest_passenger"

    booking = Booking(
        booking_reference=ref,
        user_id=resolved_user,
        train_id=schedule.train_id,
        schedule_id=schedule.id,
        from_station=request.from_station.strip(),
        to_station=request.to_station.strip(),
        travel_date=request.travel_date,
        seat_class=normalize_seat_class(request.seat_class),
        passenger_count=request.passenger_count,
        passenger_email=str(request.passenger_email).strip() if getattr(request, "passenger_email", None) else None,
        fare=resolved_fare,
        status=BookingStatus.CONFIRMED,
    )

    try:
        from database.models import Passenger, BookingPassenger
        db.add(booking)
        db.flush()

        # Link passenger records to booking_passengers
        p_list = passenger_records
        if not p_list and hasattr(request, "passengers") and request.passengers:
            from shared.nic import hash_nic, mask_nic
            p_list = [
                {"name": p.name, "nic_hash": hash_nic(p.nic), "nic_masked": mask_nic(p.nic)}
                for p in request.passengers
            ]

        if p_list:
            for p_info in p_list:
                p_hash = p_info["nic_hash"]
                p_masked = p_info["nic_masked"]
                p_name = p_info.get("name")

                passenger = db.query(Passenger).filter(Passenger.nic_hash == p_hash).first()
                if not passenger:
                    passenger = Passenger(
                        nic_hash=p_hash,
                        nic_masked=p_masked,
                        full_name=p_name,
                    )
                    db.add(passenger)
                    db.flush()

                bp = BookingPassenger(
                    booking_id=booking.id,
                    passenger_id=passenger.id,
                )
                db.add(bp)

        db.commit()
        db.refresh(booking)
        return booking
    except Exception:
        db.rollback()
        raise

