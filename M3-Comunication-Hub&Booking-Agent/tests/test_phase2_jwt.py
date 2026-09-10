"""
tests/test_phase2_jwt.py
------------------------
RailSense AI — Member C Phase 2 JWT Authentication Tests.

Covers:
  - test_valid_jwt
  - test_invalid_jwt
  - test_expired_jwt
  - test_missing_token
  - test_sender_claim_mismatch
  - test_valid_authenticated_message
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timezone, timedelta, date

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
MEMBER_C = os.path.dirname(os.path.dirname(__file__))   # member-c/
AGENT_HUB = os.path.join(MEMBER_C, "agent-hub")

for p in (MEMBER_C, AGENT_HUB):
    if p not in sys.path:
        sys.path.insert(0, p)

from auth.jwt_utils import verify_agent_token, get_jwt_secret, get_jwt_algorithm

# Dynamically load agent-hub/main.py
HUB_MAIN = os.path.join(AGENT_HUB, "main.py")
spec = importlib.util.spec_from_file_location("hub_main_jwt", HUB_MAIN)
hub_mod = importlib.util.module_from_spec(spec)
sys.modules["hub_main_jwt"] = hub_mod
spec.loader.exec_module(hub_mod)
hub_app = hub_mod.app

client = TestClient(hub_app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Test Helpers (strictly within test suite — not exposed to production)
# ---------------------------------------------------------------------------
TEST_SECRET = get_jwt_secret()
TEST_ALGO = get_jwt_algorithm()


def create_test_token(
    sub: str = "passenger-agent",
    secret: str = TEST_SECRET,
    algorithm: str = TEST_ALGO,
    expires_in_seconds: int = 3600,
) -> str:
    """Generate a signed test JWT for unit and integration testing."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()
NOW_ISO = datetime.now(timezone.utc).isoformat()


def make_valid_message(token: str | None = None, sender: str = "passenger-agent") -> dict:
    """Helper to produce a valid AgentMessage payload."""
    if token is None:
        token = create_test_token(sub=sender)
    return {
        "message_id": "MSG-2001",
        "sender_agent": sender,
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
        "auth_token": token,
        "timestamp": NOW_ISO,
    }


# ===========================================================================
# Unit & Integration Tests for JWT Authentication
# ===========================================================================

class TestJwtAuthentication:
    """Test suite for Phase 2 JWT verification in the Communication Hub."""

    def test_valid_jwt(self):
        """A valid, signed, non-expired JWT decodes successfully."""
        token = create_test_token(sub="passenger-agent", expires_in_seconds=600)
        claims = verify_agent_token(token, expected_sender="passenger-agent")
        assert claims["sub"] == "passenger-agent"
        assert "exp" in claims

    def test_valid_jwt_with_bearer_prefix(self):
        """Tokens with 'Bearer ' prefix are accepted and cleanly stripped."""
        token = "Bearer " + create_test_token(sub="passenger-agent", expires_in_seconds=600)
        claims = verify_agent_token(token, expected_sender="passenger-agent")
        assert claims["sub"] == "passenger-agent"

    def test_invalid_jwt(self):
        """Tokens with an invalid signature or malformed body raise HTTP 401."""
        # 1. Invalid signature (signed with different secret)
        wrong_token = create_test_token(secret="wrong-secret-key-12345")
        with pytest.raises(HTTPException) as exc_info:
            verify_agent_token(wrong_token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or expired authentication token"

        # 2. Corrupted string
        with pytest.raises(HTTPException) as exc_info:
            verify_agent_token("not.a.valid.jwt.token")
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or expired authentication token"

    def test_expired_jwt(self):
        """Expired JWTs raise HTTP 401."""
        expired_token = create_test_token(sub="passenger-agent", expires_in_seconds=-60)
        with pytest.raises(HTTPException) as exc_info:
            verify_agent_token(expired_token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or expired authentication token"

    def test_missing_token(self):
        """Empty or whitespace token strings raise HTTP 401."""
        for bad_token in ("", "   ", "Bearer "):
            with pytest.raises(HTTPException) as exc_info:
                verify_agent_token(bad_token)
            assert exc_info.value.status_code == 401
            assert exc_info.value.detail == "Invalid or expired authentication token"

    def test_sender_claim_mismatch(self):
        """Token with subject claim different from sender_agent raises HTTP 401."""
        # Token issued for 'security-agent', but message says 'passenger-agent'
        token = create_test_token(sub="security-agent")
        with pytest.raises(HTTPException) as exc_info:
            verify_agent_token(token, expected_sender="passenger-agent")
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Token subject does not match sender agent"

    def test_valid_authenticated_message(self):
        """Hub POST /messages succeeds (200) with a valid signed token."""
        msg = make_valid_message()
        response = client.post("/messages", json=msg)
        assert response.status_code == 200
        body = response.json()
        assert body["message_id"] == "MSG-2001"
        assert body["status"] in ("validated", "routed")
        assert body["receiver_agent"] == "booking-agent"

    def test_hub_rejects_unauthenticated_message(self):
        """Hub POST /messages returns 401 if auth_token is invalid."""
        msg = make_valid_message(token="invalid.bogus.token")
        response = client.post("/messages", json=msg)
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid or expired authentication token"

    def test_hub_rejects_expired_message(self):
        """Hub POST /messages returns 401 if auth_token is expired."""
        expired_token = create_test_token(expires_in_seconds=-10)
        msg = make_valid_message(token=expired_token)
        response = client.post("/messages", json=msg)
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid or expired authentication token"

    def test_hub_rejects_sender_mismatch(self):
        """Hub POST /messages returns 401 if token sub claim does not match sender_agent."""
        spoofed_token = create_test_token(sub="attacker-agent")
        msg = make_valid_message(token=spoofed_token, sender="passenger-agent")
        response = client.post("/messages", json=msg)
        assert response.status_code == 401
        assert response.json()["detail"] == "Token subject does not match sender agent"
