"""
tests/test_phase3_lookup.py
----------------------------
RailSense AI — Member C Phase 3 Train & Schedule Lookup Tests.

Verifies:
  1. Valid train lookup
  2. Inactive train rejection
  3. Unknown train ID rejection
  4. Valid schedule lookup (with case-insensitive / trimmed station matching)
  5. Wrong route rejection
  6. Wrong travel date rejection
  7. Same origin/destination rejection
  8. Unsupported seat class rejection
  9. Clean domain exceptions without leaking SQL errors
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pytest
from pydantic import ValidationError
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

from database.models import Base
from database.seed import seed_test_train_data
from schemas.booking import BookingRequest
from booking import (
    BookingService,
    InvalidBookingError,
    ScheduleNotFoundError,
    TrainNotFoundError,
)
from booking.availability import (
    get_schedule_for_trip,
    get_train_by_public_id,
    validate_booking_details,
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
    """Create fresh database tables and seed test fixtures in memory."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    session = TestingSession()
    seed_test_train_data(session)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=TEST_ENGINE)


# ===========================================================================
# 1. Train Lookup Tests
# ===========================================================================

class TestTrainLookup:

    def test_valid_train_lookup(self, db_session):
        """Active train 'PM-4082' must be found and return the active Train model."""
        train = get_train_by_public_id(db_session, "PM-4082")
        assert train is not None
        assert train.train_id == "PM-4082"
        assert train.active is True
        assert train.train_name == "Intercity Express"

        # Also verify via BookingService orchestrator
        service = BookingService(db_session)
        service_train = service.find_train("PM-4082")
        assert service_train.id == train.id

    def test_inactive_train_rejected(self, db_session):
        """Inactive train 'INACT-9999' must raise TrainNotFoundError."""
        with pytest.raises(TrainNotFoundError) as exc_info:
            get_train_by_public_id(db_session, "INACT-9999")
        assert "INACT-9999" in str(exc_info.value)
        assert "inactive" in str(exc_info.value).lower()

    def test_unknown_train_id_rejected(self, db_session):
        """Non-existent train ID must raise TrainNotFoundError."""
        with pytest.raises(TrainNotFoundError) as exc_info:
            get_train_by_public_id(db_session, "GHOST-0000")
        assert "GHOST-0000" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()

    def test_empty_train_id_rejected(self, db_session):
        """Empty or whitespace train ID must raise TrainNotFoundError."""
        with pytest.raises(TrainNotFoundError):
            get_train_by_public_id(db_session, "")
        with pytest.raises(TrainNotFoundError):
            get_train_by_public_id(db_session, "   ")


# ===========================================================================
# 2. Schedule Lookup Tests
# ===========================================================================

