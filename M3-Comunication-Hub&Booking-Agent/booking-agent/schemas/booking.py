"""
schemas/booking.py
------------------
Pydantic v2 schema for a completed booking request.

Design intent
-------------
BookingRequest represents the FINAL, fully-validated payload that arrives
after the passenger has filled in every required field on the booking page.
All fields are therefore mandatory; the agent must not invent or guess any
missing information.

Phase 1 note
------------
No fare calculation, availability check, or database operations are performed
here.  Pure data validation only.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator


class BookingRequest(BaseModel):
    """
    Fully-completed booking request submitted by the passenger.

    Attributes
    ----------
    from_station:    Departure station name.
    to_station:      Arrival station name.
    travel_date:     Date of travel (must not be in the past).
    train_id:        Unique identifier of the selected train service.
    seat_class:      Passenger class (e.g. "First Class", "Second Class").
    passenger_count: Number of passengers (1–10 inclusive).
    """

    from_station:    str  = Field(..., min_length=1, description="Departure station name")
    to_station:      str  = Field(..., min_length=1, description="Arrival station name")
    travel_date:     date = Field(...,               description="Date of travel")
    train_id:        str  = Field(..., min_length=1, description="Train service identifier")
    seat_class:      str  = Field(..., min_length=1, description="Seat/class type")
    passenger_count: int  = Field(..., ge=1, le=10,  description="Number of passengers (1–10)")

    model_config = {"str_strip_whitespace": True}

    # ------------------------------------------------------------------
    # Field validators
    # ------------------------------------------------------------------

    @field_validator("travel_date")
    @classmethod
    def travel_date_not_in_past(cls, v: date) -> date:
        """Reject travel dates that are strictly in the past."""
        from datetime import date as _date
        if v < _date.today():
            raise ValueError("travel_date must be today or a future date")
        return v
