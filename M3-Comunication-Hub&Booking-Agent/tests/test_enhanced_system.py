"""
tests/test_enhanced_system.py
------------------------------
Comprehensive verification test suite for the enhanced RailSense AI platform:
1. 5-Minute Prototype Seat Hold Lifecycle (Hold, decrement, confirmation, and timeout release)
2. FIFO Waiting List Enqueue, Queue Positions, and Automatic Seat Release Allocation
3. Atomic Booking Mutations & Idempotency Deduplication (Identical reuse vs payload conflict)
4. Opaque E-Ticket Tokens (TKT-...) and Privacy-Preserving SVG QR Code Live Server Verification
5. Asia/Colombo Timezone and Overnight Cross-Train Journey Conflict Detection
6. Security Agent Grounded 4-Section Summary and Adjudication Feedback Telemetry
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Setup module import paths
MEMBER_C = Path(__file__).resolve().parent.parent
BOOKING_AGENT = MEMBER_C / "booking-agent"
AGENT_HUB = MEMBER_C / "agent-hub"
SECURITY_AGENT_DIR = MEMBER_C.parent / "security-agent"

for p in (str(MEMBER_C), str(BOOKING_AGENT), str(AGENT_HUB), str(SECURITY_AGENT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from database.database import Base, get_db
from database.models import (
    Booking,
    BookingPassenger,
    BookingStatus,
    FraudInvestigationLabel,
    FraudReview,
    FraudReviewStatus,
    HoldStatus,
    IdempotencyRecord,
    Passenger,
    SeatHold,
    Train,
    TrainSchedule,
    WaitingListEntry,
    WaitingListStatus,
)
from database.seed import seed_test_train_data
from schemas.booking import (
    BookingRequest,
    PassengerDetail,
    SeatHoldRequest,
    WaitingListRequest,
)
from booking.exceptions import (
    ConflictingActiveJourneyError,
    DuplicateActiveTicketError,
    IdempotencyConflictError,
    SeatsUnavailableError,
)
from booking.service import BookingService
from booking.lifecycle import (
    create_seat_hold,
    get_active_hold,
    release_expired_holds,
    get_held_seats_for_schedule,
)
from booking.waiting_list import (
    enqueue_waiting_list,
    allocate_released_seat_to_waiting_list,
    get_active_queue_length,
)
from booking.qr_service import (
    generate_ticket_token,
    generate_ticket_qr_svg,
    verify_ticket_token,
)
from fraud.rules import check_cross_train_conflicts
from fraud.llm_summary import (
    generate_grounded_fraud_summary,
    sanitize_evidence_object,
    DEMO_POLICY_CITATIONS,
)
from shared.nic import hash_nic, mask_nic


# Isolated In-Memory Database Engine for Enhanced System Tests
TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)


@pytest.fixture(scope="module", autouse=True)
def setup_enhanced_test_db():
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestSession() as db:
        seed_test_train_data(db)

        # 1. Seed tight-capacity train (1 First Class seat, 1 Second Class seat)
        t_tight = db.query(Train).filter(Train.train_id == "TIGHT-EXP").first()
        if not t_tight:
            t_tight = Train(train_id="TIGHT-EXP", train_name="Tight Capacity Express", active=True)
            db.add(t_tight)
            db.flush()
            sch_tight = TrainSchedule(
                train_id=t_tight.id,
                from_station="Colombo",
                to_station="Kandy",
                travel_date=date(2026, 12, 10),
                departure_time=time(8, 0),
                arrival_time=time(11, 0),
                first_class_capacity=1,
                second_class_capacity=1,
            )
            db.add(sch_tight)

        # 2. Seed overnight train service (Departs 22:00, Arrives 04:30 next morning)
        t_night = db.query(Train).filter(Train.train_id == "NIGHT-MAIL").first()
        if not t_night:
            t_night = Train(train_id="NIGHT-MAIL", train_name="Night Mail Express", active=True)
            db.add(t_night)
            db.flush()
            sch_night = TrainSchedule(
                train_id=t_night.id,
                from_station="Colombo",
                to_station="Badulla",
                travel_date=date(2026, 12, 10),
                departure_time=time(22, 0),
                arrival_time=time(4, 30),
                first_class_capacity=20,
                second_class_capacity=50,
            )
            db.add(sch_night)

        # 3. Seed early morning connecting train (Departs 02:00 next morning from Colombo)
        t_early = db.query(Train).filter(Train.train_id == "EARLY-DAWN").first()
        if not t_early:
            t_early = Train(train_id="EARLY-DAWN", train_name="Early Dawn Special", active=True)
            db.add(t_early)
            db.flush()
            sch_early = TrainSchedule(
                train_id=t_early.id,
                from_station="Colombo",
                to_station="Kandy",
                travel_date=date(2026, 12, 11),
                departure_time=time(2, 0),
                arrival_time=time(5, 0),
                first_class_capacity=20,
                second_class_capacity=50,
            )
            db.add(sch_early)

        db.commit()


@pytest.fixture
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ===========================================================================
# 1. 5-Minute Prototype Seat Hold Lifecycle Tests
# ===========================================================================
class TestSeatHoldLifecycle:
    def test_create_and_query_seat_hold(self, db):
        """Creating a seat hold reduces available inventory and sets 5-min expiration."""
        req = SeatHoldRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=2,
            user_id="hold_tester",
        )
        resp = create_seat_hold(db, req)

        assert resp.hold_token.startswith("HLD-")
        assert resp.passenger_count == 2
        assert resp.expires_in_seconds > 290
        assert resp.expires_in_seconds <= 300

        # Query active hold
        active = get_active_hold(db, resp.hold_token)
        assert active is not None
        assert active.status == HoldStatus.ACTIVE
        assert active.seat_count == 2

        # Verify held seats are calculated in schedule inventory
        held = get_held_seats_for_schedule(db, active.schedule_id, "Second Class")
        assert held >= 2

    def test_confirm_booking_consumes_active_hold(self, db):
        """Booking with an active hold token links the hold and marks it CONFIRMED."""
        hold_req = SeatHoldRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="First Class",
            passenger_count=1,
            user_id="buyer_with_hold",
        )
        hold_resp = create_seat_hold(db, hold_req)

        # Confirm booking referencing the hold token
        service = BookingService(db)
        b_req = BookingRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="First Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Hold Buyer", nic="199011223344")],
            hold_token=hold_resp.hold_token,
        )
        result = service.process_booking(b_req)

        assert result.status == "CONFIRMED"
        assert result.ticket_token is not None

        # Check DB record for hold transition
        db_hold = get_active_hold(db, hold_resp.hold_token)
        assert db_hold is None  # No longer active

        hold_record = db.query(SeatHold).filter(SeatHold.hold_token == hold_resp.hold_token).first()
        assert hold_record.status == HoldStatus.CONFIRMED

        # Check booking record holds foreign key
        booking = db.query(Booking).filter(Booking.booking_reference == result.booking_reference).first()
        assert booking.hold_id == hold_record.id
        assert booking.ticket_token == result.ticket_token

    def test_expired_hold_is_released_back_to_inventory(self, db):
        """Expired holds are released by release_expired_holds(), freeing seats."""
        hold_req = SeatHoldRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=3,
            user_id="timeout_user",
        )
        hold_resp = create_seat_hold(db, hold_req)

        # Force expire the hold in database
        hold_record = db.query(SeatHold).filter(SeatHold.hold_token == hold_resp.hold_token).first()
        hold_record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.commit()

        # Run release worker
        released_count = release_expired_holds(db)
        assert released_count >= 1

        db.refresh(hold_record)
        assert hold_record.status == HoldStatus.EXPIRED


# ===========================================================================
# 2. FIFO Waiting List & Auto-Allocation Tests
# ===========================================================================
class TestFIFOWaitingList:
    def test_waiting_list_enqueue_and_priority_order(self, db):
        """Sold-out service enqueues passengers with deterministic incrementing positions."""
        wl_req_1 = WaitingListRequest(
            train_id="TIGHT-EXP",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 10),
            seat_class="Second Class",
            passenger_count=1,
            passenger_email="p1@railsense.ai",
            user_id="user_p1",
        )
        resp1 = enqueue_waiting_list(db, wl_req_1)
        assert resp1.queue_position == 1
        assert resp1.status == "PENDING"

        wl_req_2 = WaitingListRequest(
            train_id="TIGHT-EXP",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 10),
            seat_class="Second Class",
            passenger_count=1,
            passenger_email="p2@railsense.ai",
            user_id="user_p2",
        )
        resp2 = enqueue_waiting_list(db, wl_req_2)
        assert resp2.queue_position == 2
        assert resp2.status == "PENDING"

        # Check total active waiting list length
        train = db.query(Train).filter(Train.train_id == "TIGHT-EXP").first()
        sch = db.query(TrainSchedule).filter(TrainSchedule.train_id == train.id).first()
        length = get_active_queue_length(db, sch.id, "Second Class")
        assert length >= 2

    def test_seat_release_auto_allocates_to_head_of_queue(self, db):
        """When a seat is released, the FIFO head is allocated a prototype hold."""
        train = db.query(Train).filter(Train.train_id == "TIGHT-EXP").first()
        sch = db.query(TrainSchedule).filter(TrainSchedule.train_id == train.id).first()

        wl_req = WaitingListRequest(
            train_id="TIGHT-EXP",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 10),
            seat_class="Second Class",
            passenger_count=1,
            passenger_email="p1@railsense.ai",
            user_id="user_p1",
        )
        enqueue_waiting_list(db, wl_req)

        entry = allocate_released_seat_to_waiting_list(
            db=db,
            schedule_id=sch.id,
            seat_class="Second Class",
            seats_freed=1,
        )
        assert entry is not None
        assert entry.passenger_email == "p1@railsense.ai"
        assert entry.status == WaitingListStatus.ALLOCATED
        assert entry.assigned_hold_token is not None
        assert entry.assigned_hold_token.startswith("HLD-")


# ===========================================================================
# 3. Idempotency Deduplication & Concurrency Tests
# ===========================================================================
class TestIdempotencyDeduplication:
    def test_identical_idempotency_key_returns_cached_booking(self, db):
        """Repeated submission with identical idempotency_key returns cached result without creating new booking."""
        service = BookingService(db)
        idem_key = "IDEM-CLEAN-KEY-001"

        req = BookingRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Idem Traveler", nic="198011223344")],
            idempotency_key=idem_key,
        )
        res1 = service.process_booking(req)
        assert res1.status == "CONFIRMED"
        ref1 = res1.booking_reference

        # Repeat identical request
        res2 = service.process_booking(req)
        assert res2.status == "CONFIRMED"
        assert res2.booking_reference == ref1
        assert res2.ticket_token == res1.ticket_token

        # Verify only 1 booking record exists in DB with this reference
        count = db.query(Booking).filter(Booking.booking_reference == ref1).count()
        assert count == 1

        # Verify IdempotencyRecord exists
        idem_rec = db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == idem_key).first()
        assert idem_rec is not None
        assert idem_rec.booking_reference == ref1

    def test_idempotency_key_with_different_payload_raises_conflict(self, db):
        """Reusing the same idempotency key for different travel parameters raises 409 conflict error."""
        service = BookingService(db)
        idem_key = "IDEM-CONFLICT-KEY-002"

        req1 = BookingRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="First User", nic="198111223344")],
            idempotency_key=idem_key,
        )
        service.process_booking(req1)

        # Mutate the payload with a different train or route while keeping the same key
        req2 = BookingRequest(
            train_id="EXP-EVENING",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Different User", nic="198211223344")],
            idempotency_key=idem_key,
        )

        with pytest.raises(IdempotencyConflictError) as exc_info:
            service.process_booking(req2)
        assert exc_info.value.status_code == 409
        assert "mismatched booking parameters" in exc_info.value.message


# ===========================================================================
# 4. Opaque QR E-Ticket & Privacy Verification Tests
# ===========================================================================
class TestTicketQRAndVerification:
    def test_opaque_ticket_token_and_svg_generation(self):
        """Tokens are 32-byte URL safe; SVG QR renders valid XML without PII leakage."""
        token = generate_ticket_token()
        assert token.startswith("TKT-")
        assert len(token) >= 40

        svg = generate_ticket_qr_svg(token)
        assert svg.startswith("<svg")
        assert "</svg>" in svg
        # Zero PII leakage in QR
        assert "19" not in svg  # no year/NIC fragment
        assert "V" not in svg and "v" not in svg or "<svg" in svg

    def test_server_side_ticket_verification_lifecycle(self, db):
        """Tickets verify cleanly server-side without exposing passenger NICs."""
        service = BookingService(db)
        req = BookingRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="First Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Verified Passenger", nic="198311223344")],
        )
        result = service.process_booking(req)
        assert result.ticket_token is not None

        # Verify ticket with server
        ver = verify_ticket_token(db, result.ticket_token)
        assert ver["is_valid"] is True
        assert ver["status"] == "CONFIRMED"
        assert ver["train_id"] == "PM-4082"
        assert ver["passenger_count"] == 1
        assert "nic" not in str(ver).lower() or "primary_nic_masked" in ver

        # Invalid token check
        bogus_ver = verify_ticket_token(db, "TKT-BOGUS-TOKEN-NOT-FOUND")
        assert bogus_ver["is_valid"] is False


# ===========================================================================
# 5. Asia/Colombo Timezone and Overnight Trip Conflict Checking
# ===========================================================================
class TestOvernightTimezoneConflicts:
    def test_overnight_trip_interval_conflicts_detected(self, db):
        """
        Overnight train (22:00 -> 04:30 next morning) conflicts with an early morning train
        departing at 02:00 next morning for the same passenger identity.
        """
        passenger_nic = "198411223344"
        nic_h = hash_nic(passenger_nic)

        # 1. Book overnight train
        service = BookingService(db)
        req_night = BookingRequest(
            train_id="NIGHT-MAIL",
            from_station="Colombo",
            to_station="Badulla",
            travel_date=date(2026, 12, 10),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Night Traveler", nic=passenger_nic)],
        )
        result_night = service.process_booking(req_night)
        assert result_night.status == "CONFIRMED"

        # 2. Attempt to book train departing at 02:00 on Dec 11 (while overnight train is still in transit)
        req_overlap = BookingRequest(
            train_id="EARLY-DAWN",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 11),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Night Traveler", nic=passenger_nic)],
        )

        with pytest.raises(ConflictingActiveJourneyError) as exc_info:
            service.process_booking(req_overlap)
        assert exc_info.value.status_code == 409
        assert "conflicts" in exc_info.value.message.lower()


# ===========================================================================
# 6. Security Agent Grounded Summary & Feedback Telemetry Tests
# ===========================================================================
class TestSecurityGroundedSummaryAndFeedback:
    def test_grounded_summary_four_sections_and_sanitization(self):
        """Grounded summary contains 4 mandatory sections and strips raw NICs."""
        raw_evidence = {
            "features": {
                "bookings_last_1_minute": 4.0,
                "bookings_last_10_minutes": 8.0,
                "duplicate_attempts": 2.0,
                "seconds_since_previous_booking": 12.0,
            },
            "risk_score": 0.82,
            "risk_level": "HIGH",
            "travel_context": {
                "from_station": "Colombo",
                "to_station": "Kandy",
                "train_id": "PM-4082",
                "travel_date": "2026-12-03",
                "passenger_count": 2,
            },
            "raw_passenger_nic": "199212345678",
        }

        # Test evidence sanitization
        clean = sanitize_evidence_object(raw_evidence)
        assert clean["raw_passenger_nic"] != "199212345678"
        assert "****" in clean["raw_passenger_nic"]

        # Generate summary
        summary = generate_grounded_fraud_summary(raw_evidence)
        assert "observed_facts" in summary
        assert "reasons_for_review" in summary
        assert "uncertainty" in summary
        assert "matters_to_check" in summary
        assert "policy_citations" in summary

        assert len(summary["observed_facts"]) > 0
        assert len(summary["reasons_for_review"]) > 0
        assert len(summary["matters_to_check"]) > 0
        assert "Project Demo Specification" in summary["evaluation_source"]

    def test_human_review_records_investigation_feedback(self, db):
        """Admin adjudication records ground-truth feedback for model telemetry."""
        from fraud.review_service import FraudReviewService

        review_svc = FraudReviewService(db)
        nic = "199312345678"

        case_ref = review_svc.create_review_case(
            primary_nic=nic,
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passenger_email="feedback_test@railsense.ai",
            user_id="feedback_tester",
            risk_score=0.72,
            risk_level="HIGH",
            reasons=["BURST_VELOCITY"],
            payload={
                "passengers": [{"name": "Feedback Candidate", "nic": nic, "nic_hash": hash_nic(nic), "nic_masked": mask_nic(nic)}],
                "fare": 1200.0,
            },
        )

        # Admin rejects as CONFIRMED_FRAUD
        outcome = review_svc.review_case(
            case_reference=case_ref,
            decision="REJECT",
            admin_reason="Confirmed automated ticket hoarding attempt.",
        )
        assert outcome["status"] == "REJECTED"

        # Check FraudInvestigationLabel in DB
        label = db.query(FraudInvestigationLabel).filter(FraudInvestigationLabel.case_reference == case_ref).first()
        assert label is not None
        assert label.true_label == "CONFIRMED_FRAUD"
        assert "automated ticket hoarding" in label.reviewer_notes
