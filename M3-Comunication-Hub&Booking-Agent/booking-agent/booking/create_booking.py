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

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from database.models import Booking, TrainSchedule
    from schemas.booking import BookingRequest


def generate_booking_reference() -> str:
    """
    Generate a unique, human-readable booking reference identifier.

    Format: e.g., 'BK-YYYYMMDD-XXXX'

    Returns
    -------
    str: Unique booking reference code.
    """
    raise NotImplementedError("Booking reference generation will be implemented in Phase 3.")


def persist_booking(
    db: Session,
    request: BookingRequest,
    schedule: TrainSchedule,
    booking_reference: str,
    fare: Decimal,
    user_id: str = "guest_user",
) -> Booking:
    """
    Persist a new confirmed booking record into the database.

    Parameters
    ----------
    db:                SQLAlchemy database session.
    request:           Validated BookingRequest payload.
    schedule:          TrainSchedule instance corresponding to the booking.
    booking_reference: Generated unique booking reference string.
    fare:              Calculated fare amount.
    user_id:           Identifier of the booking owner / passenger.

    Returns
    -------
    Booking: Newly created and committed Booking ORM instance.
    """
    raise NotImplementedError("Booking persistence will be implemented in Phase 3.")
