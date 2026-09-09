"""
booking package
---------------
Core business-logic package for the Booking & Reservation Agent (Phase 3).
"""

from .exceptions import (
    BookingError,
    FareNotFoundError,
    InvalidBookingError,
    ScheduleNotFoundError,
    SeatsUnavailableError,
    TrainNotFoundError,
)
from .fare import FareBreakdown, calculate_fare, get_fare_per_passenger
from .service import BookingService

__all__ = [
    "BookingError",
    "BookingService",
    "FareBreakdown",
    "FareNotFoundError",
    "InvalidBookingError",
    "ScheduleNotFoundError",
    "SeatsUnavailableError",
    "TrainNotFoundError",
    "calculate_fare",
    "get_fare_per_passenger",
]
