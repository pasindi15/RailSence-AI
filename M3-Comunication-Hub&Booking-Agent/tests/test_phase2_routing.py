"""
tests/test_phase2_routing.py
----------------------------
RailSense AI — Member C Phase 2 Communication Hub Routing Tests.

Covers:
  - test_route_to_booking_agent
  - test_unknown_receiver
  - test_destination_unavailable (503)
  - test_destination_timeout (504)
  - test_destination_error (502)
  - test_success_sets_routed_audit_status
  - test_failure_sets_failed_audit_status
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timezone, timedelta, date
from unittest.mock import AsyncMock, patch

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
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
from router import RoutingError, get_http_client, route_message

# Dynamically load agent-hub/main.py and booking-agent/main.py
HUB_MAIN = os.path.join(AGENT_HUB, "main.py")
spec_hub = importlib.util.spec_from_file_location("hub_main_routing", HUB_MAIN)
hub_mod = importlib.util.module_from_spec(spec_hub)
sys.modules["hub_main_routing"] = hub_mod
spec_hub.loader.exec_module(hub_mod)
hub_app = hub_mod.app

BOOKING_MAIN = os.path.join(BOOKING_AGENT, "main.py")
spec_bk = importlib.util.spec_from_file_location("bk_main_routing", BOOKING_MAIN)
bk_mod = importlib.util.module_from_spec(spec_bk)
sys.modules["bk_main_routing"] = bk_mod
spec_bk.loader.exec_module(bk_mod)
booking_app = bk_mod.app

# ---------------------------------------------------------------------------
# Test In-Memory Database
# ---------------------------------------------------------------------------
TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


from database.seed import seed_test_train_data
from database.database import get_db as get_booking_db

@pytest.fixture(autouse=True)
def setup_test_db():
    """Create fresh database tables before each test and drop after."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestingSessionLocal() as db:
        seed_test_train_data(db)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


hub_app.dependency_overrides[get_db] = override_get_db
booking_app.dependency_overrides[get_booking_db] = override_get_db
client = TestClient(hub_app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Token & Message Helpers
# ---------------------------------------------------------------------------
TEST_SECRET = os.getenv("JWT_SECRET_KEY", "change-me")
FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()
NOW_ISO = datetime.now(timezone.utc).isoformat()


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


VALID_MESSAGE = {
    "message_id": "MSG-ROUTE-101",
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
    "auth_token": make_token(),
    "timestamp": NOW_ISO,
}


# ===========================================================================
# Test Cases
# ===========================================================================

class TestCommunicationHubRouting:
    """Test suite for Communication Hub asynchronous routing pipeline."""

    def test_route_to_booking_agent(self):
        """Hub forwards message to booking-agent and returns structured response."""
        # Use in-process ASGITransport to route to actual booking_app
        transport = httpx.ASGITransport(app=booking_app)
        async def override_client():
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8003") as ac:
                yield ac

        hub_app.dependency_overrides[get_http_client] = override_client

        response = client.post("/messages", json=VALID_MESSAGE)
        assert response.status_code == 200
        body = response.json()
        assert body["message_id"] == "MSG-ROUTE-101"
        assert body["status"] == "routed"
        assert body["receiver_agent"] == "booking-agent"
        assert "response" in body
        assert body["response"]["status"] in ("received_for_phase_1", "booking_confirmed")
        if body["response"]["status"] == "booking_confirmed":
            assert "booking" in body["response"]
        else:
            assert body["response"]["intent"] == "booking_request"

    def test_unknown_receiver(self):
        """Unknown receiver fails at validation stage with HTTP 404 before routing."""
        data = {
            **VALID_MESSAGE,
            "message_id": "MSG-UNKNOWN-RCV",
            "receiver_agent": "nonexistent-agent",
        }
        response = client.post("/messages", json=data)
        assert response.status_code == 404
        assert "not registered" in response.json()["detail"]

    def test_destination_unavailable(self):
        """Connection refused maps to HTTP 503 (Service Unavailable)."""
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        async def override_unavailable():
            yield mock_client

        hub_app.dependency_overrides[get_http_client] = override_unavailable

        response = client.post("/messages", json=VALID_MESSAGE)
        assert response.status_code == 503
        body = response.json()
        assert "unavailable" in body["detail"].lower()

    def test_destination_timeout(self):
        """Destination request timeout maps to HTTP 504 (Gateway Timeout)."""
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ReadTimeout("Read timed out")

        async def override_timeout():
            yield mock_client

        hub_app.dependency_overrides[get_http_client] = override_timeout

        response = client.post("/messages", json=VALID_MESSAGE)
        assert response.status_code == 504
        body = response.json()
        assert "timed out" in body["detail"].lower()

    def test_destination_error(self):
        """Destination 5xx/4xx error maps to HTTP 502 (Bad Gateway)."""
        mock_client = AsyncMock()
        mock_client.post.return_value = httpx.Response(
            status_code=500,
            text="Internal Server Error",
            request=httpx.Request("POST", "http://localhost:8003/internal/messages"),
        )

        async def override_error():
            yield mock_client

        hub_app.dependency_overrides[get_http_client] = override_error

        response = client.post("/messages", json=VALID_MESSAGE)
        assert response.status_code == 502
        body = response.json()
        assert "server error" in body["detail"].lower()

    def test_success_sets_routed_audit_status(self):
        """Successfully routed message records AuditStatus.ROUTED in audit_logs."""
        transport = httpx.ASGITransport(app=booking_app)
        async def override_client():
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8003") as ac:
                yield ac

        hub_app.dependency_overrides[get_http_client] = override_client

        data = {**VALID_MESSAGE, "message_id": "MSG-AUDIT-ROUTED"}
        response = client.post("/messages", json=data)
        assert response.status_code == 200

        with TestingSessionLocal() as session:
            record = session.query(AuditLog).filter_by(message_id="MSG-AUDIT-ROUTED").first()
            assert record is not None
            assert record.status == AuditStatus.ROUTED
            assert record.error_message is None

    def test_failure_sets_failed_audit_status(self):
        """Failed routing records AuditStatus.FAILED with concise error in audit_logs."""
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        async def override_fail():
            yield mock_client

        hub_app.dependency_overrides[get_http_client] = override_fail

        data = {**VALID_MESSAGE, "message_id": "MSG-AUDIT-FAILED"}
        response = client.post("/messages", json=data)
        assert response.status_code == 503

        with TestingSessionLocal() as session:
            record = session.query(AuditLog).filter_by(message_id="MSG-AUDIT-FAILED").first()
            assert record is not None
            assert record.status == AuditStatus.FAILED
            assert record.error_message is not None
            assert "unavailable" in record.error_message.lower()
