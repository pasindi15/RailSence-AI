"""
tests/test_phase3_seats.py
--------------------------
RailSense AI — Member C Phase 3 Seat & Class Availability Checking Tests.

Verifies:
  1. capacity = 50, booked = 20, requested = 2  -> available
  2. capacity = 50, booked = 49, requested = 2  -> unavailable (SeatsUnavailableError)
  3. capacity = 50, booked = 50                 -> unavailable (SeatsUnavailableError, 0 available)
  4. Cancelled bookings do not consume capacity
  5. Different seat classes do not consume each other's capacity
  6. Bookings on different schedules do not affect the target schedule
  7. Centralized normalization of seat classes ("first", "2nd", "Second Class")
  8. Boundary: capacity = 50, booked = 48, requested = 2 -> available (0 remaining)
  9. Safe error reporting on SeatsUnavailableError (requested, available attributes)
"""

from __future__ import annotations

import os
import sys
from datetime import date, time
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
MEMBER_C = os.path.dirname(os.path.dirname(__file__))
BOOKING_AGENT = os.path.join(MEMBER_C, "booking-agent")

for p in (MEMBER_C, BOOKING_AGENT):
    if p not in sys.path:
        sys.path.insert(0, p)

from database.models import Base, Booking, BookingStatus, Train, TrainSchedule
from booking import (
    BookingService,
    InvalidBookingError,
    SeatsUnavailableError,
)
from booking.availability import (
    check_seat_availability,
    get_available_seats,
    get_booked_seats,
    normalize_seat_class,
)

