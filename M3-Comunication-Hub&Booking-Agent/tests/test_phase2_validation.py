"""
tests/test_phase2_validation.py
-------------------------------
RailSense AI — Member C Phase 2 Validation & Receiver Tests.

Covers:
  - test_valid_agent_message
  - test_missing_message_id
  - test_invalid_intent
  - test_invalid_timestamp
  - test_missing_auth_token
  - test_known_receiver
  - test_unknown_receiver
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timezone, timedelta, date

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
MEMBER_C = os.path.dirname(os.path.dirname(__file__))   # member-c/
AGENT_HUB = os.path.join(MEMBER_C, "agent-hub")

for p in (MEMBER_C, AGENT_HUB):
    if p not in sys.path:
        sys.path.insert(0, p)

# Dynamically load agent-hub/main.py
HUB_MAIN = os.path.join(AGENT_HUB, "main.py")
spec = importlib.util.spec_from_file_location("hub_main_p2", HUB_MAIN)
hub_mod = importlib.util.module_from_spec(spec)
sys.modules["hub_main_p2"] = hub_mod
spec.loader.exec_module(hub_mod)
hub_app = hub_mod.app

client = TestClient(hub_app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Test Fixtures / Payloads
# ---------------------------------------------------------------------------
FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()
NOW_ISO = datetime.now(timezone.utc).isoformat()

import jwt

VALID_TOKEN = jwt.encode(
    {
        "sub": "passenger-agent",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    },
    os.getenv("JWT_SECRET_KEY", "change-me"),
    algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
)

VALID_MESSAGE = {
    "message_id": "MSG-2001",
    "sender_agent": "passenger-agent",
    "receiver_agent": "booking-agent",
    "intent": "booking_request",
    "payload": {
        "from_station": "Colombo",
        "to_station": "Kandy",
        "travel_date": FUTURE_DATE,
        "train_id": "PM-4082",
        "seat_class": "Second Class",
        "passenger_count": 1,
    },
    "auth_token": VALID_TOKEN,
    "timestamp": NOW_ISO,
}


class TestHubMessageValidation:
    """Test suite for Phase 2 AgentMessage and receiver validation."""

    def test_valid_agent_message(self):
        """A well-formed AgentMessage with a known receiver succeeds with 200."""
        response = client.post("/messages", json=VALID_MESSAGE)
        assert response.status_code == 200
        body = response.json()
        assert body["message_id"] == "MSG-2001"
        assert body["status"] in ("validated", "routed")
        assert body["receiver_agent"] == "booking-agent"
        assert "note" in body

    def test_missing_message_id(self):
        """Omitting message_id fails Pydantic schema validation with 422."""
        data = {k: v for k, v in VALID_MESSAGE.items() if k != "message_id"}
        response = client.post("/messages", json=data)
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any(err["loc"][-1] == "message_id" for err in errors)

    def test_missing_sender_agent(self):
        """Omitting sender_agent fails Pydantic schema validation with 422."""
        data = {k: v for k, v in VALID_MESSAGE.items() if k != "sender_agent"}
        response = client.post("/messages", json=data)
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any(err["loc"][-1] == "sender_agent" for err in errors)

    def test_missing_receiver_agent(self):
        """Omitting receiver_agent fails Pydantic schema validation with 422."""
        data = {k: v for k, v in VALID_MESSAGE.items() if k != "receiver_agent"}
        response = client.post("/messages", json=data)
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any(err["loc"][-1] == "receiver_agent" for err in errors)

    def test_invalid_intent(self):
        """Supplying an unknown intent fails schema validation with 422."""
        data = {**VALID_MESSAGE, "intent": "non_existent_intent"}
        response = client.post("/messages", json=data)
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any(err["loc"][-1] == "intent" for err in errors)

    def test_invalid_timestamp(self):
        """An invalid timestamp string fails schema validation with 422."""
        data = {**VALID_MESSAGE, "timestamp": "not-a-valid-iso-date"}
        response = client.post("/messages", json=data)
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any(err["loc"][-1] == "timestamp" for err in errors)

    def test_missing_auth_token(self):
        """Omitting auth_token fails schema validation with 422."""
        data = {k: v for k, v in VALID_MESSAGE.items() if k != "auth_token"}
        response = client.post("/messages", json=data)
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any(err["loc"][-1] == "auth_token" for err in errors)

    def test_known_receiver(self):
        """All known registered agents are accepted by the receiver check."""
        known_agents = [
            "passenger-agent",
            "booking-agent",
            "security-agent",
            "operations-agent",
            "maintenance-agent",
        ]
        for agent in known_agents:
            data = {**VALID_MESSAGE, "receiver_agent": agent}
            response = client.post("/messages", json=data)
            assert response.status_code == 200
            body = response.json()
            assert body["receiver_agent"] == agent
            assert body["status"] in ("validated", "routed")

    def test_unknown_receiver(self):
        """An unknown receiver fails receiver validation with 404."""
        data = {**VALID_MESSAGE, "receiver_agent": "random-agent"}
        response = client.post("/messages", json=data)
        assert response.status_code == 404
        body = response.json()
        assert "detail" in body
        assert "random-agent" in body["detail"]
        assert "not registered" in body["detail"]

    def test_payload_wrong_outer_type(self):
        """Payload provided as string instead of dict fails with 422."""
        data = {**VALID_MESSAGE, "payload": "not-a-dict"}
        response = client.post("/messages", json=data)
        assert response.status_code == 422
