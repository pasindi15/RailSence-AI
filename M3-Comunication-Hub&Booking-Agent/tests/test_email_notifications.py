"""
tests/test_email_notifications.py
---------------------------------
Comprehensive Test Suite for RailSense AI Email Notifications:
1. Booking success triggers booking confirmation email
2. Booking failure sends no email
3. Cancellation PENDING sends no final email (Human-in-the-Loop constraint)
4. Admin approval triggers approved email with refund information
5. Admin rejection triggers rejected email with admin reason
6. Email failure does not rollback confirmed booking
7. Email failure does not rollback admin decision
8. SMTP credentials are never exposed to the frontend
9. Passenger email is stored and retrieved correctly from Supabase / SQLite
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
spec_serve = importlib.util.spec_from_file_location("frontend_serve_email", str(_FRONTEND_DIR / "serve.py"))
serve_mod = importlib.util.module_from_spec(spec_serve)
sys.modules["frontend_serve_email"] = serve_mod
spec_serve.loader.exec_module(serve_mod)
client = TestClient(serve_mod.app)

from database.database import SessionLocal
from database.models import Booking, BookingStatus, CancellationRequest, CancellationStatus, Train, TrainSchedule
from notifications.email_service import EmailService, get_email_service
from schemas.booking import BookingRequest


@pytest.fixture
def setup_schedule():
    """Ensure a valid test train and schedule exist in database."""
    with SessionLocal() as db:
        train = db.query(Train).filter_by(train_id="PM-4082").first()
        if not train:
            train = Train(train_id="PM-4082", train_name="Intercity Express", active=True)
            db.add(train)
            db.flush()

        travel_dt = date.today() + timedelta(days=20)
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
            db.commit()
            db.refresh(schedule)
        return travel_dt


class TestEmailNotificationService:
    """Unit tests for EmailService methods, formatting, and safety."""

    def test_booking_confirmation_email_content(self):
        """Test booking confirmation email contains all required journey details."""
        svc = EmailService(host="mockhost")
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            res = svc.send_booking_confirmation_email(
                recipient_email="passenger@test.com",
                booking_reference="RS-99881",
                from_station="Colombo",
                to_station="Kandy",
                travel_date="2026-10-15",
                train_id="PM-4082",
                seat_class="Second Class",
                passenger_count=2,
                fare="2400.00",
                status="CONFIRMED",
            )
            assert res is True
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            to_email, subject, text_body, html_body = args
            assert to_email == "passenger@test.com"
            assert subject == "RailSense AI - Booking Confirmed"
            assert "RS-99881" in text_body
            assert "Colombo to Kandy" in text_body
            assert "2026-10-15" in text_body
            assert "PM-4082" in text_body
            assert "Second Class" in text_body
            assert "2" in text_body
            assert "2400.00" in text_body
            assert "CONFIRMED" in text_body

    def test_cancellation_approved_email_content(self):
        """Test cancellation approved email contains refund and route details."""
        svc = EmailService(host="mockhost")
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            res = svc.send_cancellation_approved_email(
                recipient_email="passenger@test.com",
                booking_reference="RS-99881",
                refund_amount="2400.00",
                from_station="Colombo",
                to_station="Kandy",
                travel_date="2026-10-15",
                admin_reason="Full refund approved per policy.",
            )
            assert res is True
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            to_email, subject, text_body, _ = args
            assert to_email == "passenger@test.com"
            assert subject == "RailSense AI - Cancellation Approved"
            assert "RS-99881" in text_body
            assert "APPROVED" in text_body
            assert "2400.00" in text_body
            assert "Full refund approved per policy." in text_body

    def test_cancellation_rejected_email_content(self):
        """Test cancellation rejected email contains admin reason and confirmed status."""
        svc = EmailService(host="mockhost")
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            res = svc.send_cancellation_rejected_email(
                recipient_email="passenger@test.com",
                booking_reference="RS-99881",
                admin_reason="Late notice within 24h departure.",
                from_station="Colombo",
                to_station="Kandy",
                travel_date="2026-10-15",
            )
            assert res is True
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            to_email, subject, text_body, _ = args
            assert to_email == "passenger@test.com"
            assert subject == "RailSense AI - Cancellation Request Rejected"
            assert "RS-99881" in text_body
            assert "REJECTED" in text_body
            assert "CONFIRMED" in text_body
            assert "Late notice within 24h departure." in text_body

    def test_missing_recipient_email_returns_false_safely(self):
        """If recipient email is missing, return False without crashing."""
        svc = EmailService()
        assert svc.send_booking_confirmation_email(None, "RS-1", "A", "B", "2026-10-10", "T-1", "2nd", 1, "100") is False
        assert svc.send_cancellation_approved_email(None, "RS-1", "100") is False
        assert svc.send_cancellation_rejected_email(None, "RS-1", "Reason") is False


class TestEndToEndEmailWorkflow:
    """Integration tests for booking, cancellation, and admin review notifications."""

    def test_booking_success_triggers_confirmation_email(self, setup_schedule):
        """Successful booking triggers booking confirmation email."""
        travel_dt = setup_schedule
        test_email = f"traveler_{datetime.now().strftime('%M%S%f')[:5]}@example.com"

        email_svc = get_email_service()
        with patch.object(email_svc, "send_booking_confirmation_email") as mock_confirm:
            resp = client.post("/api/bookings/confirm", json={
                "from_station": "Colombo",
                "to_station": "Kandy",
                "travel_date": travel_dt.isoformat(),
                "train_id": "PM-4082",
                "seat_class": "Second Class",
                "passenger_count": 2,
                "passenger_email": test_email,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            ref = data["booking"]["booking_reference"]

            # Verify email sender was triggered
            mock_confirm.assert_called_once()
            call_kwargs = mock_confirm.call_args[1]
            assert call_kwargs["recipient_email"] == test_email
            assert call_kwargs["booking_reference"] == ref
            assert call_kwargs["status"] == "CONFIRMED"

            # Verify passenger_email stored in database
            with SessionLocal() as db:
                row = db.query(Booking).filter_by(booking_reference=ref).first()
                assert row is not None
                assert row.passenger_email == test_email

    def test_booking_failure_sends_no_email(self, setup_schedule):
        """Failed booking (e.g. invalid date or stations) triggers no email."""
        email_svc = get_email_service()
        with patch.object(email_svc, "send_booking_confirmation_email") as mock_confirm:
            resp = client.post("/api/bookings/confirm", json={
                "from_station": "InvalidStation",
                "to_station": "Nowhere",
                "travel_date": "2026-10-15",
                "train_id": "PM-4082",
                "seat_class": "Second Class",
                "passenger_count": 2,
                "passenger_email": "passenger@example.com",
            })
            # Booking fails
            assert resp.status_code in (400, 404, 502, 503)
            mock_confirm.assert_not_called()

    def test_cancellation_pending_sends_no_final_email(self, setup_schedule):
        """
        HUMAN-IN-THE-LOOP RULE:
        Submitting a cancellation request (PENDING_ADMIN_REVIEW) must NOT send
        approved or rejected email before human administrator reviews it.
        """
        travel_dt = setup_schedule
        test_email = "pending_tester@example.com"

        # Create confirmed booking
        with SessionLocal() as db:
            train = db.query(Train).filter_by(train_id="PM-4082").first()
            sched = db.query(TrainSchedule).filter_by(train_id=train.id, travel_date=travel_dt).first()
            ref = f"RS-PEND-{datetime.now().strftime('%M%S%f')[:5]}"
            b = Booking(
                booking_reference=ref,
                user_id="email_tester",
                train_id=train.id,
                schedule_id=sched.id,
                from_station="Colombo",
                to_station="Kandy",
                travel_date=travel_dt,
                seat_class="Second Class",
                passenger_count=1,
                passenger_email=test_email,
                fare=Decimal("1200.00"),
                status=BookingStatus.CONFIRMED,
            )
            db.add(b)
            db.commit()

        email_svc = get_email_service()
        with patch.object(email_svc, "send_cancellation_approved_email") as mock_app, \
             patch.object(email_svc, "send_cancellation_rejected_email") as mock_rej:
            # Submit cancellation
            r_canc = client.post("/api/cancellations/confirm", json={
                "booking_reference": ref,
                "reason": "Accidental reservation duplicate"
            })
            assert r_canc.status_code == 200
            assert r_canc.json()["cancellation"]["cancellation_status"] == "PENDING_ADMIN_REVIEW"

            # Neither approval nor rejection email should have been sent!
            mock_app.assert_not_called()
            mock_rej.assert_not_called()

    def test_admin_approval_triggers_approved_email(self, setup_schedule):
        """Admin APPROVE triggers Cancellation Approved email with refund details."""
        travel_dt = setup_schedule
        test_email = "approvee@example.com"

        with SessionLocal() as db:
            train = db.query(Train).filter_by(train_id="PM-4082").first()
            sched = db.query(TrainSchedule).filter_by(train_id=train.id, travel_date=travel_dt).first()
            ref = f"RS-APP-{datetime.now().strftime('%M%S%f')[:5]}"
            b = Booking(
                booking_reference=ref,
                user_id="email_tester",
                train_id=train.id,
                schedule_id=sched.id,
                from_station="Colombo",
                to_station="Kandy",
                travel_date=travel_dt,
                seat_class="Second Class",
                passenger_count=1,
                passenger_email=test_email,
                fare=Decimal("1200.00"),
                status=BookingStatus.CONFIRMED,
            )
            db.add(b)
            db.commit()

        # Submit cancellation
        r_canc = client.post("/api/cancellations/confirm", json={
            "booking_reference": ref,
            "reason": "Double booked ticket"
        })
        case_ref = r_canc.json()["cancellation"]["case_reference"]

        email_svc = get_email_service()
        with patch.object(email_svc, "send_cancellation_approved_email") as mock_app:
            resp_rev = client.post(f"/api/admin/cancellations/{case_ref}/review", json={
                "decision": "APPROVE",
                "admin_reason": "Verified duplicate booking."
            })
            assert resp_rev.status_code == 200
            assert resp_rev.json()["cancellation_status"] == "APPROVED"

            mock_app.assert_called_once()
            call_kwargs = mock_app.call_args[1]
            assert call_kwargs["recipient_email"] == test_email
            assert call_kwargs["booking_reference"] == ref
            assert call_kwargs["refund_amount"] == "1200.00"
            assert call_kwargs["admin_reason"] == "Verified duplicate booking."

    def test_admin_rejection_triggers_rejected_email(self, setup_schedule):
        """Admin REJECT triggers Cancellation Rejected email with admin reason."""
        travel_dt = setup_schedule
        test_email = "rejectee@example.com"

        with SessionLocal() as db:
            train = db.query(Train).filter_by(train_id="PM-4082").first()
            sched = db.query(TrainSchedule).filter_by(train_id=train.id, travel_date=travel_dt).first()
            ref = f"RS-REJ-{datetime.now().strftime('%M%S%f')[:5]}"
            b = Booking(
                booking_reference=ref,
                user_id="email_tester",
                train_id=train.id,
                schedule_id=sched.id,
                from_station="Colombo",
                to_station="Kandy",
                travel_date=travel_dt,
                seat_class="Second Class",
                passenger_count=1,
                passenger_email=test_email,
                fare=Decimal("1200.00"),
                status=BookingStatus.CONFIRMED,
            )
            db.add(b)
            db.commit()

        # Submit cancellation
        r_canc = client.post("/api/cancellations/confirm", json={
            "booking_reference": ref,
            "reason": "Changed my mind"
        })
        case_ref = r_canc.json()["cancellation"]["case_reference"]

        email_svc = get_email_service()
        with patch.object(email_svc, "send_cancellation_rejected_email") as mock_rej:
            resp_rev = client.post(f"/api/admin/cancellations/{case_ref}/review", json={
                "decision": "REJECT",
                "admin_reason": "Non-refundable personal schedule change."
            })
            assert resp_rev.status_code == 200
            assert resp_rev.json()["cancellation_status"] == "REJECTED"

            mock_rej.assert_called_once()
            call_kwargs = mock_rej.call_args[1]
            assert call_kwargs["recipient_email"] == test_email
            assert call_kwargs["booking_reference"] == ref
            assert call_kwargs["admin_reason"] == "Non-refundable personal schedule change."

            # Booking remains confirmed
            with SessionLocal() as db:
                row = db.query(Booking).filter_by(booking_reference=ref).first()
                assert row.status == BookingStatus.CONFIRMED

    def test_email_failure_does_not_rollback_booking(self, setup_schedule):
        """
        NON-BLOCKING RESILIENCE:
        If SMTP throws an error or connection fails, the booking MUST remain
        committed and CONFIRMED in the database.
        """
        travel_dt = setup_schedule
        test_email = "crash_smtp@example.com"

        email_svc = get_email_service()
        # Mock low-level delivery raising an unexpected SMTP error
        with patch.object(email_svc, "_send_email", side_effect=Exception("SMTP connection refused")):
            resp = client.post("/api/bookings/confirm", json={
                "from_station": "Colombo",
                "to_station": "Kandy",
                "travel_date": travel_dt.isoformat(),
                "train_id": "PM-4082",
                "seat_class": "Second Class",
                "passenger_count": 1,
                "passenger_email": test_email,
            })
            # Booking itself must succeed
            assert resp.status_code == 200
            ref = resp.json()["booking"]["booking_reference"]

            # Database check: booking exists and is CONFIRMED
            with SessionLocal() as db:
                row = db.query(Booking).filter_by(booking_reference=ref).first()
                assert row is not None
                assert row.status == BookingStatus.CONFIRMED
                assert row.passenger_email == test_email

    def test_email_failure_does_not_rollback_admin_decision(self, setup_schedule):
        """
        NON-BLOCKING RESILIENCE:
        If SMTP fails during admin review, the admin decision must NOT be rolled back.
        """
        travel_dt = setup_schedule
        test_email = "admin_smtp_crash@example.com"

        with SessionLocal() as db:
            train = db.query(Train).filter_by(train_id="PM-4082").first()
            sched = db.query(TrainSchedule).filter_by(train_id=train.id, travel_date=travel_dt).first()
            ref = f"RS-FAIL-{datetime.now().strftime('%M%S%f')[:5]}"
            b = Booking(
                booking_reference=ref,
                user_id="email_tester",
                train_id=train.id,
                schedule_id=sched.id,
                from_station="Colombo",
                to_station="Kandy",
                travel_date=travel_dt,
                seat_class="Second Class",
                passenger_count=1,
                passenger_email=test_email,
                fare=Decimal("1200.00"),
                status=BookingStatus.CONFIRMED,
            )
            db.add(b)
            db.commit()

        r_canc = client.post("/api/cancellations/confirm", json={
            "booking_reference": ref,
            "reason": "Duplicate"
        })
        case_ref = r_canc.json()["cancellation"]["case_reference"]

        email_svc = get_email_service()
        with patch.object(email_svc, "_send_email", side_effect=Exception("SMTP timeout")):
            resp_rev = client.post(f"/api/admin/cancellations/{case_ref}/review", json={
                "decision": "APPROVE",
                "admin_reason": "Approved despite notification outage."
            })
            assert resp_rev.status_code == 200

            # Database check: decision is APPROVED and booking is CANCELLED
            with SessionLocal() as db:
                case_row = db.query(CancellationRequest).filter_by(case_reference=case_ref).first()
                assert case_row.status == CancellationStatus.APPROVED
                b_row = db.query(Booking).filter_by(booking_reference=ref).first()
                assert b_row.status == BookingStatus.CANCELLED

    def test_smtp_credentials_not_exposed_to_frontend(self):
        """Ensure no SMTP password, username, or internal secrets leak to frontend."""
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert "SMTP_PASSWORD" not in html
        assert "smtp.gmail.com" not in html
        assert "your-app-password" not in html
