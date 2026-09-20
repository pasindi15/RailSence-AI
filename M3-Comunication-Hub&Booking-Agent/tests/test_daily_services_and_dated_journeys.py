"""
tests/test_daily_services_and_dated_journeys.py
-----------------------------------------------
Comprehensive test suite verifying daily train services with date-specific booking:
1. Daily service recurring appearance on future dates (schedules.md).
2. Idempotency & concurrency safety (no duplicate journey records under race conditions).
3. Independent inventory per travel date (booking Date A never alters Date B).
4. Cancellation scoped strictly to specific journey date.
5. Explicitly cancelled journeys remain unavailable and cannot be re-seeded.
6. Advance booking horizon (<= 90 days) and past date rejection in Asia/Colombo time.
7. Overnight train (4095 Uttara Devi) arrival_date and intermediate boarding.
8. Anti-fraud / NIC duplicate rules scoped correctly per travel date.
9. Station aliases and normalization (Colombo Fort <-> Colombo).
"""

from __future__ import annotations

import concurrent.futures
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

MEMBER_C = os.path.dirname(os.path.dirname(__file__))
BOOKING_AGENT = os.path.join(MEMBER_C, "booking-agent")
for p in (MEMBER_C, BOOKING_AGENT):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from zoneinfo import ZoneInfo
    COLOMBO_TZ = ZoneInfo("Asia/Colombo")
except Exception:
    COLOMBO_TZ = timezone(timedelta(hours=5, minutes=30))

from database.models import Base, Booking, BookingStatus, Train, TrainSchedule
from schemas.booking import BookingRequest, PassengerDetail
from booking import (
    BookingService,
    InvalidBookingError,
    ScheduleNotFoundError,
    SeatsUnavailableError,
)
from booking.availability import (
    ensure_journeys_for_date,
    get_available_seats,
    get_schedule_for_trip,
    get_schedules_for_route,
    validate_travel_date,
)
from booking.services_catalog import (
    find_matching_services,
    get_service_by_train_id,
    normalize_station,
    stations_match,
)


TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=TEST_ENGINE)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture
def today_colombo():
    return datetime.now(COLOMBO_TZ).date()


# ===========================================================================
# 1. Daily Services Appearance & Search
# ===========================================================================

class TestDailyServicesMaterialization:

    def test_daily_trains_appear_on_future_dates(self, db, today_colombo):
        """Services from schedules.md (1005, 1015, 1020) appear on multiple future dates."""
        date1 = today_colombo + timedelta(days=3)
        date2 = today_colombo + timedelta(days=14)
        date3 = today_colombo + timedelta(days=45)

        for travel_date in (date1, date2, date3):
            options = get_schedules_for_route(
                db=db,
                from_station="Colombo Fort",
                to_station="Kandy",
                travel_date=travel_date,
            )
            assert len(options) >= 3
            train_ids = [opt["train_id"] for opt in options]
            assert "1005" in train_ids  # Podi Menike
            assert "1015" in train_ids  # Udarata Menike
            assert "1020" in train_ids  # Intercity Express

            # Verify enriched fields
            for opt in options:
                assert opt["travel_date"] == travel_date.isoformat()
                assert opt["arrival_date"] == travel_date.isoformat()
                assert opt["is_overnight"] is False
                assert opt["schedule_id"] is not None
                assert len(opt["available_classes"]) == 2

    def test_station_alias_matching_finds_schedules(self, db, today_colombo):
        """Searching 'colombo' matches 'Colombo Fort' and returns daily services."""
        travel_date = today_colombo + timedelta(days=5)
        options = get_schedules_for_route(
            db=db,
            from_station="colombo",
            to_station="kandy",
            travel_date=travel_date,
        )
        assert len(options) >= 3
        train_names = [opt["train_name"] for opt in options]
        assert any("Udarata Menike" in name for name in train_names)

    def test_idempotent_materialization(self, db, today_colombo):
        """Repeated calls for the same route and date do not duplicate TrainSchedule rows."""
        travel_date = today_colombo + timedelta(days=7)

        opts_run1 = get_schedules_for_route(db, "Colombo Fort", "Kandy", travel_date)
        count_run1 = db.query(TrainSchedule).filter(TrainSchedule.travel_date == travel_date).count()

        opts_run2 = get_schedules_for_route(db, "Colombo Fort", "Kandy", travel_date)
        count_run2 = db.query(TrainSchedule).filter(TrainSchedule.travel_date == travel_date).count()

        assert count_run1 == count_run2
        assert len(opts_run1) == len(opts_run2)
        assert [o["schedule_id"] for o in opts_run1] == [o["schedule_id"] for o in opts_run2]

    def test_concurrent_searches_are_safe(self, today_colombo, tmp_path):
        """Concurrent calls to ensure_journeys_for_date across threads do not duplicate records."""
        db_file = tmp_path / "concurrent_test.db"
        file_engine = create_engine(
            f"sqlite:///{db_file}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        Base.metadata.create_all(bind=file_engine)
        FileSession = sessionmaker(bind=file_engine, autocommit=False, autoflush=False)
        travel_date = today_colombo + timedelta(days=10)

        def worker():
            local_session = FileSession()
            try:
                ensure_journeys_for_date(
                    db=local_session,
                    travel_date=travel_date,
                    from_station="Colombo Fort",
                    to_station="Kandy",
                )
                local_session.commit()
            except Exception:
                local_session.rollback()
                raise
            finally:
                local_session.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker) for _ in range(5)]
            for f in concurrent.futures.as_completed(futures):
                f.result()  # verify no unhandled exception

        # Verify DB integrity
        check_session = FileSession()
        try:
            scheds = check_session.query(TrainSchedule).filter(
                TrainSchedule.travel_date == travel_date,
                TrainSchedule.from_station == "Colombo Fort",
                TrainSchedule.to_station == "Kandy",
            ).all()
            train_ids = [s.train_id for s in scheds]
            # Each train should appear exactly once
            assert len(train_ids) == len(set(train_ids))
        finally:
            check_session.close()
            file_engine.dispose()


