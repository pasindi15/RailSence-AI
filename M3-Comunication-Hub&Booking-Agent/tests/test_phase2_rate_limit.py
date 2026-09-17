"""
tests/test_phase2_rate_limit.py
--------------------------------
RailSense AI — Member C Phase 2 Communication Hub Per-Agent Rate Limiting Tests.

Covers:
  1. Requests below limit succeed (HTTP 200)
  2. Request at allowed boundary succeeds (e.g. 5 requests within 1 second)
  3. Request above limit returns HTTP 429 Too Many Requests (detail: "Rate limit exceeded")
  4. Rejected request is NOT forwarded to the destination agent
  5. Rate limits are tracked independently per sender_agent
  6. Rejected flood request creates REJECTED audit entry with error_message="Rate limit exceeded"
  7. auth_token, JWT secret, and payload contents are NOT stored in audit log
  8. Rate window resets after time elapses, allowing subsequent requests
  9. Unit tests for AgentRateLimiter sliding window logic
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
MEMBER_C = os.path.dirname(os.path.dirname(__file__))   # M3 root
AGENT_HUB = os.path.join(MEMBER_C, "agent-hub")
BOOKING_AGENT = os.path.join(MEMBER_C, "booking-agent")

for p in (MEMBER_C, AGENT_HUB, BOOKING_AGENT):
    if p not in sys.path:
        sys.path.insert(0, p)

from database.models import AuditLog, AuditStatus, Base
from hub_database import get_db
from rate_limit import AgentRateLimiter, rate_limiter

# Dynamically load agent-hub/main.py
HUB_MAIN = os.path.join(AGENT_HUB, "main.py")
spec_hub = importlib.util.spec_from_file_location("hub_main_ratelimit", HUB_MAIN)
hub_mod = importlib.util.module_from_spec(spec_hub)
sys.modules["hub_main_ratelimit"] = hub_mod
spec_hub.loader.exec_module(hub_mod)
hub_app = hub_mod.app

# ---------------------------------------------------------------------------
# Test In-Memory Database
# ---------------------------------------------------------------------------
TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def setup_test_db_and_limiter():
    """Create fresh database tables and reset rate limiter before each test."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    rate_limiter.reset()
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)
    rate_limiter.reset()


def override_get_db():
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
TEST_SECRET = os.getenv("JWT_SECRET_KEY", "change-me")
FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()


def make_token(sub: str = "passenger-agent") -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": sub,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        TEST_SECRET,
        algorithm="HS256",
    )


