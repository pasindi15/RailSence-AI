"""
tests/test_cancellation_rejection_nlp_audit.py
----------------------------------------------
Comprehensive Test Suite for RailSense AI Administrator Rejection Workflow:
1. NLP Classification of Administrator Rejection Reasons
2. Entity & Policy Marker Extraction from Admin Messages
3. Audit Log Persistence in audit_logs Table with AuditStatus.REJECTED
4. Email Notification with Typed Admin Reason
5. Rejection API Endpoints and Real-time NLP Preview
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

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
spec_serve = importlib.util.spec_from_file_location("frontend_serve_rejection", str(_FRONTEND_DIR / "serve.py"))
serve_mod = importlib.util.module_from_spec(spec_serve)
sys.modules["frontend_serve_rejection"] = serve_mod
spec_serve.loader.exec_module(serve_mod)
client = TestClient(serve_mod.app)

from cancellation.nlp import analyze_admin_rejection_reason
from cancellation.service import CancellationService
from database.database import SessionLocal
from database.models import (
    AuditLog,
    AuditStatus,
    Booking,
    BookingStatus,
    CancellationRequest,
    CancellationStatus,
    Train,
    TrainSchedule,
)
from notifications.email_service import EmailService, get_email_service


class TestAdminRejectionNLP:
    """Unit tests for NLP classification and entity extraction on admin rejection reasons."""

    def test_nlp_classifies_late_notice(self):
        """Messages citing late departure notice are classified as LATE_NOTICE_INELIGIBLE."""
        msg = "Cancellation requested less than 24 hours prior to scheduled departure. Non-refundable per Section 4.2."
        res = analyze_admin_rejection_reason(msg)
        assert res["rejection_category"] == "LATE_NOTICE_INELIGIBLE"
        assert "Section 4.2" in res["policy_citations"]
        assert any("24 hours" in t for t in res["time_references"])
        assert "Timing" in res["tone"]
        assert "non-refundable" in res["polished_explanation"].lower()

    def test_nlp_classifies_unverified_duplicate(self):
        """Messages citing no duplicate record are classified as UNVERIFIED_DUPLICATE."""
        msg = "Audited central reservation ledger and found single ticket only. No duplicate found for this passenger."
        res = analyze_admin_rejection_reason(msg)
        assert res["rejection_category"] == "UNVERIFIED_DUPLICATE"
        assert "Ledger" in res["tone"] or "Audit" in res["tone"]
        assert "duplicate" in res["polished_explanation"].lower()

    def test_nlp_classifies_missing_documentation(self):
        """Messages citing missing medical certificates are classified as MISSING_DOCUMENTATION."""
        msg = "Passenger claimed medical emergency but no doctor note or medical certificate was provided as proof."
        res = analyze_admin_rejection_reason(msg)
        assert res["rejection_category"] == "MISSING_DOCUMENTATION"
        assert "Documentation" in res["tone"]
        assert "documentation" in res["polished_explanation"].lower()

    def test_nlp_classifies_non_refundable_fare(self):
        """Messages citing promotional or saver conditions are classified as NON_REFUNDABLE_FARE."""
        msg = "Ticket was issued under promotional advance saver terms and is strictly non-refundable."
        res = analyze_admin_rejection_reason(msg)
        assert res["rejection_category"] == "NON_REFUNDABLE_FARE"
        assert "Fare" in res["tone"]

    def test_nlp_classifies_policy_exclusion(self):
        """Messages citing policy codes are classified as POLICY_EXCLUSION."""
        msg = "Request violates railway regulations under POL-REF-003 clause 4."
        res = analyze_admin_rejection_reason(msg)
        assert res["rejection_category"] == "POLICY_EXCLUSION"
        assert "POL-REF-003" in res["policy_citations"]

    def test_nlp_handles_empty_or_discretionary_reason(self):
        """Fallback when no specific keywords match."""
        res = analyze_admin_rejection_reason("Denied per station master order.")
        assert res["rejection_category"] == "ADMINISTRATIVE_DISCRETION"
        assert res["raw_reason"] == "Denied per station master order."


class TestRejectionAuditAndEmailPersistence:
    """Integration tests for audit logging, database persistence, and email transmission."""

    @pytest.fixture
    def test_cancellation_case(self):
        """Create a dedicated confirmed booking and pending cancellation request."""
        with SessionLocal() as db:
            train = db.query(Train).filter_by(train_id="PM-4082").first()
            if not train:
                train = Train(train_id="PM-4082", train_name="Intercity Express", active=True)
                db.add(train)
                db.flush()

            travel_dt = date.today() + timedelta(days=15)
            sched = db.query(TrainSchedule).filter_by(train_id=train.id, travel_date=travel_dt).first()
            if not sched:
                sched = TrainSchedule(
                    train_id=train.id,
                    from_station="Colombo",
                    to_station="Kandy",
                    travel_date=travel_dt,
                    departure_time=time(6, 0),
                    arrival_time=time(9, 30),
                    first_class_capacity=50,
                    second_class_capacity=150,
                )
                db.add(sched)
                db.flush()

            import uuid
            uid = uuid.uuid4().hex[:8].upper()
            ref = f"RS-REJ-{uid}"
            booking = Booking(
                booking_reference=ref,
                user_id="rejection_tester",
                train_id=train.id,
                schedule_id=sched.id,
                from_station="Colombo",
                to_station="Kandy",
                travel_date=travel_dt,
                seat_class="Second Class",
                passenger_count=1,
                passenger_email="passenger_audit@example.com",
                fare=Decimal("1500.00"),
                status=BookingStatus.CONFIRMED,
            )
            db.add(booking)
            db.flush()

            case_ref = f"CN-TEST-{uid}"
            case = CancellationRequest(
                case_reference=case_ref,
                booking_id=booking.id,
                reason="Changed my mind last minute",
                reason_category="travel_plan_changed",
                eligibility="INELIGIBLE",
                suggested_refund=Decimal("0.00"),
                ai_summary="Advisory: review late notice",
                status=CancellationStatus.PENDING_ADMIN_REVIEW,
            )
            db.add(case)
            db.commit()
            return case_ref, ref

    def test_rejection_persists_to_audit_logs_with_nlp(self, test_cancellation_case):
        """
        When admin rejects with typed explanation:
        1. CancellationRequest.status -> REJECTED
        2. CancellationRequest.admin_reason -> typed explanation
        3. Booking.status remains CONFIRMED
        4. audit_logs table receives record with status REJECTED containing NLP metadata
        """
        case_ref, booking_ref = test_cancellation_case
        typed_explanation = "Cancellation requested less than 24 hours before departure. Non-refundable per Section 4.2."

        with SessionLocal() as db:
            service = CancellationService(db)
            res = service.review_cancellation(
                case_reference=case_ref,
                decision="REJECT",
                admin_reason=typed_explanation,
            )

            assert res["success"] is True
            assert res["cancellation_status"] == "REJECTED"
            assert res["admin_decision"] == "REJECTED"
            assert res["admin_reason"] == typed_explanation
            assert res["booking_status"] == "CONFIRMED"
            assert res["nlp_analysis"] is not None
            assert res["nlp_analysis"]["rejection_category"] == "LATE_NOTICE_INELIGIBLE"
            assert res["audit_logged"] is True

            # Verify in audit_logs table
            audit_row = (
                db.query(AuditLog)
                .filter(AuditLog.intent == "cancellation_review_rejection")
                .order_by(AuditLog.id.desc())
                .first()
            )
            assert audit_row is not None
            assert audit_row.status == AuditStatus.REJECTED
            assert audit_row.sender_agent == "admin-adjudicator"
            assert audit_row.receiver_agent == "booking-agent"
            assert typed_explanation in audit_row.error_message
            assert "LATE_NOTICE_INELIGIBLE" in audit_row.error_message
            assert booking_ref in audit_row.error_message

    def test_rejection_email_dispatches_with_typed_reason(self, test_cancellation_case):
        """Rejection email receives the exact typed reason from the administrator."""
        case_ref, booking_ref = test_cancellation_case
        typed_explanation = "Medical certificate was not attached to substantiate the emergency claim."

        email_svc = get_email_service()
        with patch.object(email_svc, "send_cancellation_rejected_email") as mock_reject_email:
            with SessionLocal() as db:
                service = CancellationService(db)
                service.review_cancellation(
                    case_reference=case_ref,
                    decision="REJECT",
                    admin_reason=typed_explanation,
                )

            mock_reject_email.assert_called_once()
            call_kwargs = mock_reject_email.call_args[1]
            assert call_kwargs["booking_reference"] == booking_ref
            assert call_kwargs["recipient_email"] == "passenger_audit@example.com"
            assert call_kwargs["admin_reason"] == typed_explanation


class TestAdminRejectionApiEndpoints:
    """Test HTTP API endpoints for NLP preview and admin review execution."""

    def test_api_nlp_preview_endpoint(self):
        """POST /api/admin/cancellations/nlp-preview returns real-time NLP classification."""
        resp = client.post("/api/admin/cancellations/nlp-preview", json={
            "reason": "Late request submitted within 24 hours of departure"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["rejection_category"] == "LATE_NOTICE_INELIGIBLE"
        assert "category_label" in data
        assert "tone" in data
        assert "polished_explanation" in data

    def test_api_admin_rejection_execution(self):
        """POST /api/admin/cancellations/{case_reference}/review with REJECT and typed message."""
        with SessionLocal() as db:
            train = db.query(Train).filter_by(train_id="PM-4082").first()
            if not train:
                train = Train(train_id="PM-4082", train_name="Intercity Express", active=True)
                db.add(train)
                db.flush()

            travel_dt = date.today() + timedelta(days=22)
            sched = db.query(TrainSchedule).filter_by(train_id=train.id, travel_date=travel_dt).first()
            if not sched:
                sched = TrainSchedule(
                    train_id=train.id,
                    from_station="Colombo",
                    to_station="Kandy",
                    travel_date=travel_dt,
                    departure_time=time(6, 0),
                    arrival_time=time(9, 30),
                    first_class_capacity=50,
                    second_class_capacity=150,
                )
                db.add(sched)
                db.flush()

            import uuid
            uid_api = uuid.uuid4().hex[:8].upper()
            ref = f"RS-API-{uid_api}"
            b = Booking(
                booking_reference=ref,
                user_id="api_tester",
                train_id=train.id,
                schedule_id=sched.id,
                from_station="Colombo",
                to_station="Kandy",
                travel_date=travel_dt,
                seat_class="Second Class",
                passenger_count=1,
                passenger_email="api_test@example.com",
                fare=Decimal("1200.00"),
                status=BookingStatus.CONFIRMED,
            )
            db.add(b)
            db.flush()

            case_ref = f"CN-API-{uid_api}"
            case = CancellationRequest(
                case_reference=case_ref,
                booking_id=b.id,
                reason="Trip cancelled",
                status=CancellationStatus.PENDING_ADMIN_REVIEW,
            )
            db.add(case)
            db.commit()

        typed_reason = "Denied because the passenger did not provide required supporting documentation."
        resp = client.post(f"/api/admin/cancellations/{case_ref}/review", json={
            "decision": "REJECT",
            "admin_reason": typed_reason,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["cancellation_status"] == "REJECTED"
        assert data["admin_decision"] == "REJECTED"
        assert data["admin_reason"] == typed_reason
        assert data["booking_status"] == "CONFIRMED"