# ===========================================================================
# 2. Independent Inventory Per Travel Date
# ===========================================================================

class TestIndependentSeatInventory:

    def test_booking_on_date_a_leaves_date_b_intact(self, db, today_colombo):
        """Booking 4 seats on Date A decrements Date A capacity only; Date B remains 100% full."""
        date_a = today_colombo + timedelta(days=5)
        date_b = today_colombo + timedelta(days=6)

        service = BookingService(db)
        sched_a = service.find_schedule("1015", "Colombo Fort", "Kandy", date_a)
        sched_b = service.find_schedule("1015", "Colombo Fort", "Kandy", date_b)

        assert sched_a.id != sched_b.id
        cap_2nd = sched_a.second_class_capacity
        assert get_available_seats(db, sched_a, "Second Class") == cap_2nd
        assert get_available_seats(db, sched_b, "Second Class") == cap_2nd

        # Book 4 seats on Date A
        booking_req = BookingRequest(
            from_station="Colombo Fort",
            to_station="Kandy",
            travel_date=date_a,
            train_id="1015",
            seat_class="Second Class",
            passenger_count=4,
            passengers=[
                PassengerDetail(name="Passenger 1", nic="199011112222"),
                PassengerDetail(name="Passenger 2", nic="199011112223"),
                PassengerDetail(name="Passenger 3", nic="199011112224"),
                PassengerDetail(name="Passenger 4", nic="199011112225"),
            ],
        )
        res = service.process_booking(booking_req)
        assert res.booking_reference is not None

        # Verify Date A is decremented by 4
        rem_a = get_available_seats(db, sched_a, "Second Class")
        assert rem_a == cap_2nd - 4

        # Verify Date B is completely unaffected
        rem_b = get_available_seats(db, sched_b, "Second Class")
        assert rem_b == cap_2nd

    def test_cancellation_restores_only_cancelled_date(self, db, today_colombo):
        """Cancelling Date A reservation restores seats to Date A without altering Date B."""
        date_a = today_colombo + timedelta(days=8)
        date_b = today_colombo + timedelta(days=9)

        service = BookingService(db)
        sched_a = service.find_schedule("1015", "Colombo Fort", "Kandy", date_a)
        sched_b = service.find_schedule("1015", "Colombo Fort", "Kandy", date_b)

        cap_1st = sched_a.first_class_capacity

        # Book Date A
        req_a = BookingRequest(
            from_station="Colombo Fort",
            to_station="Kandy",
            travel_date=date_a,
            train_id="1015",
            seat_class="First Class",
            passenger_count=2,
            passengers=[
                PassengerDetail(name="Alice", nic="198511223344"),
                PassengerDetail(name="Bob", nic="198511223345"),
            ],
        )
        res_a = service.process_booking(req_a)
        assert get_available_seats(db, sched_a, "First Class") == cap_1st - 2
        assert get_available_seats(db, sched_b, "First Class") == cap_1st

        # Cancel Date A
        b = db.query(Booking).filter(Booking.booking_reference == res_a.booking_reference).first()
        b.status = BookingStatus.CANCELLED
        db.commit()

        # Date A capacity restored
        assert get_available_seats(db, sched_a, "First Class") == cap_1st
        # Date B capacity untouched
        assert get_available_seats(db, sched_b, "First Class") == cap_1st


# ===========================================================================
# 3. Explicitly Cancelled Services Remain Unavailable
# ===========================================================================

