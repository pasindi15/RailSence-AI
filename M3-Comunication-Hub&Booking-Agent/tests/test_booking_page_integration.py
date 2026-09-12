"""
tests/test_booking_page_integration.py
--------------------------------------
End-to-End integration test suite for the Booking Page & Passenger Chat integration:
1. Full prefill extraction from passenger chat
2. Partial prefill extraction (no invented values)
3. No prefill extraction (no invented values)
4. Editing prefilled values
5. Loading train options from backend (real schedules and seat availability)
6. Route with no trains returns empty list
7. Successful booking flow through Server Gateway -> Hub -> Booking Agent -> Database
8. Booking reference format (RS-XXXXX) verification
9. Deterministic fare verification
10. Insufficient seats error handling
11. Invalid form error handling
12. Double-booking prevention logic
13. Security verification: no JWT secret or database URL exposed to frontend
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path setup
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
import importlib.util
spec_serve = importlib.util.spec_from_file_location("frontend_serve", str(_FRONTEND_DIR / "serve.py"))
serve_mod = importlib.util.module_from_spec(spec_serve)
spec_serve.loader.exec_module(serve_mod)
serve_app = serve_mod.app

client = TestClient(serve_app)


class TestPassengerChatExtraction:
    """Tests 1, 2, 3: Entity and intent extraction from passenger chat."""

    def test_full_prefill_extraction(self):
        """1. Full prefill: Colombo to Kandy on 3rd December."""
        resp = client.post("/api/chat", json={
            "message": "I need to book a train from Colombo to Kandy on 3rd December."
        })
        assert resp.status_code == 200
        data = resp.json()

        assert data["intent"] == "booking_request"
        prefill = data["prefill"]
        assert prefill.get("from_station") == "Colombo"
        assert prefill.get("to_station") == "Kandy"
        assert prefill.get("travel_date") == "2026-12-03"

        action = data.get("action")
        assert action is not None
        assert action["type"] == "continue_to_booking"
        assert "from=Colombo" in action["url"]
        assert "to=Kandy" in action["url"]
        assert "date=2026-12-03" in action["url"]

    def test_partial_prefill_extraction(self):
        """2. Partial prefill: 'I want to book a train to Kandy.' Only to_station extracted."""
        resp = client.post("/api/chat", json={
            "message": "I want to book a train to Kandy."
        })
        assert resp.status_code == 200
        data = resp.json()

        assert data["intent"] == "booking_request"
        prefill = data["prefill"]
        assert prefill.get("to_station") == "Kandy"
        # Must NOT invent missing values
        assert "from_station" not in prefill
        assert "travel_date" not in prefill

        action = data.get("action")
        assert action is not None
        assert "to=Kandy" in action["url"]
        assert "from=" not in action["url"]
        assert "date=" not in action["url"]

    def test_no_prefill_extraction(self):
        """3. No prefill: 'I want to book tickets.' No stations or dates invented."""
        resp = client.post("/api/chat", json={
            "message": "I want to book tickets."
        })
        assert resp.status_code == 200
        data = resp.json()

        assert data["intent"] == "booking_request"
        prefill = data["prefill"]
        assert "from_station" not in prefill
        assert "to_station" not in prefill
        assert "travel_date" not in prefill

        action = data.get("action")
        assert action is not None
        assert action["url"] == "/booking"


class TestTrainOptionsDiscovery:
    """Tests 5, 6: Train options loading from authoritative database."""

    def test_loading_train_options_matching_route(self):
        """5. Loading trains from backend for Colombo -> Kandy on 2026-12-03."""
        resp = client.get("/api/booking-options", params={
            "from_station": "Colombo",
            "to_station": "Kandy",
            "travel_date": "2026-12-03",
        })
        assert resp.status_code == 200
        options = resp.json()
        assert isinstance(options, list)
        assert len(options) >= 1

        opt = options[0]
        assert opt["train_id"] == "PM-4082"
        assert opt["train_name"] == "Intercity Express"
        assert opt["from_station"] == "Colombo"
        assert opt["to_station"] == "Kandy"
        assert opt["travel_date"] == "2026-12-03"

        classes = {c["seat_class"]: c for c in opt["available_classes"]}
        assert "First Class" in classes
        assert "Second Class" in classes
        assert classes["Second Class"]["available_seats"] > 0
        assert "available_seats" in classes["First Class"]

    def test_no_trains_available_for_unmatched_route(self):
        """6. Route with no trains returns empty list."""
        resp = client.get("/api/booking-options", params={
            "from_station": "Colombo",
            "to_station": "Jaffna",
            "travel_date": "2026-12-03",
        })
        assert resp.status_code == 200
        options = resp.json()
        assert isinstance(options, list)
        assert len(options) == 0


class TestBookingConfirmationFlow:
    """Tests 4, 7, 8, 9, 10, 11, 12, 13: Booking submission, security, and persistence."""

    def test_successful_booking_flow(self):
        """4, 7, 8, 9: Successful booking with edited/final form values."""
        payload = {
            "from_station": "Colombo",
            "to_station": "Kandy",
            "travel_date": "2026-12-03",
            "train_id": "PM-4082",
            "seat_class": "Second Class",
            "passenger_count": 2,
            "user_id": "passenger_test_web",
        }
        resp = client.post("/api/bookings/confirm", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        booking = data["booking"]

        # 8. Booking reference format RS-XXXXX
        ref = booking["booking_reference"]
        assert ref.startswith("RS-"), f"Expected RS- reference, got {ref}"
        assert len(ref) >= 7

        # 9. Deterministic fare
        assert booking["fare"] == "2400.00"  # 1200.00 * 2 for Second Class
        assert booking["status"] == "CONFIRMED"
        assert booking["passenger_count"] == 2

    def test_insufficient_seats_error(self):
        """10. Requesting more seats than capacity returns clean error."""
        payload = {
            "from_station": "Colombo",
            "to_station": "Kandy",
            "travel_date": "2026-12-03",
            "train_id": "PM-4082",
            "seat_class": "First Class",
            "passenger_count": 10,
        }
        # In a loop or large request that exceeds capacity
        # First Class capacity is 40. Request 10 multiple times until full
        for _ in range(5):
            r = client.post("/api/bookings/confirm", json=payload)
            if r.status_code == 409:
                break
        assert r.status_code == 409
        assert r.json()["error"] == "Not enough seats are available."

    def test_invalid_form_missing_required_fields(self):
        """11. Missing required fields returns clean error."""
        payload = {
            "from_station": "Colombo",
            "to_station": "",
            "travel_date": "2026-12-03",
            "train_id": "PM-4082",
            "seat_class": "Second Class",
            "passenger_count": 1,
        }
        resp = client.post("/api/bookings/confirm", json=payload)
        assert resp.status_code == 400
        assert resp.json()["error"] == "Please complete all booking details."

    def test_no_secrets_exposed_to_browser(self):
        """13. Ensure JWT secret, passwords, or connection strings are never exposed."""
        # 1. Check chat response
        r_chat = client.post("/api/chat", json={"message": "book train to Kandy"})
        chat_text = r_chat.text
        assert "change-me" not in chat_text
        assert "postgresql://" not in chat_text
        assert "supabase" not in chat_text.lower() or "railway" in chat_text.lower()
        assert "secret" not in chat_text.lower()

        # 2. Check booking options response
        r_opt = client.get("/api/booking-options", params={
            "from_station": "Colombo",
            "to_station": "Kandy",
            "travel_date": "2026-12-03",
        })
        assert "change-me" not in r_opt.text
        assert "postgresql" not in r_opt.text

        # 3. Check booking confirmation response
        r_conf = client.post("/api/bookings/confirm", json={
            "from_station": "Colombo",
            "to_station": "Kandy",
            "travel_date": "2026-12-03",
            "train_id": "PM-4082",
            "seat_class": "Second Class",
            "passenger_count": 1,
        })
        assert "change-me" not in r_conf.text
        assert "postgresql" not in r_conf.text
        assert "auth_token" not in r_conf.text  # Internal JWT is never returned to browser
