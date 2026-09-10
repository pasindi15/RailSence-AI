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


class FareNotFoundError(BookingError):
    """Raised when no deterministic fare rule matches the requested route, schedule, or seat class."""

    def __init__(self, route: str, seat_class: str, message: str | None = None):
        msg = message or f"No deterministic fare rule found for route '{route}' and seat class '{seat_class}'."
        super().__init__(msg)
        self.route = route
        self.seat_class = seat_class
