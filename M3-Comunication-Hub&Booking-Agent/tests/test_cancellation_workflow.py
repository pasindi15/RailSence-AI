"""
tests/test_cancellation_workflow.py
-----------------------------------
End-to-End Test Suite for RailSense AI Cancellation Workflow & Human-in-the-Loop Admin Review:

1. Chat Cancellation Intent & Extraction:
   - Extract booking reference and preserve exact original reason
   - Confirmation card action generation
2. NLP Classification & Entity Extraction:
   - Rule-based reason classification for all 7 supported categories
   - Extraction of duplicate_booking, personal_emergency, schedule_change, etc.
3. RAG Policy Knowledge Retrieval:
   - Retrieve verified policy passages with citations
   - Relevant policy evidence for duplicate bookings and emergencies
4. Deterministic Refund & Eligibility Calculations:
   - Duplicate booking: 100% refund
   - Service disruption: 100% refund
   - Medical emergency: 80% refund
   - Advance notice (>48h): 75% refund
   - Standard notice (24-48h): 50% refund
   - Late notice (<24h): 0% non-refundable
   - Precise Decimal arithmetic
5. Real Booking Validation:
   - Valid booking retrieved from database
   - Non-existent booking reference returns clean 404
   - Already cancelled booking returns clean 409
6. Persistence to cancellation_requests:
   - Case reference format CN-XXXXX
   - Initial status is strictly PENDING_ADMIN_REVIEW
   - Booking.status remains CONFIRMED
7. Grounded LLM Advisory Summary:
   - Contains verified facts only (no hallucinated figures)
   - Lacks authority to approve/reject
8. Human-in-the-Loop Admin Review:
   - Admin APPROVE transitions Booking.status -> CANCELLED and CancellationRequest.status -> APPROVED
   - Admin REJECT keeps Booking.status as CONFIRMED and transitions CancellationRequest.status -> REJECTED
   - AI cannot approve automatically
9. Browser Security:
   - JWT secret and connection strings never leak to client responses
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path Setup
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).resolve().parent
_M3_ROOT = _TESTS_DIR.parent
_WORKSPACE_ROOT = _M3_ROOT.parent
_FRONTEND_DIR = _WORKSPACE_ROOT / "frontend"
_BOOKING_AGENT_DIR = _M3_ROOT / "booking-agent"
_AGENT_HUB_DIR = _M3_ROOT / "agent-hub"

for p in (str(_M3_ROOT), str(_WORKSPACE_ROOT), str(_FRONTEND_DIR), str(_BOOKING_AGENT_DIR), str(_AGENT_HUB_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Load serve.py app
spec_serve = importlib.util.spec_from_file_location("frontend_serve_canc", str(_FRONTEND_DIR / "serve.py"))
serve_mod = importlib.util.module_from_spec(spec_serve)
spec_serve.loader.exec_module(serve_mod)
client = TestClient(serve_mod.app)

from cancellation.nlp import classify_cancellation_reason, extract_cancellation_entities, process_cancellation_nlp
from cancellation.rag import retrieve_relevant_policies
from cancellation.rules import calculate_cancellation_refund
from cancellation.llm import generate_admin_advisory_summary
from cancellation.service import (
    CancellationService,
    BookingNotFoundError,
    BookingAlreadyCancelledError,
    CancellationAlreadyPendingError,
)
from database.database import SessionLocal
from database.models import Booking, BookingStatus, CancellationRequest, CancellationStatus, Train, TrainSchedule


class TestCancellationNLPExtraction:
    """Tests for NLP intent detection, entity extraction, and reason classification."""

    def test_passenger_chat_cancellation_extraction(self):
        """Extract booking reference RS-84521 and preserve exact original reason."""
        resp = client.post("/api/chat", json={
            "message": "Cancel booking RS-84521 because I accidentally booked twice"
        })
        assert resp.status_code == 200
        data = resp.json()

        assert data["intent"] == "cancel_booking"
        cancellation = data.get("cancellation")
        assert cancellation is not None
        assert cancellation["booking_reference"] == "RS-84521"
        assert cancellation["reason"] == "I accidentally booked twice"

        action = data.get("action")
        assert action is not None
        assert action["type"] == "cancellation_confirmation_card"
        assert action["booking_reference"] == "RS-84521"
        assert action["reason"] == "I accidentally booked twice"

    def test_reason_classification_all_categories(self):
        """Test rule-based classification across all 7 supported categories."""
        assert classify_cancellation_reason("I accidentally booked twice") == "duplicate_booking"
        assert classify_cancellation_reason("Charged twice for the same ticket") == "duplicate_booking"
        assert classify_cancellation_reason("Family medical emergency, admitted to hospital") == "personal_emergency"
        assert classify_cancellation_reason("My office meeting got rescheduled to next week") == "schedule_change"
        assert classify_cancellation_reason("I selected the wrong date by mistake") == "wrong_booking"
        assert classify_cancellation_reason("The train was cancelled due to railway strike") == "service_issue"
        assert classify_cancellation_reason("Our vacation plans changed and we are not traveling") == "travel_plan_changed"
        assert classify_cancellation_reason("I just do not want to go anymore") == "other"

    def test_entity_extraction_from_cancellation_text(self):
        """Extract booking reference, train ID, and station names."""
        text = "Please cancel booking RS-98124 for train PM-4082 from Colombo to Kandy on 2026-12-03"
        entities = extract_cancellation_entities(text)
        assert entities["booking_reference"] == "RS-98124"
        assert entities["train_id"] == "PM-4082"
        assert "Colombo" in entities["stations"]
        assert "Kandy" in entities["stations"]
        assert entities["travel_date"] == "2026-12-03"


class TestCancellationRAGPolicyRetrieval:
    """Tests for Policy Knowledge Base retrieval and citations."""

    def test_rag_retrieves_duplicate_booking_policy(self):
        """RAG retrieves relevant policy chunks for duplicate bookings."""
        chunks = retrieve_relevant_policies("I accidentally booked twice for the same trip", top_k=3)
        assert len(chunks) > 0
        citations = [c["citation"] for c in chunks]
        # Ensure duplicate reservation or refund policy was retrieved
        assert any("Duplicate" in cit or "POL-REF" in cit or "POL-RES" in cit for cit in citations)
        assert all("citation" in c and "content" in c and "similarity_score" in c for c in chunks)

    def test_rag_retrieves_emergency_and_refund_tiers(self):
        """RAG retrieves refund schedules for medical emergency."""
        chunks = retrieve_relevant_policies("hospital emergency medical illness cancellation", top_k=3)
        assert len(chunks) > 0
        content_text = " ".join(c["content"] for c in chunks).lower()
        assert "emergency" in content_text or "refund" in content_text


class TestDeterministicRefundCalculation:
    """Tests for deterministic financial and eligibility business rules."""

    def test_duplicate_booking_refund_calculation(self):
        """Duplicate booking grants 100% refund."""
        fare = Decimal("2400.00")
        target_date = date.today() + timedelta(days=10)
        res = calculate_cancellation_refund(
            fare=fare,
            travel_date=target_date,
            reason_category="duplicate_booking",
        )
        assert res.eligibility == "ELIGIBLE"
        assert res.suggested_refund == Decimal("2400.00")
        assert res.refund_percentage == 100
        assert res.deduction_amount == Decimal("0.00")

    def test_service_issue_refund_calculation(self):
        """Railway disruption grants 100% full refund."""
        fare = Decimal("5000.00")
        res = calculate_cancellation_refund(
            fare=fare,
            travel_date=date.today() + timedelta(days=1),
            reason_category="service_issue",
        )
        assert res.eligibility == "FULL_REFUND"
        assert res.suggested_refund == Decimal("5000.00")
        assert res.refund_percentage == 100

    def test_medical_emergency_refund_calculation(self):
        """Medical emergency grants 80% refund recommendation."""
        fare = Decimal("2500.00")
        res = calculate_cancellation_refund(
            fare=fare,
            travel_date=date.today() + timedelta(days=2),
            reason_category="personal_emergency",
        )
        assert res.eligibility == "ELIGIBLE"
        assert res.suggested_refund == Decimal("2000.00")  # 80% of 2500
        assert res.refund_percentage == 80
        assert res.deduction_amount == Decimal("500.00")

    def test_standard_tiers_by_hours_until_departure(self):
        """Verify 75% (>48h), 50% (24-48h), and 0% (<24h)."""
        fare = Decimal("1000.00")
        # 1. >48 hours notice
        res_48h = calculate_cancellation_refund(
            fare=fare,
            travel_date=date.today() + timedelta(days=5),
            reason_category="other",
        )
        assert res_48h.eligibility == "ELIGIBLE"
        assert res_48h.suggested_refund == Decimal("750.00")
        assert res_48h.refund_percentage == 75

        # 2. 24-48 hours notice
        now = datetime.now(timezone.utc)
        dep_dt_30h = now + timedelta(hours=30)
        res_30h = calculate_cancellation_refund(
            fare=fare,
            travel_date=dep_dt_30h.date(),
            departure_time=dep_dt_30h.time(),
            reason_category="other",
            current_time=now,
        )
        assert res_30h.eligibility == "PARTIAL_REFUND"
        assert res_30h.suggested_refund == Decimal("500.00")
        assert res_30h.refund_percentage == 50

        # 3. <24 hours notice
        dep_dt_5h = now + timedelta(hours=5)
        res_5h = calculate_cancellation_refund(
            fare=fare,
            travel_date=dep_dt_5h.date(),
            departure_time=dep_dt_5h.time(),
            reason_category="other",
            current_time=now,
        )
        assert res_5h.eligibility == "INELIGIBLE"
        assert res_5h.suggested_refund == Decimal("0.00")
        assert res_5h.refund_percentage == 0


class TestCancellationServiceAndAdminReview:
    """End-to-End tests for booking retrieval, case creation, and human admin adjudication."""

    @pytest.fixture
    def test_booking(self):
        """Create a dedicated confirmed test booking for cancellation testing."""
        with SessionLocal() as db:
            train = db.query(Train).filter_by(train_id="PM-4082").first()
            if not train:
                train = Train(train_id="PM-4082", train_name="Intercity Express", active=True)
                db.add(train)
                db.flush()

            travel_dt = date.today() + timedelta(days=14)
            schedule = db.query(TrainSchedule).filter_by(train_id=train.id, travel_date=travel_dt).first()
            if not schedule:
                schedule = TrainSchedule(
                    train_id=train.id,
                    from_station="Colombo",
                    to_station="Kandy",
                    travel_date=travel_dt,
                    departure_time=time(6, 0),
                    arrival_time=time(9, 30),
                    first_class_capacity=50,
                    second_class_capacity=150,
                )
                db.add(schedule)
                db.flush()

            ref = f"RS-TEST-{datetime.now().strftime('%M%S%f')[:6]}"
            booking = Booking(
                booking_reference=ref,
                user_id="cancellation_tester",
                train_id=train.id,
                schedule_id=schedule.id,
                from_station="Colombo",
                to_station="Kandy",
                travel_date=travel_dt,
                seat_class="Second Class",
                passenger_count=2,
                fare=Decimal("2400.00"),
                status=BookingStatus.CONFIRMED,
            )
            db.add(booking)
            db.commit()
            db.refresh(booking)
            return ref

    def test_cancellation_request_nonexistent_booking_fails(self):
        """Non-existent booking reference returns clean 404 error."""
        resp = client.post("/api/cancellations/confirm", json={
            "booking_reference": "RS-NONEXISTENT-999",
            "reason": "Accidental booking"
        })
        assert resp.status_code == 404
        assert "does not exist" in resp.json()["error"].lower() or "not found" in resp.json()["error"].lower()

    def test_successful_cancellation_request_creation(self, test_booking):
        """
        Submitting valid cancellation:
        - Creates CN-XXXXX case in Supabase
        - Status is PENDING_ADMIN_REVIEW
        - Booking remains CONFIRMED initially
        - AI summary is grounded with verified facts
        """
        ref = test_booking
        reason = "I accidentally booked twice due to network delay"

        resp = client.post("/api/cancellations/confirm", json={
            "booking_reference": ref,
            "reason": reason
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        c = data["cancellation"]
        case_ref = c["case_reference"]
        assert case_ref.startswith("CN-")
        assert c["cancellation_status"] == "PENDING_ADMIN_REVIEW"
        assert c["booking_status"] == "CONFIRMED"
        assert c["reason_category"] == "duplicate_booking"
        assert c["suggested_refund"] == "2400.00"

        # AI summary is grounded
        ai_sum = c["ai_summary"]
        assert ref in ai_sum
        assert "Colombo to Kandy" in ai_sum
        assert "2400.00" in ai_sum
        assert "Advisory" in ai_sum or "Approve" in ai_sum

        # Verify database record
        with SessionLocal() as db:
            case_row = db.query(CancellationRequest).filter_by(case_reference=case_ref).first()
            assert case_row is not None
            assert case_row.status == CancellationStatus.PENDING_ADMIN_REVIEW

            booking_row = db.query(Booking).filter_by(booking_reference=ref).first()
            assert booking_row.status == BookingStatus.CONFIRMED  # Strictly CONFIRMED!

    def test_cannot_submit_duplicate_cancellation_request(self, test_booking):
        """Cannot submit a second cancellation request while one is already pending."""
        ref = test_booking
        # First request
        r1 = client.post("/api/cancellations/confirm", json={
            "booking_reference": ref,
            "reason": "First cancellation attempt"
        })
        assert r1.status_code == 200

        # Second request must fail with 409
        r2 = client.post("/api/cancellations/confirm", json={
            "booking_reference": ref,
            "reason": "Second cancellation attempt"
        })
        assert r2.status_code == 409
        assert "already" in r2.json()["error"].lower() or "pending" in r2.json()["error"].lower()

    def test_human_in_the_loop_admin_approval(self, test_booking):
        """
        When human admin approves:
        - CancellationRequest.status -> APPROVED
        - Booking.status -> CANCELLED
        """
        ref = test_booking
        r_create = client.post("/api/cancellations/confirm", json={
            "booking_reference": ref,
            "reason": "Duplicate ticket purchase"
        })
        case_ref = r_create.json()["cancellation"]["case_reference"]

        # Admin approves
        resp_review = client.post(f"/api/admin/cancellations/{case_ref}/review", json={
            "decision": "APPROVE",
            "admin_reason": "Verified duplicate booking in ledger."
        })
        assert resp_review.status_code == 200
        review_data = resp_review.json()

        assert review_data["cancellation_status"] == "APPROVED"
        assert review_data["admin_decision"] == "APPROVED"
        assert review_data["booking_status"] == "CANCELLED"

        # Verify in database
        with SessionLocal() as db:
            case_row = db.query(CancellationRequest).filter_by(case_reference=case_ref).first()
            assert case_row.status == CancellationStatus.APPROVED
            assert case_row.reviewed_at is not None

            booking_row = db.query(Booking).filter_by(booking_reference=ref).first()
            assert booking_row.status == BookingStatus.CANCELLED

    def test_human_in_the_loop_admin_rejection(self, test_booking):
        """
        When human admin rejects:
        - CancellationRequest.status -> REJECTED
        - Booking.status remains CONFIRMED
        """
        ref = test_booking
        r_create = client.post("/api/cancellations/confirm", json={
            "booking_reference": ref,
            "reason": "Travel plans changed last minute"
        })
        case_ref = r_create.json()["cancellation"]["case_reference"]

        # Admin rejects
        resp_review = client.post(f"/api/admin/cancellations/{case_ref}/review", json={
            "decision": "REJECT",
            "admin_reason": "Does not meet refund criteria."
        })
        assert resp_review.status_code == 200
        review_data = resp_review.json()

        assert review_data["cancellation_status"] == "REJECTED"
        assert review_data["admin_decision"] == "REJECTED"
        assert review_data["booking_status"] == "CONFIRMED"

        # Verify in database
        with SessionLocal() as db:
            case_row = db.query(CancellationRequest).filter_by(case_reference=case_ref).first()
            assert case_row.status == CancellationStatus.REJECTED

            booking_row = db.query(Booking).filter_by(booking_reference=ref).first()
            assert booking_row.status == BookingStatus.CONFIRMED  # Remains CONFIRMED!

    def test_cannot_cancel_already_cancelled_booking(self, test_booking):
        """A booking that has already been cancelled cannot be cancelled again."""
        ref = test_booking
        # Submit and approve cancellation
        r1 = client.post("/api/cancellations/confirm", json={
            "booking_reference": ref,
            "reason": "Accidental booking"
        })
        case_ref = r1.json()["cancellation"]["case_reference"]
        client.post(f"/api/admin/cancellations/{case_ref}/review", json={"decision": "APPROVE"})

        # Second cancellation attempt on now-CANCELLED booking
        r2 = client.post("/api/cancellations/confirm", json={
            "booking_reference": ref,
            "reason": "Try to cancel again"
        })
        assert r2.status_code == 409
        assert "already cancelled" in r2.json()["error"].lower()

    def test_zero_secrets_leakage_in_cancellation_flow(self, test_booking):
        """Ensure no JWT secret, database URL, or internal token is leaked in responses."""
        resp = client.post("/api/cancellations/confirm", json={
            "booking_reference": test_booking,
            "reason": "Duplicate ticket purchase"
        })
        text = resp.text
        assert "change-me" not in text
        assert "postgresql" not in text
        assert "auth_token" not in text
        assert "secret" not in text.lower()
