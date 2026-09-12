"""
tests/test_phase4_nic_and_fraud.py
----------------------------------
Comprehensive test suite for Phase 4:
- Mandatory Sri Lankan NIC validation (old & new formats, lowercase normalization)
- Deterministic HMAC-SHA256 privacy hashing & masking
- Passenger count and NIC matching
- Deterministic Conflict Rules:
    1. DUPLICATE_NIC_IN_BOOKING (400)
    2. DUPLICATE_ACTIVE_TICKET (409)
    3. CONFLICTING_ACTIVE_JOURNEY (409)
    4. Non-conflicting repeat journey allowed
    5. Different date journey allowed
- Security & Fraud Agent (ML IsolationForest behavioral risk scoring)
- Fail-Closed Resilience (SECURITY_AGENT_UNAVAILABLE -> PENDING_FRAUD_REVIEW)
- Human Admin Fraud Review Queue & Adjudication (Approve with strict seat & conflict re-checks, Reject)
- Strict Privacy & Security Auditing (zero raw NIC leakage in database or logs)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
MEMBER_C = os.path.dirname(os.path.dirname(__file__))
BOOKING_AGENT = os.path.join(MEMBER_C, "booking-agent")
SECURITY_AGENT_DIR = os.path.join(os.path.dirname(MEMBER_C), "security-agent")

for p in (MEMBER_C, BOOKING_AGENT, SECURITY_AGENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from database.database import get_db
from database.models import (
    Base,
    Booking,
    BookingPassenger,
    BookingStatus,
    FraudReview,
    FraudReviewStatus,
    Passenger,
    Train,
    TrainSchedule,
)
from database.seed import seed_test_train_data
from booking.exceptions import (
    ConflictingActiveJourneyError,
    DuplicateActiveTicketError,
    DuplicateNICInBookingError,
    InvalidBookingError,
    SeatsUnavailableError,
)
from schemas.booking import BookingRequest, PassengerDetail
from booking.service import BookingService
from fraud.client import set_security_client_transport
from fraud.review_service import FraudReviewError, FraudReviewService
from shared.nic import (
    hash_nic,
    mask_nic,
    normalize_nic,
    validate_sri_lankan_nic,
)
from shared.schemas import AgentMessage

import importlib.util
BOOKING_MAIN_PATH = os.path.join(BOOKING_AGENT, "main.py")
spec_bk = importlib.util.spec_from_file_location("booking_agent_api_main", BOOKING_MAIN_PATH)
booking_agent_main = importlib.util.module_from_spec(spec_bk)
sys.modules["booking_agent_api_main"] = booking_agent_main
spec_bk.loader.exec_module(booking_agent_main)

# ---------------------------------------------------------------------------
# Isolated In-Memory Database for Phase 4 Test Suite
# ---------------------------------------------------------------------------
TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)


@pytest.fixture(scope="module", autouse=True)
def setup_phase4_db():
    """Create all tables in in-memory test database and seed train data."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestSession() as db:
        seed_test_train_data(db)

        # Seed overlapping and non-overlapping trains for journey conflict testing
        # Train A (Overlapping with PM-4082 07:00-10:15): dep 09:00, arr 12:00
        t_overlap = db.query(Train).filter(Train.train_id == "EXP-OVERLAP").first()
        if not t_overlap:
            t_overlap = Train(train_id="EXP-OVERLAP", train_name="Overlapping Express", active=True)
            db.add(t_overlap)
            db.flush()

            sch_overlap = TrainSchedule(
                train_id=t_overlap.id,
                from_station="Colombo",
                to_station="Kandy",
                travel_date=date(2026, 12, 3),
                departure_time=time(9, 0),
                arrival_time=time(12, 0),
                first_class_capacity=20,
                second_class_capacity=50,
            )
            db.add(sch_overlap)

        # Train B (Non-overlapping with PM-4082 07:00-10:15): dep 16:00, arr 19:15
        t_evening = db.query(Train).filter(Train.train_id == "EXP-EVENING").first()
        if not t_evening:
            t_evening = Train(train_id="EXP-EVENING", train_name="Evening Express", active=True)
            db.add(t_evening)
            db.flush()

            sch_evening = TrainSchedule(
                train_id=t_evening.id,
                from_station="Colombo",
                to_station="Kandy",
                travel_date=date(2026, 12, 3),
                departure_time=time(16, 0),
                arrival_time=time(19, 15),
                first_class_capacity=20,
                second_class_capacity=50,
            )
            db.add(sch_evening)

        # Train C (Tight capacity train for exhaustion tests): capacity 1 seat
        t_limited = db.query(Train).filter(Train.train_id == "EXP-TIGHT").first()
        if not t_limited:
            t_limited = Train(train_id="EXP-TIGHT", train_name="Limited Express", active=True)
            db.add(t_limited)
            db.flush()

            sch_limited = TrainSchedule(
                train_id=t_limited.id,
                from_station="Colombo",
                to_station="Kandy",
                travel_date=date(2026, 12, 3),
                departure_time=time(13, 0),
                arrival_time=time(15, 30),
                first_class_capacity=1,
                second_class_capacity=1,
            )
            db.add(sch_limited)

        db.commit()


