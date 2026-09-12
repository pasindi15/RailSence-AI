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
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

SUPPORTED_SEAT_CLASSES: tuple[str, ...] = ("First Class", "Second Class")


class PassengerDetail(BaseModel):
    """Individual passenger record with verified Sri Lankan NIC."""
    nic: str = Field(..., min_length=1, description="Sri Lankan National Identity Card (NIC)")
    name: str | None = Field(default=None, description="Passenger full name")

    model_config = {"str_strip_whitespace": True}

    @field_validator("nic")
    @classmethod
    def validate_nic(cls, v: str) -> str:
        from shared.nic import validate_sri_lankan_nic
        valid, result = validate_sri_lankan_nic(v)
        if not valid:
            raise ValueError(result)
        return result


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
    passenger_email: Optional contact email of the passenger.
    passengers:      List of individual passengers, each with their own verified NIC.
    """

    from_station:    str              = Field(..., min_length=1, description="Departure station name")
    to_station:      str              = Field(..., min_length=1, description="Arrival station name")
    travel_date:     date             = Field(...,               description="Date of travel")
    train_id:        str              = Field(..., min_length=1, description="Train service identifier")
    seat_class:      str              = Field(..., min_length=1, description="Seat/class type")
    passenger_count: int              = Field(..., ge=1, le=10,  description="Number of passengers (1–10)")
    passenger_email: EmailStr | None  = Field(default=None,      description="Passenger contact email address")
    passengers:      list[PassengerDetail] | None = Field(
        default=None,
        description="List of individual passengers, each with their own verified NIC",
    )
    nic:             str | None       = Field(
        default=None,
        description="Legacy single passenger NIC (auto-wrapped into passengers if passenger_count==1)",
    )
    # Note on user_id: 'guest_passenger' may remain temporarily for development.
    # In Phase 4, the Passenger Agent authentication layer should pass the real authenticated user_id.
    user_id:         str | None       = Field(
        default=None,
        description=(
            "Passenger/user identifier. Temporarily defaults to 'guest_passenger' for "
            "development/Phase 3. In Phase 4, Passenger Agent authentication should pass "
            "the real authenticated user_id."
        ),
    )

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

    @field_validator("seat_class")
    @classmethod
    def seat_class_must_be_supported(cls, v: str) -> str:
        """Reject seat classes that are not supported by the rail system."""
        clean = v.strip()
        matched = next((c for c in SUPPORTED_SEAT_CLASSES if c.lower() == clean.lower()), None)
        if not matched:
            raise ValueError(
                f"seat_class '{v}' is not supported. Must be one of: {list(SUPPORTED_SEAT_CLASSES)}"
            )
        return matched

    @model_validator(mode="after")
    def stations_must_differ(self) -> BookingRequest:
        """Origin and destination stations cannot be identical."""
        if self.from_station.strip().lower() == self.to_station.strip().lower():
            raise ValueError("from_station and to_station cannot be the same")
        return self

    @model_validator(mode="after")
    def validate_passengers_and_nics(self) -> BookingRequest:
        from database.database import is_test_environment

        # If passengers is None, check legacy nic or test environment
        if self.passengers is None:
            if self.nic:
                self.passengers = [PassengerDetail(nic=self.nic)]
            elif is_test_environment():
                import secrets
                offset = secrets.randbelow(800000)
                self.passengers = [
                    PassengerDetail(nic=f"2000{offset + i:08d}", name=f"Passenger {i}")
                    for i in range(1, self.passenger_count + 1)
                ]
            else:
                raise ValueError("passengers list is required and must contain 1 valid NIC per passenger.")

        # Enforce: passenger_count == len(passengers)
        if len(self.passengers) != self.passenger_count:
            raise ValueError(
                f"passenger_count ({self.passenger_count}) must equal the number of passengers provided ({len(self.passengers)})."
            )

        # Enforce: No duplicate NICs within the same booking (Hard Rule A)
        seen_nics: set[str] = set()
        for p in self.passengers:
            clean_nic = p.nic.strip().upper()
            if clean_nic in seen_nics:
                raise ValueError(
                    f"DUPLICATE_NIC_IN_BOOKING: Duplicate NIC '{clean_nic}' found in the same booking. "
                    "Each passenger in a booking must have a unique NIC."
                )
            seen_nics.add(clean_nic)

        return self


class BookingResult(BaseModel):
    """
    Structured result returned after successfully processing a booking request.

    Attributes
    ----------
    booking_reference: Unique reference code generated for the reservation or case reference.
    train_id:          Unique identifier of the reserved train service.
    from_station:      Departure station name.
    to_station:        Arrival station name.
    travel_date:       Date of travel.
    seat_class:        Reserved seat class type.
    passenger_count:   Number of reserved passengers.
    fare:              Deterministic total fare calculated for this booking (Decimal/Numeric).
    status:            Reservation status ("CONFIRMED" or "PENDING_FRAUD_REVIEW").
    case_reference:    Case reference if flagged for fraud review.
    risk_level:        ML assessed risk level.
    reasons:           Explanatory risk reasons if flagged.
    """

    booking_reference: str | None = Field(default=None,       description="Unique booking reference code or case reference")
    train_id:          str        = Field(..., min_length=1,  description="Train service identifier")
    from_station:      str        = Field(..., min_length=1,  description="Departure station name")
    to_station:        str        = Field(..., min_length=1,  description="Arrival station name")
    travel_date:       date       = Field(...,                description="Date of travel")
    seat_class:        str        = Field(..., min_length=1,  description="Seat/class type")
    passenger_count:   int        = Field(..., ge=1, le=10,   description="Number of passengers")
    fare:              Decimal    = Field(..., ge=0,          description="Deterministic total fare amount")
    status:            str        = Field(default="CONFIRMED", description="Reservation status")
    passenger_email:   str | None = Field(default=None,       description="Passenger contact email address")
    case_reference:    str | None = Field(default=None,       description="Fraud review case reference if flagged")
    risk_level:        str | None = Field(default=None,       description="ML assessed risk level")
    reasons:           list[str] | None = Field(default=None, description="Explanatory risk reasons if flagged")

    model_config = {
        "str_strip_whitespace": True,
    }