class TestScheduleLookup:

    def test_valid_schedule_lookup(self, db_session):
        """Valid trip Colombo -> Kandy on 2026-12-03 must return the TrainSchedule."""
        schedule = get_schedule_for_trip(
            db=db_session,
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
        )
        assert schedule is not None
        assert schedule.from_station == "Colombo"
        assert schedule.to_station == "Kandy"
        assert schedule.travel_date == date(2026, 12, 3)
        assert schedule.first_class_capacity == 40
        assert schedule.second_class_capacity == 120

        # Also verify via BookingService orchestrator
        service = BookingService(db_session)
        service_sched = service.find_schedule(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
        )
        assert service_sched.id == schedule.id

    def test_valid_schedule_case_and_whitespace_insensitive(self, db_session):
        """Station names with differing casing and whitespace must resolve correctly."""
        schedule = get_schedule_for_trip(
            db=db_session,
            train_id="PM-4082",
            from_station="  colombo  ",
            to_station="KANDY ",
            travel_date=date(2026, 12, 3),
        )
        assert schedule is not None
        assert schedule.from_station == "Colombo"

    def test_wrong_route_rejected(self, db_session):
        """Searching for a route the train does not operate (e.g. Galle) must raise ScheduleNotFoundError."""
        with pytest.raises(ScheduleNotFoundError) as exc_info:
            get_schedule_for_trip(
                db=db_session,
                train_id="PM-4082",
                from_station="Colombo",
                to_station="Galle",
                travel_date=date(2026, 12, 3),
            )
        assert "PM-4082" in str(exc_info.value)
        assert "Colombo -> Galle" in str(exc_info.value)

    def test_wrong_travel_date_rejected(self, db_session):
        """Searching for an unscheduled date (e.g. 2026-12-04) must raise ScheduleNotFoundError."""
        with pytest.raises(ScheduleNotFoundError) as exc_info:
            get_schedule_for_trip(
                db=db_session,
                train_id="PM-4082",
                from_station="Colombo",
                to_station="Kandy",
                travel_date=date(2026, 12, 4),
            )
        assert "2026-12-04" in str(exc_info.value)

    def test_schedule_lookup_with_inactive_train_fails(self, db_session):
        """Looking up schedule for an inactive train must fail at the train level."""
        with pytest.raises(TrainNotFoundError):
            get_schedule_for_trip(
                db=db_session,
                train_id="INACT-9999",
                from_station="Colombo",
                to_station="Kandy",
                travel_date=date(2026, 12, 3),
            )


# ===========================================================================
# 3. Booking Detail Business Validation Tests
# ===========================================================================

class TestBookingValidation:

    def test_same_origin_destination_rejected_pydantic(self):
        """BookingRequest with identical from_station and to_station must fail validation."""
        target_date = date.today() + timedelta(days=10)
        with pytest.raises(ValidationError) as exc_info:
            BookingRequest(
                from_station="Colombo",
                to_station="Colombo",
                travel_date=target_date,
                train_id="PM-4082",
                seat_class="Second Class",
                passenger_count=1,
            )
        assert "cannot be the same" in str(exc_info.value)

    def test_same_origin_destination_case_insensitive_rejected(self):
        """BookingRequest with 'colombo' and ' Colombo ' must fail validation."""
        target_date = date.today() + timedelta(days=10)
        with pytest.raises(ValidationError) as exc_info:
            BookingRequest(
                from_station="colombo",
                to_station=" Colombo ",
                travel_date=target_date,
                train_id="PM-4082",
                seat_class="Second Class",
                passenger_count=1,
            )
        assert "cannot be the same" in str(exc_info.value)

    def test_unsupported_seat_class_rejected(self):
        """BookingRequest with unsupported class must fail validation."""
        target_date = date.today() + timedelta(days=10)
        with pytest.raises(ValidationError) as exc_info:
            BookingRequest(
                from_station="Colombo",
                to_station="Kandy",
                travel_date=target_date,
                train_id="PM-4082",
                seat_class="Executive Sleeper",
                passenger_count=1,
            )
        assert "not supported" in str(exc_info.value)

    def test_supported_seat_classes_accepted(self):
        """Both 'First Class' and 'Second Class' must be accepted and normalized."""
        target_date = date.today() + timedelta(days=10)
        b1 = BookingRequest(
            from_station="Colombo",
            to_station="Kandy",
            travel_date=target_date,
            train_id="PM-4082",
            seat_class="first class",
            passenger_count=1,
        )
        assert b1.seat_class == "First Class"

        b2 = BookingRequest(
            from_station="Colombo",
            to_station="Kandy",
            travel_date=target_date,
            train_id="PM-4082",
            seat_class="Second Class",
            passenger_count=2,
        )
        assert b2.seat_class == "Second Class"

    def test_business_validation_function(self):
        """Direct validate_booking_details call must pass valid request."""
        target_date = date.today() + timedelta(days=10)
        valid_req = BookingRequest(
            from_station="Colombo",
            to_station="Kandy",
            travel_date=target_date,
            train_id="PM-4082",
            seat_class="Second Class",
            passenger_count=2,
        )
        # Should not raise
        validate_booking_details(valid_req)