def make_message(
    msg_id: str = "MSG-RL-001",
    sender: str = "passenger-agent",
    receiver: str = "booking-agent",
) -> dict:
    return {
        "message_id": msg_id,
        "sender_agent": sender,
        "receiver_agent": receiver,
        "intent": "booking_request",
        "payload": {
            "from_station": "Colombo",
            "to_station": "Kandy",
            "travel_date": FUTURE_DATE,
            "train_id": "PM-4082",
            "seat_class": "Second Class",
            "passenger_count": 2,
        },
        "auth_token": make_token(sub=sender),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ===========================================================================
# 1. AgentRateLimiter Unit Tests
# ===========================================================================

class TestAgentRateLimiterUnit:
    def test_default_limits(self):
        limiter = AgentRateLimiter()
        assert limiter.limit_per_second >= 1
        assert limiter.limit_per_minute >= limiter.limit_per_second

    def test_per_second_boundary_and_exceeded(self):
        limiter = AgentRateLimiter(rate_limit_per_second=3, rate_limit_per_minute=20)
        t0 = 1000.0

        # First 3 requests at t0 succeed
        assert limiter.is_allowed("agent-a", current_time=t0) is True
        assert limiter.is_allowed("agent-a", current_time=t0 + 0.1) is True
        assert limiter.is_allowed("agent-a", current_time=t0 + 0.2) is True

        # 4th request at t0 + 0.3 fails (exceeds 3/sec)
        assert limiter.is_allowed("agent-a", current_time=t0 + 0.3) is False

        # After 1.1s, window has slid, request succeeds
        assert limiter.is_allowed("agent-a", current_time=t0 + 1.1) is True

    def test_per_minute_boundary_and_exceeded(self):
        limiter = AgentRateLimiter(rate_limit_per_second=100, rate_limit_per_minute=4)
        t0 = 2000.0

        for i in range(4):
            assert limiter.is_allowed("agent-b", current_time=t0 + (i * 2.0)) is True

        # 5th request at t0 + 10.0 exceeds 4/min limit
        assert limiter.is_allowed("agent-b", current_time=t0 + 10.0) is False

        # After 61 seconds from t0, the first request has expired
        assert limiter.is_allowed("agent-b", current_time=t0 + 60.5) is True

    def test_independent_agents(self):
        limiter = AgentRateLimiter(rate_limit_per_second=2, rate_limit_per_minute=10)
        t0 = 3000.0

        assert limiter.is_allowed("passenger-agent", current_time=t0) is True
        assert limiter.is_allowed("passenger-agent", current_time=t0 + 0.1) is True
        # passenger-agent exhausted
        assert limiter.is_allowed("passenger-agent", current_time=t0 + 0.2) is False

        # booking-agent and operations-agent must NOT be blocked
        assert limiter.is_allowed("booking-agent", current_time=t0 + 0.2) is True
        assert limiter.is_allowed("operations-agent", current_time=t0 + 0.2) is True

    def test_empty_agent_rejected(self):
        limiter = AgentRateLimiter()
        assert limiter.is_allowed("") is False


# ===========================================================================
# 2. Communication Hub Integration Tests
# ===========================================================================

class TestHubRateLimitingIntegration:
    @patch.object(hub_mod, "route_message")
    def test_requests_below_limit_succeed(self, mock_route):
        """Requests below limit should route successfully with HTTP 200."""
        mock_route.return_value = (200, {"status": "confirmed", "booking_reference": "RS-RL-01"})

        msg = make_message(msg_id="MSG-RL-BELOW-1", sender="passenger-agent")
        resp = client.post("/messages", json=msg)

        assert resp.status_code == 200
        assert resp.json()["status"] == "routed"
        assert mock_route.call_count == 1

    @patch.object(hub_mod, "route_message")
    def test_allowed_boundary_succeeds(self, mock_route):
        """Exact limit boundary requests succeed."""
        mock_route.return_value = (200, {"status": "ok"})
        limit = rate_limiter.limit_per_second

        for i in range(limit):
            msg = make_message(msg_id=f"MSG-RL-BOUND-{i}", sender="passenger-agent")
            resp = client.post("/messages", json=msg)
            assert resp.status_code == 200, f"Request {i+1}/{limit} unexpectedly failed: {resp.text}"

        assert mock_route.call_count == limit

    @patch.object(hub_mod, "route_message")
    def test_request_above_limit_returns_429(self, mock_route):
        """Request exceeding limit must return HTTP 429 Too Many Requests."""
        mock_route.return_value = (200, {"status": "ok"})
        limit = rate_limiter.limit_per_second

        # Exhaust limit
        for i in range(limit):
            msg = make_message(msg_id=f"MSG-RL-BURST-{i}", sender="passenger-agent")
            resp = client.post("/messages", json=msg)
            assert resp.status_code == 200

        # Next request must be rejected with 429
        flood_msg = make_message(msg_id="MSG-RL-BURST-EXCEED", sender="passenger-agent")
        resp_flood = client.post("/messages", json=flood_msg)

        assert resp_flood.status_code == 429
        data = resp_flood.json()
        assert data.get("detail") == "Rate limit exceeded"

    @patch.object(hub_mod, "route_message")
    def test_rejected_request_is_not_forwarded(self, mock_route):
        """Downstream route_message must NOT be invoked for rejected flood requests."""
        mock_route.return_value = (200, {"status": "ok"})
        limit = rate_limiter.limit_per_second

        for i in range(limit):
            client.post("/messages", json=make_message(msg_id=f"MSG-FWD-{i}", sender="passenger-agent"))

        calls_before = mock_route.call_count

        # Exceed limit
        flood_msg = make_message(msg_id="MSG-FWD-EXCEED", sender="passenger-agent")
        resp = client.post("/messages", json=flood_msg)

        assert resp.status_code == 429
        # Ensure route_message was NOT called again
        assert mock_route.call_count == calls_before

    @patch.object(hub_mod, "route_message")
    def test_independent_rate_limits_per_sender_agent(self, mock_route):
        """Exhausting passenger-agent rate limit must NOT block booking-agent or operations-agent."""
        mock_route.return_value = (200, {"status": "ok"})
        limit = rate_limiter.limit_per_second

        # Exhaust passenger-agent
        for i in range(limit):
            resp = client.post("/messages", json=make_message(msg_id=f"MSG-PA-{i}", sender="passenger-agent"))
            assert resp.status_code == 200

        # Verify passenger-agent is now blocked
        resp_pa_blocked = client.post(
            "/messages",
            json=make_message(msg_id="MSG-PA-BLOCKED", sender="passenger-agent"),
        )
        assert resp_pa_blocked.status_code == 429

        # Verify booking-agent can still post successfully
        resp_booking = client.post(
            "/messages",
            json=make_message(msg_id="MSG-BK-OK", sender="booking-agent", receiver="passenger-agent"),
        )
        assert resp_booking.status_code == 200

        # Verify operations-agent can also still post successfully
        resp_ops = client.post(
            "/messages",
            json=make_message(msg_id="MSG-OPS-OK", sender="operations-agent", receiver="passenger-agent"),
        )
        assert resp_ops.status_code == 200

    @patch.object(hub_mod, "route_message")
    def test_rejected_request_creates_audit_entry(self, mock_route):
        """Rejected flood requests must write an audit entry with status REJECTED."""
        mock_route.return_value = (200, {"status": "ok"})
        limit = rate_limiter.limit_per_second

        for i in range(limit):
            client.post("/messages", json=make_message(msg_id=f"MSG-AUD-{i}", sender="passenger-agent"))

        flood_msg = make_message(msg_id="MSG-AUD-FLOOD-999", sender="passenger-agent")
        resp = client.post("/messages", json=flood_msg)
        assert resp.status_code == 429

        # Check database audit record
        with TestingSessionLocal() as db:
            audit = db.query(AuditLog).filter(AuditLog.message_id == "MSG-AUD-FLOOD-999").first()
            assert audit is not None
            assert audit.status == AuditStatus.REJECTED
            assert audit.error_message == "Rate limit exceeded"
            assert audit.sender_agent == "passenger-agent"
            assert audit.receiver_agent == "booking-agent"
            assert audit.intent == "booking_request"

    @patch.object(hub_mod, "route_message")
    def test_auth_token_and_secrets_never_in_audit_log(self, mock_route):
        """Ensure auth_token, JWT secret, and payload contents are not in audit log."""
        mock_route.return_value = (200, {"status": "ok"})
        limit = rate_limiter.limit_per_second

        for i in range(limit):
            client.post("/messages", json=make_message(msg_id=f"MSG-SEC-{i}", sender="passenger-agent"))

        secret_token = make_token("passenger-agent")
        flood_msg = make_message(msg_id="MSG-PRIVACY-CHECK", sender="passenger-agent")
        flood_msg["auth_token"] = secret_token

        resp = client.post("/messages", json=flood_msg)
        assert resp.status_code == 429

        with TestingSessionLocal() as db:
            audit = db.query(AuditLog).filter(AuditLog.message_id == "MSG-PRIVACY-CHECK").first()
            assert audit is not None
            # Verify no token or secret leak
            assert not hasattr(audit, "auth_token")
            assert not hasattr(audit, "payload")
            assert TEST_SECRET not in str(audit.error_message)
            assert secret_token not in str(audit.error_message)