# ---------------------------------------------------------------------------
# Isolated SQLite In-Memory Database for Tests
# ---------------------------------------------------------------------------
TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture
def db_session():
    """Create fresh database tables in memory and tear down after each test."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture
def seat_test_data(db_session):
    """
    Setup standard test schedule:
    - Train 'PM-5000'
    - Schedule 1: Colombo -> Kandy, First Class cap=50, Second Class cap=50
    - Schedule 2: Colombo -> Galle (different schedule for isolation testing)
    """
    train = Train(train_id="PM-5000", train_name="City Express", active=True)
    db_session.add(train)
    db_session.flush()

    sched1 = TrainSchedule(
        train_id=train.id,
        from_station="Colombo",
        to_station="Kandy",
        travel_date=date(2026, 12, 15),
        departure_time=time(8, 0),
        arrival_time=time(11, 0),
        first_class_capacity=50,
        second_class_capacity=50,
    )
    sched2 = TrainSchedule(
        train_id=train.id,
        from_station="Colombo",
        to_station="Galle",
        travel_date=date(2026, 12, 15),
        departure_time=time(14, 0),
        arrival_time=time(16, 30),
        first_class_capacity=50,
        second_class_capacity=50,
    )
    db_session.add_all([sched1, sched2])
    db_session.commit()

    return {"train": train, "schedule_1": sched1, "schedule_2": sched2}


def _create_booking(
    db_session,
    schedule_id: int,
    train_id: int,
    seat_class: str,
    passenger_count: int,
    status: BookingStatus = BookingStatus.CONFIRMED,
    ref: str = "BK-TEST",
) -> Booking:
    """Helper to persist a test booking."""
    b = Booking(
        booking_reference=ref,
        user_id="test_user",
        train_id=train_id,
        schedule_id=schedule_id,
        from_station="Colombo",
        to_station="Kandy",
        travel_date=date(2026, 12, 15),
        seat_class=seat_class,
        passenger_count=passenger_count,
        fare=Decimal("500.00"),
        status=status,
    )
    db_session.add(b)
    db_session.commit()
    return b


# ===========================================================================
# Unit Tests for Seat Availability
# ===========================================================================

class TestSeatAvailability:

    def test_case_1_capacity_50_booked_20_requested_2_available(
        self, db_session, seat_test_data
    ):
        """capacity = 50, booked = 20, requested = 2 -> available (remaining = 30)."""
        sched = seat_test_data["schedule_1"]
        train = seat_test_data["train"]

        _create_booking(
            db_session,
            schedule_id=sched.id,
            train_id=train.id,
            seat_class="First Class",
            passenger_count=20,
            status=BookingStatus.CONFIRMED,
            ref="BK-001",
        )

        assert get_booked_seats(db_session, sched.id, "First Class") == 20
        assert get_available_seats(db_session, sched, "First Class") == 30

        # Request 2 seats -> succeeds
        avail = check_seat_availability(
            db_session, sched, seat_class="First Class", requested_seats=2
        )
        assert avail == 30

        # Also verify via BookingService orchestrator
        service = BookingService(db_session)
        assert service.check_availability(sched, "First Class", 2) == 30

    def test_case_2_capacity_50_booked_49_requested_2_unavailable(
        self, db_session, seat_test_data
    ):
        """capacity = 50, booked = 49, requested = 2 -> unavailable (only 1 left)."""
        sched = seat_test_data["schedule_1"]
        train = seat_test_data["train"]

        _create_booking(
            db_session,
            schedule_id=sched.id,
            train_id=train.id,
            seat_class="First Class",
            passenger_count=49,
            status=BookingStatus.CONFIRMED,
            ref="BK-002",
        )

        assert get_available_seats(db_session, sched, "First Class") == 1

        with pytest.raises(SeatsUnavailableError) as exc_info:
            check_seat_availability(
                db_session, sched, seat_class="First Class", requested_seats=2
            )

        err = exc_info.value
        assert err.seat_class == "First Class"
        assert err.requested == 2
        assert err.available == 1
        assert "requested: 2, available: 1" in str(err)

    def test_case_3_capacity_50_booked_50_unavailable(
        self, db_session, seat_test_data
    ):
        """capacity = 50, booked = 50 -> unavailable (0 seats left)."""
        sched = seat_test_data["schedule_1"]
        train = seat_test_data["train"]

        _create_booking(
            db_session,
            schedule_id=sched.id,
            train_id=train.id,
            seat_class="First Class",
            passenger_count=50,
            status=BookingStatus.CONFIRMED,
            ref="BK-003",
        )

        assert get_available_seats(db_session, sched, "First Class") == 0

        with pytest.raises(SeatsUnavailableError) as exc_info:
            check_seat_availability(
                db_session, sched, seat_class="First Class", requested_seats=1
            )

        err = exc_info.value
        assert err.available == 0
        assert err.requested == 1

    def test_cancelled_booking_does_not_consume_seats(
        self, db_session, seat_test_data
    ):
        """Cancelled bookings must NOT reduce available capacity."""
        sched = seat_test_data["schedule_1"]
        train = seat_test_data["train"]

        # 20 confirmed seats
        _create_booking(
            db_session,
            schedule_id=sched.id,
            train_id=train.id,
            seat_class="First Class",
            passenger_count=20,
            status=BookingStatus.CONFIRMED,
            ref="BK-CONF",
        )

        # 25 CANCELLED seats
        _create_booking(
            db_session,
            schedule_id=sched.id,
            train_id=train.id,
            seat_class="First Class",
            passenger_count=25,
            status=BookingStatus.CANCELLED,
            ref="BK-CANC",
        )

        # Booked seats should only be 20 (NOT 45)
        booked = get_booked_seats(db_session, sched.id, "First Class")
        assert booked == 20

        # Available seats should be 50 - 20 = 30
        available = get_available_seats(db_session, sched, "First Class")
        assert available == 30

        # Requesting 15 seats should succeed
        assert check_seat_availability(db_session, sched, "First Class", 15) == 30

    def test_different_seat_class_does_not_consume_requested_capacity(
        self, db_session, seat_test_data
    ):
        """Bookings in First Class must not reduce Second Class capacity."""
        sched = seat_test_data["schedule_1"]
        train = seat_test_data["train"]

        # Completely fill First Class (50 seats)
        _create_booking(
            db_session,
            schedule_id=sched.id,
            train_id=train.id,
            seat_class="First Class",
            passenger_count=50,
            status=BookingStatus.CONFIRMED,
            ref="BK-FC-FULL",
        )

        # Second Class must still have full 50 seats available
        assert get_available_seats(db_session, sched, "First Class") == 0
        assert get_available_seats(db_session, sched, "Second Class") == 50

        # Requesting 20 Second Class seats succeeds
        assert check_seat_availability(db_session, sched, "Second Class", 20) == 50

    def test_different_schedule_does_not_affect_target_schedule(
        self, db_session, seat_test_data
    ):
        """Bookings on schedule 2 must not affect available seats on schedule 1."""
        sched1 = seat_test_data["schedule_1"]
        sched2 = seat_test_data["schedule_2"]
        train = seat_test_data["train"]

        # Completely fill schedule 2
        _create_booking(
            db_session,
            schedule_id=sched2.id,
            train_id=train.id,
            seat_class="First Class",
            passenger_count=50,
            status=BookingStatus.CONFIRMED,
            ref="BK-SCHED2",
        )

        # Schedule 2 is full
        assert get_available_seats(db_session, sched2, "First Class") == 0

        # Schedule 1 is completely untouched
        assert get_available_seats(db_session, sched1, "First Class") == 50
        assert check_seat_availability(db_session, sched1, "First Class", 5) == 50

    def test_exact_boundary_condition(self, db_session, seat_test_data):
        """capacity = 50, booked = 48, requested = 2 -> available (exactly 0 left)."""
        sched = seat_test_data["schedule_1"]
        train = seat_test_data["train"]

        _create_booking(
            db_session,
            schedule_id=sched.id,
            train_id=train.id,
            seat_class="Second Class",
            passenger_count=48,
            status=BookingStatus.CONFIRMED,
            ref="BK-BOUND",
        )

        # Requesting exact remaining seats (2) succeeds
        assert check_seat_availability(db_session, sched, "Second Class", 2) == 2

    def test_seat_class_normalization(self):
        """Test centralized normalization of seat classes."""
        assert normalize_seat_class("First Class") == "First Class"
        assert normalize_seat_class("first class") == "First Class"
        assert normalize_seat_class("FIRST") == "First Class"
        assert normalize_seat_class("1st") == "First Class"
        assert normalize_seat_class("1st class") == "First Class"

        assert normalize_seat_class("Second Class") == "Second Class"
        assert normalize_seat_class("second class") == "Second Class"
        assert normalize_seat_class("2nd") == "Second Class"
        assert normalize_seat_class("2nd class") == "Second Class"

        with pytest.raises(InvalidBookingError):
            normalize_seat_class("Economy")
        with pytest.raises(InvalidBookingError):
            normalize_seat_class("")

    def test_invalid_requested_seats_rejected(self, db_session, seat_test_data):
        """Requested seats < 1 must raise InvalidBookingError."""
        sched = seat_test_data["schedule_1"]
        with pytest.raises(InvalidBookingError):
            check_seat_availability(db_session, sched, "First Class", 0)
        with pytest.raises(InvalidBookingError):
            check_seat_availability(db_session, sched, "First Class", -1)
