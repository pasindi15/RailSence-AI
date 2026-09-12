"""
booking/exceptions.py
--------------------
Domain-level exceptions for the Booking Agent.

Design intent
-------------
Shields API users and upstream agents from raw database or SQLAlchemy errors.
All domain-specific errors inherit from `BookingError`.
"""

from __future__ import annotations


class BookingError(Exception):
    """Base exception for all booking-agent domain errors."""

    def __init__(self, message: str = "A booking processing error occurred."):
        super().__init__(message)
        self.message = message


class TrainNotFoundError(BookingError):
    """Raised when the requested train does not exist or is inactive."""

    def __init__(self, train_id: str, message: str | None = None):
        msg = message or f"Train service '{train_id}' was not found or is inactive."
        super().__init__(msg)
        self.train_id = train_id


class ScheduleNotFoundError(BookingError):
    """Raised when no schedule matches the train, date, and route."""

    def __init__(self, train_id: str, travel_date: str, route: str = ""):
        super().__init__(
            f"No schedule found for train '{train_id}' on {travel_date}"
            + (f" along '{route}'." if route else ".")
        )
        self.train_id = train_id
        self.travel_date = travel_date
        self.route = route


class SeatsUnavailableError(BookingError):
    """Raised when requested seats exceed available capacity."""

    def __init__(self, seat_class: str, requested: int, available: int = 0):
        super().__init__(
            f"Not enough seats available in {seat_class} "
            f"(requested: {requested}, available: {available})."
        )
        self.seat_class = seat_class
        self.requested = requested
        self.available = available


class InvalidBookingError(BookingError):
    """Raised when booking request parameters are invalid or conflict with business rules."""

    pass


class DuplicateNICInBookingError(InvalidBookingError):
    """Raised when the same NIC is submitted for more than one passenger in a single booking."""

    def __init__(self, detail: str = "DUPLICATE_NIC_IN_BOOKING", message: str | None = None, code: str = "DUPLICATE_NIC_IN_BOOKING", status_code: int = 400):
        msg = message or f"DUPLICATE_NIC_IN_BOOKING: Each passenger in a booking must provide a distinct NIC."
        super().__init__(msg)
        self.code = code
        self.message = msg
        self.status_code = status_code


class DuplicateActiveTicketError(InvalidBookingError):
    """Raised when an active confirmed ticket already exists for the same passenger NIC on the same train & journey."""

    def __init__(self, train_name: str = "selected train", travel_date: Any = "", message: str | None = None, code: str = "DUPLICATE_ACTIVE_TICKET", status_code: int = 409):
        date_str = travel_date.isoformat() if hasattr(travel_date, "isoformat") else str(travel_date)
        msg = message or f"DUPLICATE_ACTIVE_TICKET: A passenger in this request already holds an active confirmed ticket for train '{train_name}' on {date_str}."
        super().__init__(msg)
        self.code = code
        self.message = msg
        self.status_code = status_code


class ConflictingActiveJourneyError(InvalidBookingError):
    """Raised when an active confirmed journey exists on any train that conflicts in time with the requested trip."""

    def __init__(self, existing_train: str = "other train", existing_window: str = "", requested_window: str = "", message: str | None = None, code: str = "CONFLICTING_ACTIVE_JOURNEY", status_code: int = 409):
        msg = message or f"CONFLICTING_ACTIVE_JOURNEY: Passenger already has an active confirmed journey on train '{existing_train}' ({existing_window}) which conflicts with requested interval ({requested_window})."
        super().__init__(msg)
        self.code = code
        self.message = msg
        self.status_code = status_code


class FareNotFoundError(BookingError):
    """Raised when no deterministic fare rule matches the requested route, schedule, or seat class."""

    def __init__(self, route: str, seat_class: str, message: str | None = None):
        msg = message or f"No deterministic fare rule found for route '{route}' and seat class '{seat_class}'."
        super().__init__(msg)
        self.route = route
        self.seat_class = seat_class