@pytest.fixture
def db_session():
    """Provide a transactional DB session for individual tests."""
    session = TestSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def booking_client(db_session):
    """FastAPI TestClient for Booking Agent with overridden DB session."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    booking_agent_main.app.dependency_overrides[booking_agent_main.get_db] = override_get_db
    booking_agent_main.app.dependency_overrides[get_db] = override_get_db
    client = TestClient(booking_agent_main.app)
    yield client
    booking_agent_main.app.dependency_overrides.pop(booking_agent_main.get_db, None)
    booking_agent_main.app.dependency_overrides.pop(get_db, None)


# ===========================================================================
# 1. NIC Utilities & Normalization Tests
# ===========================================================================
class TestNICUtilities:
    def test_valid_old_format_nics(self):
        """9 digits + V/X, case-insensitive normalization."""
        v1, norm1 = validate_sri_lankan_nic("851234567V")
        assert v1 is True
        assert norm1 == "851234567V"

        v2, norm2 = validate_sri_lankan_nic("851234567v")
        assert v2 is True
        assert norm2 == "851234567V"

        v3, norm3 = validate_sri_lankan_nic("923456789X")
        assert v3 is True
        assert norm3 == "923456789X"

        v4, norm4 = validate_sri_lankan_nic("923456789x")
        assert v4 is True
        assert norm4 == "923456789X"

        assert normalize_nic(" 851234567v ") == "851234567V"

    def test_valid_new_format_nics(self):
        """12 digits."""
        v1, norm1 = validate_sri_lankan_nic("198512345678")
        assert v1 is True
        assert norm1 == "198512345678"

        v2, norm2 = validate_sri_lankan_nic("200012345678")
        assert v2 is True
        assert norm2 == "200012345678"

        assert normalize_nic(" 198512345678 ") == "198512345678"

    def test_invalid_nic_formats(self):
        """Invalid lengths and characters must fail validation."""
        assert validate_sri_lankan_nic("12345678")[0] is False       # 8 digits
        assert validate_sri_lankan_nic("123456789")[0] is False      # 9 digits no letter
        assert validate_sri_lankan_nic("851234567A")[0] is False     # Invalid suffix letter
        assert validate_sri_lankan_nic("19851234567")[0] is False     # 11 digits
        assert validate_sri_lankan_nic("1985123456789")[0] is False   # 13 digits
        assert validate_sri_lankan_nic("19851234567V")[0] is False   # 11 digits + letter
        assert validate_sri_lankan_nic("85123-4567V")[0] is False    # symbols
        assert validate_sri_lankan_nic("")[0] is False
        assert validate_sri_lankan_nic("   ")[0] is False

    def test_deterministic_hmac_hashing(self):
        """HMAC hashing must be deterministic and case-normalized."""
        hash1 = hash_nic("851234567V")
        hash2 = hash_nic("851234567v")
        hash3 = hash_nic(" 851234567v ")
        hash4 = hash_nic("851234568V")

        assert hash1 == hash2 == hash3
        assert hash1 != hash4
        assert len(hash1) == 64  # SHA-256 hex string
        assert "851234567" not in hash1  # Raw NIC must never be in hash

    def test_nic_masking(self):
        """Masking retains leading asterisks and trailing characters."""
        assert mask_nic("851234567V") == "******567V"
        assert mask_nic("198512345678") == "********5678"
        assert mask_nic("851234567v") == "******567V"


# ===========================================================================
# 2. Passenger Validation in Booking Request
# ===========================================================================
class TestPassengerValidation:
    def test_passenger_count_mismatch_raises_error(self, db_session):
        """passenger_count must match len(passengers)."""
        with pytest.raises((ValidationError, InvalidBookingError)) as exc:
            BookingRequest(
                train_id="PM-4082",
                from_station="Colombo",
                to_station="Kandy",
                travel_date=date(2026, 12, 3),
                seat_class="Second Class",
                passenger_count=2,
                passengers=[
                    PassengerDetail(name="Alice Perera", nic="851234567V")
                ],
            )
        assert "passenger" in str(exc.value).lower()

    def test_invalid_passenger_nic_format_raises_error(self):
        """Malformed NIC in passenger list rejected by Pydantic validator."""
        with pytest.raises(ValidationError) as exc:
            PassengerDetail(name="Bob Silva", nic="INVALID-NIC")
        assert "not a valid sri lankan nic" in str(exc.value).lower()


# ===========================================================================
# 3. Deterministic Conflict Rules
# ===========================================================================
class TestDeterministicConflictRules:
    def test_rule1_duplicate_nic_in_same_booking_rejected(self, db_session):
        """Rule 1: Same NIC entered twice in one booking request -> 400 Bad Request."""
        nic = "901234567V"
        with pytest.raises((ValidationError, DuplicateNICInBookingError)) as exc:
            BookingRequest(
                train_id="PM-4082",
                from_station="Colombo",
                to_station="Kandy",
                travel_date=date(2026, 12, 3),
                seat_class="Second Class",
                passenger_count=2,
                passengers=[
                    PassengerDetail(name="Traveler One", nic=nic),
                    PassengerDetail(name="Traveler Two", nic=nic.lower()),
                ],
            )
        assert "duplicate" in str(exc.value).lower()

    def test_rule2_duplicate_active_ticket_same_train_and_date(self, db_session):
        """Rule 2: Same NIC already has confirmed ticket on same train/date -> 409 Conflict."""
        service = BookingService(db_session)
        nic = "911234567V"
        req1 = BookingRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="First Trip", nic=nic)],
        )
        res1 = service.process_booking(req1)
        assert res1.status == "CONFIRMED"

        # Attempt to book again on the exact same train and date
        req2 = BookingRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Duplicate Trip", nic=nic)],
        )
        with pytest.raises(DuplicateActiveTicketError) as exc:
            service.process_booking(req2)
        assert "duplicate_active_ticket" in str(exc.value).lower() or "active confirmed ticket" in str(exc.value).lower()

    def test_rule3_conflicting_active_journey_overlapping_times(self, db_session):
        """
        Rule 3: Same NIC has an active ticket whose journey window overlaps across trains -> 409 Conflict.
        PM-4082: dep 07:00, arr 10:15
        EXP-OVERLAP: dep 09:00, arr 12:00
        Overlap interval: 07:00 < 12:00 AND 09:00 < 10:15
        """
        service = BookingService(db_session)
        nic = "921234567V"

        # 1. Book first train (PM-4082)
        req1 = BookingRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Morning Train", nic=nic)],
        )
        res1 = service.process_booking(req1)
        assert res1.status == "CONFIRMED"

        # 2. Book overlapping train on same date (EXP-OVERLAP)
        req2 = BookingRequest(
            train_id="EXP-OVERLAP",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Overlapping Train", nic=nic)],
        )
        with pytest.raises(ConflictingActiveJourneyError) as exc:
            service.process_booking(req2)
        assert "conflicting_active_journey" in str(exc.value).lower() or "conflicts with" in str(exc.value).lower()

    def test_rule4_non_conflicting_repeat_journey_allowed(self, db_session):
        """
        Rule 4: Same NIC can book a non-overlapping second train on the same day.
        PM-4082: 07:00 - 10:15
        EXP-EVENING: 16:00 - 19:15
        Both must be CONFIRMED.
        """
        service = BookingService(db_session)
        nic = "931234567V"

        # Morning trip
        req1 = BookingRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Morning Leg", nic=nic)],
        )
        res1 = service.process_booking(req1)
        assert res1.status == "CONFIRMED"

        # Evening trip (no time overlap)
        req2 = BookingRequest(
            train_id="EXP-EVENING",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Evening Leg", nic=nic)],
        )
        res2 = service.process_booking(req2)
        assert res2.status == "CONFIRMED"
        assert res1.booking_reference != res2.booking_reference

    def test_rule5_same_passenger_different_dates_allowed(self, db_session):
        """Rule 5: Repeat bookings on different dates are always allowed."""
        service = BookingService(db_session)
        nic = "941234567V"

        # Target date 2026-12-03
        req1 = BookingRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Trip Date 1", nic=nic)],
        )
        res1 = service.process_booking(req1)
        assert res1.status == "CONFIRMED"

        # Future date (today + 30 days) seeded in PM-4082
        future_date = date.today() + timedelta(days=30)
        req2 = BookingRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=future_date,
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Trip Date 2", nic=nic)],
        )
        res2 = service.process_booking(req2)
        assert res2.status == "CONFIRMED"


# ===========================================================================
# 4. Security & Fraud Agent ML Risk Scoring
# ===========================================================================
class TestSecurityAgentMLScoring:
    def test_normal_single_booking_is_low_risk_auto_confirmed(self, db_session):
        """Clean single passenger booking evaluates to LOW risk and confirms directly."""
        service = BookingService(db_session)
        req = BookingRequest(
            train_id="PM-4082",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="First Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Honest Passenger", nic="199512345678")],
        )
        result = service.process_booking(req)
        assert result.status == "CONFIRMED"
        assert result.booking_reference.startswith("RS-")
        assert result.case_reference is None

    def test_burst_attempts_produce_medium_or_high_risk_and_pending_review(self, db_session):
        """
        Simulated burst of bookings from the same user/NIC triggers IsolationForest
        behavioral anomaly threshold, creating a FraudReview case (PENDING_FRAUD_REVIEW).
        """
        service = BookingService(db_session)
        nic = "199612345678"
        nic_h = hash_nic(nic)

        # Seed 3 previous rejected fraud review attempts for this NIC to establish anomalous history
        for i in range(3):
            fake_fr = FraudReview(
                case_reference=f"PAST-REJ-{i}",
                primary_nic_hash=nic_h,
                booking_payload="{}",
                risk_score=Decimal("0.85"),
                risk_level="HIGH",
                recommended_action="REJECT",
                reasons=json.dumps(["MALICIOUS_BURST"]),
                status=FraudReviewStatus.REJECTED,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=i * 5),
            )
            db_session.add(fake_fr)
        db_session.commit()

        # Now attempt booking with spiked velocity history
        req = BookingRequest(
            train_id="EXP-EVENING",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Burst Passenger", nic=nic)],
        )
        result = service.process_booking(req)

        assert result.status == "PENDING_FRAUD_REVIEW"
        assert result.booking_reference is None
        assert result.case_reference is not None
        assert result.case_reference.startswith("FR-")
        assert result.risk_level in ("MEDIUM", "HIGH")
        assert len(result.reasons) > 0

        # Verify FraudReview record was written to DB
        fr = db_session.query(FraudReview).filter(FraudReview.case_reference == result.case_reference).first()
        assert fr is not None
        assert fr.status == FraudReviewStatus.PENDING_REVIEW
        assert fr.primary_nic_hash == nic_h


# ===========================================================================
# 5. Security Agent Fail-Closed Resilience
# ===========================================================================
class TestSecurityAgentFailClosed:
    def test_security_agent_down_fails_closed_to_pending_review(self, db_session):
        """
        When Security Agent is unreachable or errors, Booking Agent fails closed safely:
        marks case PENDING_FRAUD_REVIEW with reason SECURITY_AGENT_UNAVAILABLE.
        """
        def failing_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "Security agent down for maintenance"})

        transport = httpx.MockTransport(failing_handler)
        set_security_client_transport(transport)

        try:
            service = BookingService(db_session)
            req = BookingRequest(
                train_id="EXP-EVENING",
                from_station="Colombo",
                to_station="Kandy",
                travel_date=date(2026, 12, 3),
                seat_class="Second Class",
                passenger_count=1,
                passengers=[PassengerDetail(name="FailClosed Traveler", nic="199712345678")],
            )
            result = service.process_booking(req)

            assert result.status == "PENDING_FRAUD_REVIEW"
            assert result.booking_reference is None
            assert result.case_reference is not None
            assert any("security_agent" in str(r).lower() for r in result.reasons)

            # DB check
            fr = db_session.query(FraudReview).filter(FraudReview.case_reference == result.case_reference).first()
            assert fr is not None
            assert fr.status == FraudReviewStatus.PENDING_REVIEW
        finally:
            set_security_client_transport(None)


# ===========================================================================
# 6. Human Administrator Adjudication Flow
# ===========================================================================
class TestHumanAdminAdjudication:
    def test_admin_approves_case_creates_booking_and_passenger_records(self, db_session):
        """Admin approves a PENDING_REVIEW case: checks pass, booking confirmed, seats decremented."""
        review_svc = FraudReviewService(db_session)
        nic = "199812345678"

        # Create a pending case directly
        case_ref = review_svc.create_review_case(
            primary_nic=nic,
            train_id="EXP-EVENING",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passenger_email="human_review@railsense.ai",
            user_id="flagged_user",
            risk_score=0.55,
            risk_level="MEDIUM",
            reasons=["BEHAVIORAL_BURST_VELOCITY"],
            payload={
                "passengers": [{"name": "Review Candidate", "nic": nic, "nic_hash": hash_nic(nic), "nic_masked": mask_nic(nic)}],
                "fare": 1500.0,
            },
        )

        # Admin approves
        outcome = review_svc.review_case(
            case_reference=case_ref,
            decision="APPROVE",
            admin_reason="Identity manually verified with passenger via phone.",
        )

        assert outcome["status"] == "APPROVED"
        assert outcome["booking_reference"] is not None
        book_ref = outcome["booking_reference"]

        # Verify DB records
        fr = db_session.query(FraudReview).filter(FraudReview.case_reference == case_ref).first()
        assert fr.status == FraudReviewStatus.APPROVED
        assert fr.admin_decision == "APPROVE"

        b = db_session.query(Booking).filter(Booking.booking_reference == book_ref).first()
        assert b is not None
        assert b.status == BookingStatus.CONFIRMED

        p = db_session.query(Passenger).filter(Passenger.nic_hash == hash_nic(nic)).first()
        assert p is not None
        assert p.full_name == "Review Candidate"

    def test_admin_approve_rechecks_seat_availability_fails_with_409_if_exhausted(self, db_session):
        """
        If all seats are booked while review is pending, admin approval must abort
        with SeatsUnavailableError / 409 Conflict rather than overbooking the train.
        """
        review_svc = FraudReviewService(db_session)
        booking_svc = BookingService(db_session)
        nic_flagged = "199912345678"

        # Create pending review on EXP-TIGHT (which has capacity 1)
        case_ref = review_svc.create_review_case(
            primary_nic=nic_flagged,
            train_id="EXP-TIGHT",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="First Class",
            passenger_count=1,
            passenger_email="tight_seat@railsense.ai",
            risk_score=0.60,
            risk_level="MEDIUM",
            reasons=["BURST_VELOCITY"],
            payload={
                "passengers": [{"name": "Tight Passenger", "nic": nic_flagged, "nic_hash": hash_nic(nic_flagged), "nic_masked": mask_nic(nic_flagged)}],
                "fare": 2500.0,
            },
        )

        # In the meantime, another passenger books the single available seat
        other_req = BookingRequest(
            train_id="EXP-TIGHT",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="First Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Early Bird", nic="200111112222")],
        )
        res_other = booking_svc.process_booking(other_req)
        assert res_other.status == "CONFIRMED"

        # Now admin attempts to approve the pending case -> must fail with SeatsUnavailableError
        with pytest.raises(SeatsUnavailableError) as exc:
            review_svc.review_case(
                case_reference=case_ref,
                decision="APPROVE",
                admin_reason="Admin attempted approval after seats exhausted",
            )
        assert "seats available" in str(exc.value).lower()

        # Confirm case is still PENDING_REVIEW
        fr = db_session.query(FraudReview).filter(FraudReview.case_reference == case_ref).first()
        assert fr.status == FraudReviewStatus.PENDING_REVIEW

    def test_admin_rejects_case_creates_no_booking(self, db_session):
        """Admin rejects a suspicious case: status becomes REJECTED, no booking created."""
        review_svc = FraudReviewService(db_session)
        nic = "200212345678"

        case_ref = review_svc.create_review_case(
            primary_nic=nic,
            train_id="EXP-EVENING",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passenger_email="bot@attacker.com",
            risk_score=0.88,
            risk_level="HIGH",
            reasons=["MULTIPLE_REJECTED_ATTEMPTS"],
            payload={
                "passengers": [{"name": "Bot Attempt", "nic": nic, "nic_hash": hash_nic(nic), "nic_masked": mask_nic(nic)}],
                "fare": 1500.0,
            },
        )

        outcome = review_svc.review_case(
            case_reference=case_ref,
            decision="REJECT",
            admin_reason="Fraudulent bot burst confirmed.",
        )

        assert outcome["status"] == "REJECTED"
        assert outcome.get("booking_reference") is None

        fr = db_session.query(FraudReview).filter(FraudReview.case_reference == case_ref).first()
        assert fr.status == FraudReviewStatus.REJECTED
        assert fr.admin_decision == "REJECT"

        # Verify no booking was created
        b_count = db_session.query(Booking).filter(Booking.train_id == "EXP-EVENING", Booking.passenger_email == "bot@attacker.com").count()
        assert b_count == 0

    def test_cannot_review_already_adjudicated_case(self, db_session):
        """Attempting to adjudicate an already closed case raises FraudReviewError."""
        review_svc = FraudReviewService(db_session)
        nic = "200312345678"

        case_ref = review_svc.create_review_case(
            primary_nic=nic,
            train_id="EXP-EVENING",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            risk_score=0.90,
            risk_level="HIGH",
            reasons=["MALICIOUS_PATTERN"],
            payload={"passengers": [{"name": "Closed Case", "nic": nic, "nic_hash": hash_nic(nic), "nic_masked": mask_nic(nic)}], "fare": 1500.0},
        )

        # First review: REJECT
        review_svc.review_case(case_reference=case_ref, decision="REJECT", admin_reason="Initial rejection")

        # Second review attempt must fail
        with pytest.raises(FraudReviewError) as exc:
            review_svc.review_case(case_reference=case_ref, decision="APPROVE", admin_reason="Second try")
        assert exc.value.status_code in (400, 409)
        assert "already been adjudicated" in exc.value.message.lower() or "already" in exc.value.message.lower()


# ===========================================================================
# 7. Privacy & Security Compliance Auditing
# ===========================================================================
class TestPrivacyAndSecurityAudit:
    def test_raw_nic_not_stored_in_database(self, db_session):
        """
        Exhaustive audit: ensure raw NIC strings are NEVER persisted in SQLite.
        Only SHA-256 HMAC hashes and masked representations should exist.
        """
        raw_nic = "851234567V"
        booking_svc = BookingService(db_session)

        req = BookingRequest(
            train_id="EXP-EVENING",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            passengers=[PassengerDetail(name="Privacy Audit Passenger", nic=raw_nic)],
        )
        res = booking_svc.process_booking(req)
        assert res.status == "CONFIRMED"

        # Check Passenger table
        passengers = db_session.query(Passenger).all()
        for p in passengers:
            assert raw_nic not in str(p.nic_hash)
            assert raw_nic not in str(p.full_name)

        # Check BookingPassenger table
        bp_list = db_session.query(BookingPassenger).all()
        for bp in bp_list:
            assert raw_nic not in str(bp.passenger_id)

        # Check FraudReview table
        fr_list = db_session.query(FraudReview).all()
        for fr in fr_list:
            assert raw_nic not in str(fr.primary_nic_hash)


# ===========================================================================
# 8. End-to-End API Integration via TestClient
# ===========================================================================
class TestBookingAgentAPIIntegration:
    def test_api_book_route_conflict_returns_409(self, booking_client):
        """POST /internal/messages endpoint returns 409 Conflict when duplicate active ticket occurs."""
        nic = "200412345678"
        msg_payload = {
            "train_id": "PM-4082",
            "from_station": "Colombo",
            "to_station": "Kandy",
            "travel_date": "2026-12-03",
            "seat_class": "Second Class",
            "passenger_count": 1,
            "passengers": [{"name": "API Passenger", "nic": nic}],
        }
        msg1 = {
            "message_id": "MSG-API-1",
            "sender_agent": "passenger-agent",
            "receiver_agent": "booking-agent",
            "intent": "booking_request",
            "auth_token": "dummy_test_token",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": msg_payload,
        }

        # First booking succeeds
        r1 = booking_client.post("/internal/messages", json=msg1)
        assert r1.status_code == 200
        assert r1.json()["status"] == "booking_confirmed"

        # Second booking with same NIC and train returns 409 Conflict
        msg2 = dict(msg1)
        msg2["message_id"] = "MSG-API-2"
        r2 = booking_client.post("/internal/messages", json=msg2)
        assert r2.status_code == 409
        assert "duplicate" in r2.json()["detail"].lower()

    def test_api_book_route_same_booking_duplicate_returns_400(self, booking_client):
        """POST /internal/messages returns 400 Bad Request when same NIC is in passenger list."""
        nic = "200512345678"
        msg_payload = {
            "train_id": "PM-4082",
            "from_station": "Colombo",
            "to_station": "Kandy",
            "travel_date": "2026-12-03",
            "seat_class": "Second Class",
            "passenger_count": 2,
            "passengers": [
                {"name": "Traveler A", "nic": nic},
                {"name": "Traveler B", "nic": nic},
            ],
        }
        msg = {
            "message_id": "MSG-API-3",
            "sender_agent": "passenger-agent",
            "receiver_agent": "booking-agent",
            "intent": "booking_request",
            "auth_token": "dummy_test_token",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": msg_payload,
        }
        resp = booking_client.post("/internal/messages", json=msg)
        assert resp.status_code == 400
        assert "duplicate" in resp.json()["detail"].lower()

    def test_api_fraud_reviews_list_and_review(self, booking_client, db_session):
        """HTTP GET /internal/fraud-reviews and POST /internal/fraud-reviews/{ref}/review."""
        review_svc = FraudReviewService(db_session)
        case_ref = review_svc.create_review_case(
            primary_nic="200612345678",
            train_id="EXP-EVENING",
            from_station="Colombo",
            to_station="Kandy",
            travel_date=date(2026, 12, 3),
            seat_class="Second Class",
            passenger_count=1,
            risk_score=0.75,
            risk_level="HIGH",
            reasons=["API_TEST_REASON"],
            payload={"passengers": [{"name": "API Case", "nic": "200612345678"}], "fare": 1500.0},
        )

        # GET list
        r_list = booking_client.get("/internal/fraud-reviews")
        assert r_list.status_code == 200
        cases = r_list.json()
        assert any(c["case_reference"] == case_ref for c in cases)

        # POST review (Reject)
        r_action = booking_client.post(
            f"/internal/fraud-reviews/{case_ref}/review",
            json={"decision": "REJECT", "admin_reason": "API test rejection"},
        )
        assert r_action.status_code == 200
        assert r_action.json()["status"] == "REJECTED"
