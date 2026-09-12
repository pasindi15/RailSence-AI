"""
tests/conftest.py
-----------------
Pytest configuration and global fixtures for Member C tests.
Provides default mock transport so unit tests do not require live external agent servers.
"""

from __future__ import annotations

import os
import sys

import httpx
import pytest

# Ensure member-c directories are in sys.path
MEMBER_C = os.path.dirname(os.path.dirname(__file__))
AGENT_HUB = os.path.join(MEMBER_C, "agent-hub")
BOOKING_AGENT = os.path.join(MEMBER_C, "booking-agent")

for p in (MEMBER_C, AGENT_HUB, BOOKING_AGENT):
    if p not in sys.path:
        sys.path.insert(0, p)

from router import set_default_transport


def default_mock_handler(request: httpx.Request) -> httpx.Response:
    """Default mock handler simulating a successful destination agent response."""
    return httpx.Response(
        status_code=202,
        json={
            "message_id": "MSG-ACK",
            "status": "received_for_phase_1",
            "note": "Message received by destination agent mock.",
        },
    )


@pytest.fixture(autouse=True, scope="session")
def setup_test_database():
    """Ensure SQLite test database has schema and fresh seed data for test run."""
    from database.database import Base, SessionLocal, engine
    from database.seed import seed_test_train_data

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_test_train_data(db)


@pytest.fixture(autouse=True)
def default_http_client_mock():
    """
    Autouse fixture configuring a default mock transport for downstream agent calls.
    Any test overriding get_http_client on app.dependency_overrides takes precedence.
    """
    transport = httpx.MockTransport(default_mock_handler)
    set_default_transport(transport)
    yield
    set_default_transport(None)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Ensure in-memory rate limiter is reset before and after every test."""
    try:
        from rate_limit import rate_limiter
        rate_limiter.reset()
    except ImportError:
        pass
    yield
    try:
        from rate_limit import rate_limiter
        rate_limiter.reset()
    except ImportError:
        pass


SECURITY_AGENT_DIR = os.path.join(os.path.dirname(MEMBER_C), "security-agent")
def security_agent_sync_handler(request: httpx.Request) -> httpx.Response:
    import json
    path = request.url.path
    if path == "/health":
        return httpx.Response(200, json={"service": "security-agent", "status": "ok"})
    if path.endswith("/internal/fraud-score"):
        try:
            body = json.loads(request.content.decode("utf-8"))
        except Exception:
            body = {}
        if SECURITY_AGENT_DIR not in sys.path:
            sys.path.insert(0, SECURITY_AGENT_DIR)
        from fraud.model import fraud_detector
        res = fraud_detector.score_features(body.get("features", {}))
        return httpx.Response(200, json=res)
    return httpx.Response(404, json={"detail": "Not found"})


@pytest.fixture(autouse=True)
def default_security_agent_transport():
    """Wire real Security Agent (IsolationForest ML) via sync MockTransport during tests."""
    from fraud.client import set_security_client_transport
    try:
        transport = httpx.MockTransport(security_agent_sync_handler)
        set_security_client_transport(transport)
    except Exception:
        pass
    yield
    set_security_client_transport(None)



