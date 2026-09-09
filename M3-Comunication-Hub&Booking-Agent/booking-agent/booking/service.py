"""
booking/service.py
------------------
Main orchestrator service for the Booking Agent workflow.

Responsibilities (Phase 3):
Orchestrates the deterministic booking pipeline:
1. Validate booking details (BookingRequest)
2. Find train / schedule (availability.get_schedule_for_trip)
3. Check seat availability (availability.check_seat_availability)
4. Calculate fare deterministically (fare.calculate_fare) [upcoming]
5. Generate reference and persist reservation (create_booking.persist_booking) [upcoming]
6. Return structured confirmation (BookingResult) [upcoming]

Architectural & Concurrency rules:
- No LLM involvement in booking availability, seat queries, fare calculation, or booking references.
- Dynamic derived availability: capacity minus sum(CONFIRMED bookings).
- Concurrency: When implementing full reservation persistence in step 5, seat checking
  and booking persistence should execute within the same database transaction.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from .availability import (
    check_seat_availability,
    get_available_seats,
    get_schedule_for_trip,
    get_train_by_public_id,
    validate_booking_details,
)
from .fare import FareBreakdown, calculate_fare

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from database.models import Train, TrainSchedule
    from schemas.booking import BookingRequest, BookingResult


class BookingService:
    """Orchestrates end-to-end booking reservation operations."""

    def __init__(self, db: Session):
        self.db = db

    def validate_request(self, request: BookingRequest) -> None:
        """
        Validate business rules for a booking request.

        Raises
        ------
        InvalidBookingError: If business validation rules fail.
        """
        validate_booking_details(request)

    def find_train(self, train_id: str) -> Train:
        """
        Look up an active train by its public train_id.

        Raises
        ------
        TrainNotFoundError: If the train is not found or is inactive.
        """
        return get_train_by_public_id(self.db, train_id)

    def find_schedule(
        self,
        train_id: str,
        from_station: str,
        to_station: str,
        travel_date: date,
    ) -> TrainSchedule:
        """
        Look up a matching schedule for a train, route, and travel date.

        Raises
        ------
        TrainNotFoundError: If train does not exist or is inactive.
        ScheduleNotFoundError: If no matching schedule exists.
        """
        return get_schedule_for_trip(
            self.db,
            train_id=train_id,
            from_station=from_station,
            to_station=to_station,
            travel_date=travel_date,
        )

    def check_availability(
        self,
        schedule: TrainSchedule | int,
        seat_class: str,
        passenger_count: int,
    ) -> int:
        """
        Verify seat availability on the schedule for the requested class.

        Returns
        -------
        int: Remaining available seats.

        Raises
        ------
        SeatsUnavailableError: If available_seats < passenger_count.
        """
        return check_seat_availability(
            self.db,
            schedule=schedule,
            seat_class=seat_class,
            requested_seats=passenger_count,
        )

    def get_remaining_seats(
        self,
        schedule: TrainSchedule,
        seat_class: str,
    ) -> int:
        """Calculate remaining available seats for a schedule and class."""
        return get_available_seats(self.db, schedule=schedule, seat_class=seat_class)

    def compute_fare(
        self,
        from_station: str,
        to_station: str,
        seat_class: str,
        passenger_count: int,
        schedule: TrainSchedule | None = None,
    ) -> FareBreakdown:
        """
        Calculate deterministic fare for the given route, class, and passenger count.

        Raises
        ------
        FareNotFoundError: If no matching fare rule exists.
        InvalidBookingError: If parameters are invalid.
        """
        return calculate_fare(
            from_station=from_station,
            to_station=to_station,
            seat_class=seat_class,
            passenger_count=passenger_count,
            schedule=schedule,
            db=self.db,
        )

    def process_booking(
        self, request: BookingRequest, user_id: str = "guest_user"
    ) -> BookingResult:
        """
        Execute the deterministic booking workflow.
        (Reserved for subsequent Phase 3 steps: fare calculation and persistence)
        """
        raise NotImplementedError(
            "Full booking persistence will be implemented in subsequent Phase 3 steps."
        )
