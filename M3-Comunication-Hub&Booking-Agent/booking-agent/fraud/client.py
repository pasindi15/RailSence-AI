"""
fraud/client.py
---------------
RailSense AI — Client for Security & Fraud Agent Inter-Agent Communication.

Responsibilities:
1. Dispatches behavioral numerical features to Security Agent (POST /internal/fraud-score).
2. Maintains strict multi-agent boundary:
   - Does NOT run IsolationForest directly inside Booking Agent.
   - If Security Agent is unreachable, fails safely by flagging PENDING_FRAUD_REVIEW
     with reason 'SECURITY_AGENT_UNAVAILABLE'.
   - NEVER silently issues a confirmed ticket without security evaluation.
"""

from __future__ import annotations

import os
from typing import Any
import httpx


SECURITY_AGENT_URL = os.getenv("SECURITY_AGENT_URL", "http://localhost:8004").rstrip("/")

_test_transport: httpx.BaseTransport | None = None


def set_security_client_transport(transport: httpx.BaseTransport | None) -> None:
    """Configure in-memory ASGI transport for tests."""
    global _test_transport
    _test_transport = transport


def request_fraud_score(
    features: dict[str, float],
    nic_key: str = "",
    timeout: float = 4.0,
) -> dict[str, Any]:
    """
    Call Security Agent via HTTP POST /internal/fraud-score.

    If Security Agent is unavailable:
    Does NOT silently approve the ticket.
    Returns a safe fail-closed result requiring human admin review:
    risk_level='MEDIUM', recommended_action='REVIEW', reason='SECURITY_AGENT_UNAVAILABLE'.
    """
    endpoint = f"{SECURITY_AGENT_URL}/internal/fraud-score"
    payload = {
        "nic_key": nic_key,
        "features": features,
    }

    try:
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        if _test_transport is not None:
            client_kwargs["transport"] = _test_transport

        with httpx.Client(**client_kwargs) as client:
            resp = client.post(endpoint, json=payload)
            if resp.status_code == 200:
                return resp.json()
            else:
                return {
                    "risk_score": 0.65,
                    "risk_level": "MEDIUM",
                    "recommended_action": "REVIEW",
                    "reasons": [f"SECURITY_AGENT_ERROR: Security Agent returned HTTP {resp.status_code}."],
                    "model": "SecurityAgentGateway",
                }
    except (httpx.ConnectError, httpx.TimeoutException, Exception) as exc:
        # Multi-Agent Boundary: Fail-closed fallback to human review (never silently approve)
        return {
            "risk_score": 0.50,
            "risk_level": "MEDIUM",
            "recommended_action": "REVIEW",
            "reasons": ["SECURITY_AGENT_UNAVAILABLE: Security Agent was unreachable; booking flagged for human review."],
            "model": "FailClosedFallback",
        }
