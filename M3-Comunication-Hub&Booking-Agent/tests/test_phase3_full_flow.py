"""
tests/test_phase3_full_flow.py
------------------------------
End-to-End integration test suite for Phase 3:
Communication Hub -> Booking Agent -> BookingService -> Database

Verifies:
1. Valid JWT accepted and verified
2. Message routed from Hub to Booking Agent
3. Active train found
4. Trip schedule found
5. Dynamic seat availability checked
6. Deterministic fare calculated
7. Unique RS- booking reference generated
8. Booking record persisted in database with status CONFIRMED
9. BookingResult returned in structured envelope
10. Hub audit record updated to ROUTED

Negative / Error flow tests:
- Unknown train -> no booking persisted
- Wrong schedule route/date -> no booking persisted
- Insufficient seat capacity -> no booking persisted
- Invalid payload (same station, invalid count) -> no booking persisted
- Optional user_id handling -> safely recorded, default fallback when omitted
- Cancel booking intent -> returns clear not-implemented response
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

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
MEMBER_C = os.path.dirname(os.path.dirname(__file__))
AGENT_HUB = os.path.join(MEMBER_C, "agent-hub")
BOOKING_AGENT = os.path.join(MEMBER_C, "booking-agent")

for p in (MEMBER_C, AGENT_HUB, BOOKING_AGENT):
    if p not in sys.path:
        sys.path.insert(0, p)

from database.database import get_db as get_booking_db
from database.models import AuditLog, AuditStatus, Base, Booking, BookingStatus, Train, TrainSchedule
from database.seed import seed_test_train_data
from hub_database import get_db as get_hub_db
from router import get_http_client
from shared.schemas import AgentMessage

# Dynamically load apps
HUB_MAIN = os.path.join(AGENT_HUB, "main.py")
spec_hub = importlib.util.spec_from_file_location("hub_main_fullflow", HUB_MAIN)
hub_mod = importlib.util.module_from_spec(spec_hub)
sys.modules["hub_main_fullflow"] = hub_mod
spec_hub.loader.exec_module(hub_mod)
hub_app = hub_mod.app

BOOKING_MAIN = os.path.join(BOOKING_AGENT, "main.py")
spec_bk = importlib.util.spec_from_file_location("bk_main_fullflow", BOOKING_MAIN)
bk_mod = importlib.util.module_from_spec(spec_bk)
sys.modules["bk_main_fullflow"] = bk_mod
spec_bk.loader.exec_module(bk_mod)
booking_app = bk_mod.app

# ---------------------------------------------------------------------------
# Test In-Memory Database (shared between Hub and Booking Agent)
# ---------------------------------------------------------------------------
TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Create fresh database tables, seed test trains/schedules, and wire dependencies."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestingSessionLocal() as db:
        seed_test_train_data(db)

    def override_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    hub_app.dependency_overrides[get_hub_db] = override_db
    booking_app.dependency_overrides[get_booking_db] = override_db

    # Route Hub directly to booking_app in-memory via ASGITransport
    transport = httpx.ASGITransport(app=booking_app)

    async def override_http_client():
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8003") as ac:
            yield ac

    hub_app.dependency_overrides[get_http_client] = override_http_client

    yield

    Base.metadata.drop_all(bind=TEST_ENGINE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
TEST_SECRET = os.getenv("JWT_SECRET_KEY", "change-me")
TARGET_TRAVEL_DATE = "2026-12-03"


def create_agent_token(sender: str = "passenger-agent") -> str:
    """Create a valid JWT token signed with TEST_SECRET."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sender,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    return "Bearer " + jwt.encode(payload, TEST_SECRET, algorithm="HS256")