class TestCancelledServiceProtection:

    def test_explicitly_cancelled_journey_cannot_be_booked(self, db, today_colombo):
        """Explicitly cancelled journey returns 0 seats and rejects booking attempts."""
        travel_date = today_colombo + timedelta(days=12)

        service = BookingService(db)
        sched = service.find_schedule("1015", "Colombo Fort", "Kandy", travel_date)
        sched.service_status = "CANCELLED"
        db.commit()

        # Available seats must be 0
        assert get_available_seats(db, sched, "First Class") == 0
        assert get_available_seats(db, sched, "Second Class") == 0

        # Search options reflect CANCELLED status
        options = get_schedules_for_route(db, "Colombo Fort", "Kandy", travel_date)
        opt_1015 = next(o for o in options if o["train_id"] == "1015")
        assert opt_1015["service_status"] == "CANCELLED"
        for cls_info in opt_1015["available_classes"]:
            assert cls_info["available_seats"] == 0

        # Re-materialization must NOT overwrite CANCELLED status
        ensure_journeys_for_date(db, travel_date, "Colombo Fort", "Kandy")
        db.refresh(sched)
        assert sched.service_status == "CANCELLED"

        # Attempting to book raises InvalidBookingError
        req = BookingRequest(
            from_station="Colombo Fort",
            to_station="Kandy",
            travel_date=travel_date,
            train_id="1015",
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Passenger", nic="199212345678")],
        )
        with pytest.raises((InvalidBookingError, ValueError)) as exc_info:
            service.process_booking(req)
        assert "cancelled" in str(exc_info.value).lower()


# ===========================================================================
# 4. Advance Booking Horizon & Past Date Validation
# ===========================================================================

class TestBookingHorizonValidation:

    def test_past_date_rejected(self, today_colombo):
        """Dates before today in Asia/Colombo timezone are rejected."""
        past_date = today_colombo - timedelta(days=1)
        with pytest.raises(InvalidBookingError) as exc_info:
            validate_travel_date(past_date)
        assert "past date" in str(exc_info.value).lower()

    def test_far_future_date_beyond_horizon_rejected(self, today_colombo):
        """Dates beyond 90 days are rejected."""
        far_future = today_colombo + timedelta(days=95)
        with pytest.raises(InvalidBookingError) as exc_info:
            validate_travel_date(far_future)
        assert "exceeds" in str(exc_info.value).lower()
        assert "90 days" in str(exc_info.value).lower()

    def test_dates_within_horizon_are_valid(self, today_colombo):
        """Today, tomorrow, and up to 90 days are valid."""
        validate_travel_date(today_colombo)
        validate_travel_date(today_colombo + timedelta(days=1))
        validate_travel_date(today_colombo + timedelta(days=90))


# ===========================================================================
# 5. Overnight Services & Arrival Date Calculation
# ===========================================================================

class TestOvernightServices:

    def test_uttara_devi_4095_overnight_arrival_date(self, db, today_colombo):
        """Uttara Devi (4095) departs 20:15 and arrives 04:10 next day."""
        dep_date = today_colombo + timedelta(days=4)

        service = BookingService(db)
        sched = service.find_schedule("4095", "Colombo Fort", "Jaffna", dep_date)

        assert sched.travel_date == dep_date
        assert sched.arrival_date == dep_date + timedelta(days=1)
        assert sched.departure_time.hour == 20
        assert sched.departure_time.minute == 15
        assert sched.arrival_time.hour == 4
        assert sched.arrival_time.minute == 10

        # Query options check
        options = get_schedules_for_route(db, "Colombo Fort", "Jaffna", dep_date)
        opt_4095 = next(o for o in options if o["train_id"] == "4095")
        assert opt_4095["is_overnight"] is True
        assert opt_4095["arrival_date"] == (dep_date + timedelta(days=1)).isoformat()


# ===========================================================================
# 6. Anti-Fraud & NIC Rules Scoped Across Dates
# ===========================================================================

class TestNICScopeAcrossDates:

    def test_same_nic_can_book_different_dates(self, db, today_colombo):
        """A passenger with the same NIC can legally travel on different dates."""
        date_a = today_colombo + timedelta(days=10)
        date_b = today_colombo + timedelta(days=15)

        service = BookingService(db)
        passenger_nic = "199412345678"

        req1 = BookingRequest(
            from_station="Colombo Fort",
            to_station="Kandy",
            travel_date=date_a,
            train_id="1015",
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Frequent Traveler", nic=passenger_nic)],
        )
        res1 = service.process_booking(req1)
        assert res1.booking_reference is not None

        req2 = BookingRequest(
            from_station="Colombo Fort",
            to_station="Kandy",
            travel_date=date_b,
            train_id="1015",
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Frequent Traveler", nic=passenger_nic)],
        )
        res2 = service.process_booking(req2)
        assert res2.booking_reference is not None
        assert res1.booking_reference != res2.booking_reference
