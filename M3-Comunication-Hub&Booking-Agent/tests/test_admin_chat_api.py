"""
tests/test_admin_chat_api.py
----------------------------
End-to-End API test suite for the Admin Booking Intelligence Assistant endpoints:
- POST /api/admin/booking-chat on Booking Agent
- POST /api/admin/booking-chat on Frontend Gateway (serve.py)
- Response schema compliance: answer, intent, entities, sources, card, is_fallback
- Handling across all 4 key administrative booking domains
"""

import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

_TESTS_DIR = Path(__file__).resolve().parent
_M3_ROOT = _TESTS_DIR.parent
_BOOKING_AGENT_DIR = _M3_ROOT / "booking-agent"
_FRONTEND_DIR = _M3_ROOT.parent / "frontend"

for p in (str(_M3_ROOT), str(_BOOKING_AGENT_DIR), str(_FRONTEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Load booking agent app
from main import app as booking_app
booking_client = TestClient(booking_app)

# Load serve.py app
import importlib.util
spec_serve = importlib.util.spec_from_file_location("frontend_serve_chat", str(_FRONTEND_DIR / "serve.py"))
serve_mod = importlib.util.module_from_spec(spec_serve)
spec_serve.loader.exec_module(serve_mod)
serve_app = serve_mod.app
serve_client = TestClient(serve_app)


class TestAdminChatAPI:

    def test_booking_agent_seat_query_api(self):
        """1. Seat availability query on Booking Agent endpoint."""
        resp = booking_client.post("/api/admin/booking-chat", json={
            "message": "How many seats are available on Udarata Menike tomorrow?"
        })
        assert resp.status_code == 200
        data = resp.json()

        assert "answer" in data
        assert data["intent"] == "seat_availability_query"
        assert "entities" in data
        assert data["entities"].get("train_name") == "Udarata Menike"
        assert isinstance(data["sources"], list)
        assert len(data["sources"]) > 0
        assert data["is_fallback"] is True  # In offline test mode

    def test_booking_agent_fraud_query_api(self):
        """2. Fraud review query on Booking Agent endpoint."""
        resp = booking_client.post("/api/admin/booking-chat", json={
            "message": "How many suspicious bookings are waiting for fraud review?"
        })
        assert resp.status_code == 200
        data = resp.json()

        assert "answer" in data
        assert data["intent"] == "fraud_review_query"
        assert "waiting for fraud review" in data["answer"].lower()

    def test_booking_agent_cancellation_query_api(self):
        """3. Cancellation query on Booking Agent endpoint."""
        resp = booking_client.post("/api/admin/booking-chat", json={
            "message": "How many cancellation requests are pending?"
        })
        assert resp.status_code == 200
        data = resp.json()

        assert "answer" in data
        assert data["intent"] == "cancellation_query"
        assert "cancellation requests" in data["answer"].lower()

    def test_booking_agent_manifest_query_api(self):
        """4. Manifest query on Booking Agent endpoint."""
        resp = booking_client.post("/api/admin/booking-chat", json={
            "message": "Show passengers booked on Udarata Menike tomorrow."
        })
        assert resp.status_code == 200
        data = resp.json()

        assert "answer" in data
        assert data["intent"] == "booking_manifest_query"

    def test_booking_agent_mutation_refusal_api(self):
        """5. Read-only guard on Booking Agent endpoint."""
        resp = booking_client.post("/api/admin/booking-chat", json={
            "message": "Approve booking RS-10023."
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "unsupported_mutation"
        assert "read-only" in data["answer"].lower()

    def test_frontend_proxy_chat_api(self):
        """6. Frontend gateway proxy route /api/admin/booking-chat."""
        resp = serve_client.post("/api/admin/booking-chat", json={
            "message": "Give me today's booking summary."
        })
        assert resp.status_code == 200
        data = resp.json()

        assert "answer" in data
        assert data["intent"] == "booking_statistics"
        assert "Daily Booking Summary" in data["answer"] or "summary" in data["answer"].lower()

    def test_empty_message_validation_error(self):
        """7. Empty message returns HTTP 422 validation error."""
        resp = booking_client.post("/api/admin/booking-chat", json={"message": ""})
        assert resp.status_code == 422
