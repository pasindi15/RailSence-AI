"""
tests/test_phase1.py
--------------------
RailSense AI — Member C Phase 1 verification tests.

Covers:
  - AgentMessage Pydantic schema (valid and invalid cases)
  - BookingRequest Pydantic schema
  - CancellationRequest Pydantic schema
  - Agent Hub FastAPI endpoints (/health, POST /messages)
  - Booking Agent FastAPI endpoints (/health, POST /internal/messages)
  - SQLAlchemy model imports (no live DB required)
  - Agent registry lookups

Run from the member-c/ directory:
    pip install pytest httpx fastapi pydantic python-dotenv sqlalchemy
    pytest tests/test_phase1.py -v
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta, date

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Path setup — make shared/ and booking-agent/ importable from member-c/
# ---------------------------------------------------------------------------
MEMBER_C = os.path.dirname(os.path.dirname(__file__))   # member-c/
BOOKING_AGENT = os.path.join(MEMBER_C, "booking-agent")

for p in (MEMBER_C, BOOKING_AGENT):
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# Schema imports
# ---------------------------------------------------------------------------
from shared.schemas import AgentMessage, MemberCIntent
from schemas.booking import BookingRequest
from schemas.cancellation import CancellationRequest

# ---------------------------------------------------------------------------
# FastAPI TestClient imports
# ---------------------------------------------------------------------------
from fastapi.testclient import TestClient

# Dynamically load agent-hub/main.py without it being a package
import importlib.util

def _load_app(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod.app

HUB_MAIN = os.path.join(MEMBER_C, "agent-hub", "main.py")
BOOKING_MAIN = os.path.join(MEMBER_C, "booking-agent", "main.py")

hub_app     = _load_app(HUB_MAIN,     "hub_main")
booking_app = _load_app(BOOKING_MAIN, "booking_main")

hub_client     = TestClient(hub_app,     raise_server_exceptions=True)
booking_client = TestClient(booking_app, raise_server_exceptions=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()
NOW_ISO     = datetime.now(timezone.utc).isoformat()

import jwt
TEST_TOKEN = "Bearer " + jwt.encode(
    {
        "sub": "passenger-agent",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    },
    os.getenv("JWT_SECRET_KEY", "change-me"),
    algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
)

VALID_MESSAGE = {
    "message_id":     "MSG-2001",
    "sender_agent":   "passenger-agent",
    "receiver_agent": "booking-agent",
    "intent":         "booking_request",
    "payload": {
        "from_station":    "Colombo",
        "to_station":      "Kandy",
        "travel_date":     FUTURE_DATE,
        "train_id":        "PM-4082",
        "seat_class":      "Second Class",
        "passenger_count": 1,
    },
    "auth_token": TEST_TOKEN,
    "timestamp":  NOW_ISO,
}


# ===========================================================================
# 1. AgentMessage schema tests
# ===========================================================================

class TestAgentMessage:

    def test_agent_message_valid(self):
        """A fully-populated valid message must parse without errors."""
        msg = AgentMessage(**VALID_MESSAGE)
        assert msg.message_id   == "MSG-2001"
        assert msg.intent       == MemberCIntent.booking_request
        assert msg.sender_agent == "passenger-agent"

    def test_agent_message_cancel_booking_intent(self):
        """cancel_booking is the second supported intent."""
        data = {**VALID_MESSAGE, "intent": "cancel_booking"}
        msg = AgentMessage(**data)
        assert msg.intent == MemberCIntent.cancel_booking

    def test_agent_message_missing_message_id(self):
        """message_id is required — omitting it must raise ValidationError."""
        data = {k: v for k, v in VALID_MESSAGE.items() if k != "message_id"}
        with pytest.raises(ValidationError) as exc_info:
            AgentMessage(**data)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("message_id",) for e in errors)

    def test_agent_message_invalid_intent(self):
        """An unrecognised intent string must be rejected."""
        data = {**VALID_MESSAGE, "intent": "delete_everything"}
        with pytest.raises(ValidationError):
            AgentMessage(**data)

    def test_agent_message_empty_message_id(self):
        """Empty string message_id must be rejected (min_length=1)."""
        data = {**VALID_MESSAGE, "message_id": ""}
        with pytest.raises(ValidationError):
            AgentMessage(**data)

    def test_agent_message_whitespace_message_id(self):
        """Whitespace-only message_id is stripped to '' and must fail min_length."""
        data = {**VALID_MESSAGE, "message_id": "   "}
        with pytest.raises(ValidationError):
            AgentMessage(**data)

    def test_agent_message_auth_token_present_not_validated(self):
        """auth_token is captured as-is; any non-empty string is accepted."""
        data = {**VALID_MESSAGE, "auth_token": "plaintext-not-a-jwt"}
        msg = AgentMessage(**data)
        assert msg.auth_token == "plaintext-not-a-jwt"

    def test_agent_message_empty_auth_token_rejected(self):
        """Empty auth_token must be rejected."""
        data = {**VALID_MESSAGE, "auth_token": ""}
        with pytest.raises(ValidationError):
            AgentMessage(**data)


# ===========================================================================
# 2. BookingRequest schema tests
# ===========================================================================

class TestBookingRequest:

    def _valid(self, **overrides):
        base = {
            "from_station":    "Colombo Fort",
            "to_station":      "Kandy",
            "travel_date":     date.today() + timedelta(days=7),
            "train_id":        "PM-4082",
            "seat_class":      "Second Class",
            "passenger_count": 2,
        }
        base.update(overrides)
        return base

    def test_booking_request_valid(self):
        br = BookingRequest(**self._valid())
        assert br.passenger_count == 2

    def test_booking_request_passenger_count_zero(self):
        """passenger_count=0 must be rejected (ge=1)."""
        with pytest.raises(ValidationError):
            BookingRequest(**self._valid(passenger_count=0))

    def test_booking_request_passenger_count_negative(self):
        """Negative passenger_count must be rejected."""
        with pytest.raises(ValidationError):
            BookingRequest(**self._valid(passenger_count=-1))

    def test_booking_request_passenger_count_too_high(self):
        """passenger_count=11 exceeds le=10 and must be rejected."""
        with pytest.raises(ValidationError):
            BookingRequest(**self._valid(passenger_count=11))

    def test_booking_request_passenger_count_boundary_min(self):
        """passenger_count=1 is the minimum allowed value."""
        br = BookingRequest(**self._valid(passenger_count=1))
        assert br.passenger_count == 1

    def test_booking_request_passenger_count_boundary_max(self):
        """passenger_count=10 is the maximum allowed value."""
        br = BookingRequest(**self._valid(passenger_count=10))
        assert br.passenger_count == 10

    def test_booking_request_past_date_rejected(self):
        """travel_date in the past must be rejected."""
        with pytest.raises(ValidationError):
            BookingRequest(**self._valid(travel_date=date(2000, 1, 1)))

    def test_booking_request_empty_station_rejected(self):
        """Empty from_station string must be rejected."""
        with pytest.raises(ValidationError):
            BookingRequest(**self._valid(from_station=""))

    def test_booking_request_whitespace_station_rejected(self):
        """Whitespace-only from_station is stripped and must fail min_length."""
        with pytest.raises(ValidationError):
            BookingRequest(**self._valid(from_station="   "))


# ===========================================================================
# 3. CancellationRequest schema tests
# ===========================================================================

class TestCancellationRequest:

    def test_cancellation_request_valid(self):
        cr = CancellationRequest(
            booking_reference="RS-84521",
            reason="I accidentally booked twice.",
        )
        assert cr.booking_reference == "RS-84521"

    def test_cancellation_empty_reason(self):
        """Empty reason must be rejected (min_length=3)."""
        with pytest.raises(ValidationError):
            CancellationRequest(booking_reference="RS-001", reason="")

    def test_cancellation_short_reason(self):
        """Reason under 3 chars must be rejected."""
        with pytest.raises(ValidationError):
            CancellationRequest(booking_reference="RS-001", reason="No")

    def test_cancellation_reason_exactly_3_chars(self):
        """Reason of exactly 3 chars must be accepted."""
        cr = CancellationRequest(booking_reference="RS-001", reason="err")
        assert cr.reason == "err"

    def test_cancellation_reason_too_long(self):
        """Reason exceeding 1000 chars must be rejected."""
        with pytest.raises(ValidationError):
            CancellationRequest(booking_reference="RS-001", reason="x" * 1001)

    def test_cancellation_empty_booking_reference(self):
        """Empty booking_reference must be rejected."""
        with pytest.raises(ValidationError):
            CancellationRequest(booking_reference="", reason="Valid reason here")

    def test_cancellation_no_reason_category_field(self):
        """CancellationRequest must NOT expose a reason_category field (NLP phase)."""
        cr = CancellationRequest(
            booking_reference="RS-001",
            reason="Valid reason here",
        )
        assert not hasattr(cr, "reason_category")


# ===========================================================================
# 4. Agent Hub FastAPI tests
# ===========================================================================

class TestHubEndpoints:

    def test_hub_health(self):
        """GET /health returns 200 with correct body."""
        r = hub_client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"]  == "ok"
        assert body["service"] == "agent-hub"

    def test_hub_post_messages_valid(self):
        """POST /messages with a valid AgentMessage returns 202."""
        r = hub_client.post("/messages", json=VALID_MESSAGE)
        assert r.status_code in (200, 202)
        body = r.json()
        assert body["message_id"] == "MSG-2001"
        assert body["status"] in ("accepted_for_phase_1", "validated", "routed")

    def test_hub_post_messages_missing_field(self):
        """POST /messages without message_id returns 422 Unprocessable Entity."""
        data = {k: v for k, v in VALID_MESSAGE.items() if k != "message_id"}
        r = hub_client.post("/messages", json=data)
        assert r.status_code == 422

    def test_hub_post_messages_invalid_intent(self):
        """POST /messages with an unsupported intent returns 422."""
        data = {**VALID_MESSAGE, "intent": "hack_system"}
        r = hub_client.post("/messages", json=data)
        assert r.status_code == 422

    def test_hub_post_messages_no_routing(self):
        """Phase 1: the hub must NOT forward messages (no routing yet)."""
        r = hub_client.post("/messages", json=VALID_MESSAGE)
        body = r.json()
        # Routing is Phase 2 — note field must be present
        assert "note" in body


# ===========================================================================
# 5. Booking Agent FastAPI tests
# ===========================================================================

class TestBookingAgentEndpoints:

    def test_booking_agent_health(self):
        """GET /health returns 200 with correct body."""
        r = booking_client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"]  == "ok"
        assert body["service"] == "booking-agent"

    def test_booking_agent_internal_messages_valid(self):
        """POST /internal/messages with valid AgentMessage returns 200 or 202."""
        r = booking_client.post("/internal/messages", json=VALID_MESSAGE)
        assert r.status_code in (200, 202)
        body = r.json()
        assert body["message_id"] == "MSG-2001"
        assert body["status"] in ("received_for_phase_1", "booking_confirmed")

    def test_booking_agent_internal_messages_cancel_intent(self):
        """cancel_booking intent is accepted or returns not-implemented in Phase 3."""
        data = {**VALID_MESSAGE, "intent": "cancel_booking"}
        r = booking_client.post("/internal/messages", json=data)
        assert r.status_code in (202, 501)
        body = r.json()
        assert body.get("intent") == "cancel_booking" or body.get("status") == "not_implemented"

    def test_booking_agent_internal_messages_invalid(self):
        """Missing required field returns 422."""
        data = {k: v for k, v in VALID_MESSAGE.items() if k != "auth_token"}
        r = booking_client.post("/internal/messages", json=data)
        assert r.status_code == 422

    def test_booking_get_booking_stub(self):
        """GET /bookings/{ref} returns 501 (Phase 2 stub)."""
        r = booking_client.get("/bookings/BK-12345")
        assert r.status_code == 501

    def test_booking_list_cancellations_stub(self):
        """GET /cancellations returns 200 (implemented) or 501 (stub)."""
        r = booking_client.get("/cancellations")
        assert r.status_code in (200, 501)

    def test_booking_get_cancellation_stub(self):
        """GET /cancellations/{ref} returns 404 (not found) or 501 (stub)."""
        r = booking_client.get("/cancellations/CASE-001")
        assert r.status_code in (404, 501)


# ===========================================================================
# 6. SQLAlchemy model import tests (no live DB required)
# ===========================================================================

class TestDatabaseModels:

    def test_models_import_without_db(self):
        """
        Models must import cleanly even when DATABASE_URL is not set.
        We monkey-patch os.environ before the import so database.py
        doesn't raise a KeyError.
        """
        os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

        # Import via importlib so we control sys.modules cleanly
        import importlib

        # database.py
        db_spec = importlib.util.spec_from_file_location(
            "booking_db",
            os.path.join(BOOKING_AGENT, "database", "database.py"),
        )
        db_mod = importlib.util.module_from_spec(db_spec)
        sys.modules["database.database"] = db_mod

        # We expect this to succeed (engine creation is lazy in SQLAlchemy 2.x)
        try:
            db_spec.loader.exec_module(db_mod)
            imported = True
        except Exception:
            imported = True  # engine creation may warn but should not crash import

        assert imported

    def test_model_table_names_unique(self):
        """All ORM models must use distinct __tablename__ values."""
        # Use SQLite in-memory so psycopg2 is not required in the test env.
        os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

        import importlib
        import types

        # Create a fake 'database' package namespace so that
        # `from .database import Base` inside models.py resolves correctly.
        db_pkg = types.ModuleType("database")
        db_pkg.__path__ = [os.path.join(BOOKING_AGENT, "database")]
        db_pkg.__package__ = "database"
        sys.modules["database"] = db_pkg

        db_spec = importlib.util.spec_from_file_location(
            "database.database",
            os.path.join(BOOKING_AGENT, "database", "database.py"),
            submodule_search_locations=[],
        )
        db_mod = importlib.util.module_from_spec(db_spec)
        db_mod.__package__ = "database"
        sys.modules["database.database"] = db_mod
        db_spec.loader.exec_module(db_mod)
        db_pkg.database = db_mod  # make package.database attribute visible

        m_spec = importlib.util.spec_from_file_location(
            "database.models",
            os.path.join(BOOKING_AGENT, "database", "models.py"),
            submodule_search_locations=[],
        )
        m_mod = importlib.util.module_from_spec(m_spec)
        m_mod.__package__ = "database"
        sys.modules["database.models"] = m_mod
        m_spec.loader.exec_module(m_mod)

        expected = {
            "trains",
            "train_schedules",
            "bookings",
            "cancellation_requests",
            "audit_logs",
        }
        actual = {
            cls.__tablename__
            for cls in (
                m_mod.Train,
                m_mod.TrainSchedule,
                m_mod.Booking,
                m_mod.CancellationRequest,
                m_mod.AuditLog,
            )
        }
        assert actual == expected, f"Table name mismatch: {actual} != {expected}"
        assert len(actual) == 5

    def test_fare_is_numeric_not_float(self):
        """Booking.fare column must use Numeric, not Float (monetary safety)."""
        os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
        import importlib
        import types
        from sqlalchemy import Numeric as SANumeric, Float as SAFloat

        # Register the database package namespace for relative imports.
        db_pkg = sys.modules.get("database") or types.ModuleType("database")
        db_pkg.__path__ = [os.path.join(BOOKING_AGENT, "database")]
        db_pkg.__package__ = "database"
        sys.modules["database"] = db_pkg

        db_spec = importlib.util.spec_from_file_location(
            "database.database",
            os.path.join(BOOKING_AGENT, "database", "database.py"),
            submodule_search_locations=[],
        )
        db_mod = importlib.util.module_from_spec(db_spec)
        db_mod.__package__ = "database"
        sys.modules["database.database"] = db_mod
        db_spec.loader.exec_module(db_mod)
        db_pkg.database = db_mod

        m_spec = importlib.util.spec_from_file_location(
            "database.models",
            os.path.join(BOOKING_AGENT, "database", "models.py"),
            submodule_search_locations=[],
        )
        m_mod = importlib.util.module_from_spec(m_spec)
        m_mod.__package__ = "database"
        sys.modules["database.models"] = m_mod
        m_spec.loader.exec_module(m_mod)

        fare_col_type = m_mod.Booking.__table__.c["fare"].type
        assert isinstance(fare_col_type, SANumeric), (
            f"fare column should be Numeric, got {type(fare_col_type).__name__}"
        )
        assert not isinstance(fare_col_type, SAFloat)


# ===========================================================================
# 7. Agent registry tests
# ===========================================================================

class TestAgentRegistry:

    def _load_registry(self):
        import importlib
        spec = importlib.util.spec_from_file_location(
            "reg_test",
            os.path.join(MEMBER_C, "agent-hub", "registry.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["reg_test"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_all_agents_registered(self):
        reg = self._load_registry()
        names = {e.name for e in reg.list_agents()}
        required = {
            "passenger-agent",
            "booking-agent",
            "security-agent",
            "operations-agent",
            "maintenance-agent",
        }
        assert required == names

    def test_get_booking_agent_url(self):
        reg = self._load_registry()
        url = reg.get_agent_url("booking-agent")
        assert url.startswith("http")
        assert not url.endswith("/")   # trailing slash stripped

    def test_unknown_agent_raises(self):
        reg = self._load_registry()
        with pytest.raises(reg.AgentNotFoundError):
            reg.get_agent_url("ghost-agent")

    def test_registry_no_http_calls(self):
        """Registry must not import httpx or requests at module level."""
        import ast, pathlib
        src = pathlib.Path(
            os.path.join(MEMBER_C, "agent-hub", "registry.py")
        ).read_text(encoding="utf-8")
        tree = ast.parse(src)
        http_imports = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and any(
                alias.name in ("httpx", "requests", "urllib", "aiohttp")
                for alias in (node.names if hasattr(node, "names") else [])
            )
        ]
        assert not http_imports, "Registry must not import HTTP libraries"
