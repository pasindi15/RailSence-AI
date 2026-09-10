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