def build_message(
    intent: str = "booking_request",
    payload: dict | None = None,
    sender: str = "passenger-agent",
    receiver: str = "booking-agent",
    message_id: str = "MSG-TEST-001",
) -> dict:
    default_payload = {
        "from_station": "Colombo",
        "to_station": "Kandy",
        "travel_date": TARGET_TRAVEL_DATE,
        "train_id": "PM-4082",
        "seat_class": "Second Class",
        "passenger_count": 2,
    }
    return {
        "message_id": message_id,
        "sender_agent": sender,
        "receiver_agent": receiver,
        "intent": intent,
        "payload": payload if payload is not None else default_payload,
        "auth_token": create_agent_token(sender),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ===========================================================================
# Full Flow Tests
# ===========================================================================

class TestPhase3FullFlow:

    def test_hub_to_booking_agent_success(self):
        """
        Verify the complete successful flow:
        Hub validates JWT & sender -> routes message -> Booking Agent checks train,
        schedule & seats -> calculates fare -> generates RS- reference -> saves booking
        with CONFIRMED status -> returns BookingResult -> Hub audit status becomes ROUTED.
        """
        hub_client = TestClient(hub_app, raise_server_exceptions=False)
        msg = build_message(message_id="MSG-SUCCESS-101")

        response = hub_client.post("/messages", json=msg)
        assert response.status_code == 200

        data = response.json()
        assert data["message_id"] == "MSG-SUCCESS-101"
        assert data["status"] == "routed"
        assert data["receiver_agent"] == "booking-agent"

        # Check destination response
        booking_resp = data["response"]
        assert booking_resp["status"] == "booking_confirmed"
        assert "booking" in booking_resp
        b = booking_resp["booking"]

        # Check booking fields
        assert b["booking_reference"].startswith("RS-")
        assert len(b["booking_reference"]) == 8  # RS- followed by 5 digits
        assert b["train_id"] == "PM-4082"
        assert b["from_station"] == "Colombo"
        assert b["to_station"] == "Kandy"
        assert b["travel_date"] == TARGET_TRAVEL_DATE
        assert b["seat_class"] == "Second Class"
        assert b["passenger_count"] == 2
        # Colombo -> Kandy Second Class fare is 1200.00 * 2 = 2400.00
        assert b["fare"] == "2400.00"
        assert b["status"] == "CONFIRMED"

        # Verify record in database
        with TestingSessionLocal() as db:
            db_booking = db.query(Booking).filter_by(booking_reference=b["booking_reference"]).first()
            assert db_booking is not None
            assert db_booking.status == BookingStatus.CONFIRMED
            assert db_booking.fare == Decimal("2400.00")
            assert db_booking.passenger_count == 2
            assert db_booking.user_id == "guest_passenger"

            # Verify Hub audit trail
            audit = db.query(AuditLog).filter_by(message_id="MSG-SUCCESS-101").first()
            assert audit is not None
            assert audit.status == AuditStatus.ROUTED
            assert audit.error_message is None

    def test_unknown_train_no_booking(self):
        """Unknown train rejects booking and creates zero booking records."""
        hub_client = TestClient(hub_app, raise_server_exceptions=False)
        payload = {
            "from_station": "Colombo",
            "to_station": "Kandy",
            "travel_date": TARGET_TRAVEL_DATE,
            "train_id": "UNKNOWN-9999",
            "seat_class": "Second Class",
            "passenger_count": 1,
        }
        msg = build_message(payload=payload, message_id="MSG-UNKNOWN-TRAIN")

        response = hub_client.post("/messages", json=msg)
        assert response.status_code == 502  # Hub maps 404 from downstream to 502

        with TestingSessionLocal() as db:
            booking_count = db.query(Booking).count()
            assert booking_count == 0

            # Hub audit log should record FAILED
            audit = db.query(AuditLog).filter_by(message_id="MSG-UNKNOWN-TRAIN").first()
            assert audit is not None
            assert audit.status == AuditStatus.FAILED

    def test_wrong_schedule_no_booking(self):
        """Non-existent route on travel date rejects booking and saves nothing."""
        hub_client = TestClient(hub_app, raise_server_exceptions=False)
        payload = {
            "from_station": "Colombo",
            "to_station": "Galle",  # PM-4082 only operates Colombo -> Kandy in seed
            "travel_date": TARGET_TRAVEL_DATE,
            "train_id": "PM-4082",
            "seat_class": "Second Class",
            "passenger_count": 1,
        }
        msg = build_message(payload=payload, message_id="MSG-WRONG-SCHEDULE")

        response = hub_client.post("/messages", json=msg)
        assert response.status_code == 502

        with TestingSessionLocal() as db:
            booking_count = db.query(Booking).count()
            assert booking_count == 0

    def test_insufficient_seats_no_booking(self):
        """When requested seats exceed available capacity, reject and do not persist."""
        hub_client = TestClient(hub_app, raise_server_exceptions=False)

        # Capacity for First Class on PM-4082 is 40 seats.
        # Seed bookings to consume 38 seats.
        with TestingSessionLocal() as db:
            sched = db.query(TrainSchedule).filter_by(travel_date=date(2026, 12, 3)).first()
            existing_booking = Booking(
                booking_reference="RS-EXISTING",
                user_id="seed_user",
                train_id=sched.train_id,
                schedule_id=sched.id,
                from_station="Colombo",
                to_station="Kandy",
                travel_date=sched.travel_date,
                seat_class="First Class",
                passenger_count=38,
                fare=Decimal("95000.00"),
                status=BookingStatus.CONFIRMED,
            )
            db.add(existing_booking)
            db.commit()

        # Request 5 seats when only 2 remain (40 - 38 = 2)
        payload = {
            "from_station": "Colombo",
            "to_station": "Kandy",
            "travel_date": TARGET_TRAVEL_DATE,
            "train_id": "PM-4082",
            "seat_class": "First Class",
            "passenger_count": 5,
        }
        msg = build_message(payload=payload, message_id="MSG-OVERBOOK")

        response = hub_client.post("/messages", json=msg)
        assert response.status_code == 502  # Booking agent returned 409 -> Hub maps to 502

        with TestingSessionLocal() as db:
            # Only the pre-existing booking should exist
            total_bookings = db.query(Booking).count()
            assert total_bookings == 1
            assert db.query(Booking).filter_by(booking_reference="RS-EXISTING").first() is not None

    def test_invalid_payload_no_booking(self):
        """Invalid payload (e.g. same departure and arrival station) rejects immediately."""
        hub_client = TestClient(hub_app, raise_server_exceptions=False)
        payload = {
            "from_station": "Colombo",
            "to_station": "Colombo",  # Identical stations
            "travel_date": TARGET_TRAVEL_DATE,
            "train_id": "PM-4082",
            "seat_class": "Second Class",
            "passenger_count": 1,
        }
        msg = build_message(payload=payload, message_id="MSG-INVALID-STATIONS")

        response = hub_client.post("/messages", json=msg)
        assert response.status_code == 502  # Downstream 422 mapped to 502

        with TestingSessionLocal() as db:
            assert db.query(Booking).count() == 0

    def test_user_id_propagation_when_provided(self):
        """When passenger agent passes user_id in payload, it is stored in database."""
        hub_client = TestClient(hub_app, raise_server_exceptions=False)
        payload = {
            "from_station": "Colombo",
            "to_station": "Kandy",
            "travel_date": TARGET_TRAVEL_DATE,
            "train_id": "PM-4082",
            "seat_class": "First Class",
            "passenger_count": 1,
            "user_id": "passenger_authenticated_987",
        }
        msg = build_message(payload=payload, message_id="MSG-USER-ID")

        response = hub_client.post("/messages", json=msg)
        assert response.status_code == 200
        ref = response.json()["response"]["booking"]["booking_reference"]

        with TestingSessionLocal() as db:
            b = db.query(Booking).filter_by(booking_reference=ref).first()
            assert b is not None
            assert b.user_id == "passenger_authenticated_987"
            assert b.fare == Decimal("2500.00")

    def test_cancel_booking_not_implemented(self):
        """cancel_booking returns not-implemented response and does not error."""
        hub_client = TestClient(hub_app, raise_server_exceptions=False)
        msg = build_message(
            intent="cancel_booking",
            payload={"booking_reference": "RS-84521", "reason": "Accidental booking"},
            message_id="MSG-CANCEL-001",
        )

        response = hub_client.post("/messages", json=msg)
        # Booking agent returns 501 for cancel_booking, so Hub maps 5xx to 502
        assert response.status_code == 502
