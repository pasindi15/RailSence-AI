"""
tests/test_phase2_audit.py
--------------------------
RailSense AI — Member C Phase 2 Communication Hub Audit Logging Tests.

Covers:
  - Valid authenticated request creates audit record (status: AUTHENTICATED)
  - Invalid JWT produces rejected status (status: REJECTED)
  - Unknown receiver produces rejected status (status: REJECTED)
  - Token is never stored in AuditLog
  - Payload is not unnecessarily stored in AuditLog
  - Timestamp and message identity are retained
  - Audit database failure returns clean HTTP 500 without leaking credentials
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timezone, timedelta, date
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
MEMBER_C = os.path.dirname(os.path.dirname(__file__))   # member-c/
AGENT_HUB = os.path.join(MEMBER_C, "agent-hub")
BOOKING_AGENT = os.path.join(MEMBER_C, "booking-agent")

for p in (MEMBER_C, AGENT_HUB, BOOKING_AGENT):
    if p not in sys.path:
        sys.path.insert(0, p)

from database.models import AuditLog, AuditStatus, Base
from hub_database import get_db

# Dynamically load agent-hub/main.py
HUB_MAIN = os.path.join(AGENT_HUB, "main.py")
spec = importlib.util.spec_from_file_location("hub_main_audit", HUB_MAIN)
hub_mod = importlib.util.module_from_spec(spec)
sys.modules["hub_main_audit"] = hub_mod
spec.loader.exec_module(hub_mod)
hub_app = hub_mod.app

# ---------------------------------------------------------------------------
# In-Memory SQLite Test Database Setup (StaticPool preserves tables across sessions)
# ---------------------------------------------------------------------------
TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def setup_test_db():
    """Create fresh audit tables before each test and tear down after."""
    Base.metadata.create_all(bind=TEST_ENGINE, tables=[AuditLog.__table__])
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE, tables=[AuditLog.__table__])


def override_get_db():
    """Dependency override providing isolated in-memory test database sessions."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


hub_app.dependency_overrides[get_db] = override_get_db
client = TestClient(hub_app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()
NOW_ISO = datetime.now(timezone.utc).isoformat()
TEST_SECRET = os.getenv("JWT_SECRET_KEY", "change-me")


def create_token(sub: str = "passenger-agent", exp_delta_seconds: int = 3600) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": sub,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=exp_delta_seconds)).timestamp()),
        },
        TEST_SECRET,
        algorithm="HS256",
    )


VALID_MESSAGE = {
    "message_id": "MSG-3001",
    "sender_agent": "passenger-agent",
    "receiver_agent": "booking-agent",
    "intent": "booking_request",
    "payload": {
        "from_station": "Colombo",
        "to_station": "Kandy",
        "travel_date": FUTURE_DATE,
        "train_id": "PM-4082",
        "seat_class": "Second Class",
        "passenger_count": 2,
    },
    "auth_token": create_token(sub="passenger-agent"),
    "timestamp": NOW_ISO,
}


# ===========================================================================
# Test Cases
# ===========================================================================

class TestCommunicationHubAudit:
    """Test suite for Communication Hub audit persistence."""

    def test_valid_authenticated_request_creates_audit_record(self):
        """A valid authenticated message creates an AuditLog row with AUTHENTICATED status."""
        response = client.post("/messages", json=VALID_MESSAGE)
        assert response.status_code == 200

        # Query test database directly
        with TestingSessionLocal() as session:
            record = session.query(AuditLog).filter_by(message_id="MSG-3001").first()
            assert record is not None
            assert record.sender_agent == "passenger-agent"
            assert record.receiver_agent == "booking-agent"
            assert record.intent == "booking_request"
            assert record.status in (AuditStatus.AUTHENTICATED, AuditStatus.ROUTED)
            assert record.error_message is None

    def test_invalid_jwt_produces_rejected_status(self):
        """A message failing JWT verification logs a REJECTED audit record before returning 401."""
        data = {
            **VALID_MESSAGE,
            "message_id": "MSG-BAD-JWT",
            "auth_token": "invalid.corrupted.jwt",
        }
        response = client.post("/messages", json=data)
        assert response.status_code == 401

        with TestingSessionLocal() as session:
            record = session.query(AuditLog).filter_by(message_id="MSG-BAD-JWT").first()
            assert record is not None
            assert record.status == AuditStatus.REJECTED
            assert record.error_message == "Invalid or expired authentication token"

    def test_unknown_receiver_produces_rejected_status(self):
        """A message with an unrecognised receiver logs a REJECTED audit record before returning 404."""
        data = {
            **VALID_MESSAGE,
            "message_id": "MSG-BAD-RCV",
            "receiver_agent": "unregistered-service",
        }
        response = client.post("/messages", json=data)
        assert response.status_code == 404

        with TestingSessionLocal() as session:
            record = session.query(AuditLog).filter_by(message_id="MSG-BAD-RCV").first()
            assert record is not None
            assert record.status == AuditStatus.REJECTED
            assert "not registered" in record.error_message

    def test_token_is_never_stored_in_audit_log(self):
        """Verify privacy rule: auth_token column does not exist and is never stored."""
        # 1. Inspect ORM columns
        column_names = [c.name for c in AuditLog.__table__.columns]
        assert "auth_token" not in column_names
        assert "jwt" not in column_names
        assert "token" not in column_names

        # 2. Inspect persisted record
        response = client.post("/messages", json=VALID_MESSAGE)
        assert response.status_code == 200

        with TestingSessionLocal() as session:
            record = session.query(AuditLog).first()
            assert not hasattr(record, "auth_token")

    def test_payload_is_not_unnecessarily_stored(self):
        """Verify privacy rule: message payload contents are not stored in the audit table."""
        column_names = [c.name for c in AuditLog.__table__.columns]
        assert "payload" not in column_names

    def test_timestamp_and_identity_retained(self):
        """Verify traceability: message_id and original timestamp are accurately retained."""
        custom_time = "2026-09-08T10:30:00+00:00"
        data = {
            **VALID_MESSAGE,
            "message_id": "MSG-TRACE-99",
            "timestamp": custom_time,
        }
        response = client.post("/messages", json=data)
        assert response.status_code == 200

        with TestingSessionLocal() as session:
            record = session.query(AuditLog).filter_by(message_id="MSG-TRACE-99").first()
            assert record is not None
            assert record.message_id == "MSG-TRACE-99"
            assert record.timestamp is not None

    def test_database_failure_returns_clean_500(self):
        """Audit database errors result in HTTP 500 without leaking connection credentials."""
        # Simulate database failure during write_audit_log commit
        with patch.object(Session, "commit", side_effect=Exception("DB connection dropped")):
            data = {
                **VALID_MESSAGE,
                "message_id": "MSG-DB-FAIL",
            }
            response = client.post("/messages", json=data)
            assert response.status_code == 500
            body = response.json()
            assert body["detail"] == "Audit logging service failed to persist message trace."
            # Verify no DB credentials or internal file traces are leaked
            assert "postgresql" not in str(body)
            assert "password" not in str(body)
