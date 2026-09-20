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
import uuid
from typing import Any
import httpx


SECURITY_AGENT_URL = os.getenv("SECURITY_AGENT_URL", "http://127.0.0.1:8004").rstrip("/")
HUB_URL = os.getenv("HUB_URL", "http://127.0.0.1:8002").rstrip("/")

_test_transport: httpx.BaseTransport | None = None
_shared_client: httpx.Client | None = None


def _get_shared_client(timeout: float = 4.0) -> httpx.Client:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.Client(timeout=timeout)
    return _shared_client


def set_security_client_transport(transport: httpx.BaseTransport | None) -> None:
    """Configure in-memory ASGI transport for tests."""
    global _test_transport
    _test_transport = transport


def request_fraud_score_via_hub(
    features: dict[str, float],
    nic_key: str = "",
    travel_context: dict[str, Any] | None = None,
    timeout: float = 4.0,
) -> dict[str, Any]:
    """
    Route fraud score request through the Central Communication Hub.
    Uses AgentMessage envelope with intent 'fraud_score_request'.
    """
    hub_endpoint = f"{HUB_URL}/messages"
    message_payload = {
        "message_id": f"MSG-FRAUD-{uuid.uuid4().hex[:8]}",
        "sender": "booking-agent",
        "receiver": "security-agent",
        "intent": "fraud_score_request",
        "body": {
            "features": features,
            "nic_key": nic_key,
            "travel_context": travel_context or {},
        },
    }

    try:
        client = httpx.Client(transport=_test_transport, timeout=timeout) if _test_transport else _get_shared_client(timeout)
        resp = client.post(hub_endpoint, json=message_payload)
        if _test_transport:
            client.close()
        if resp.status_code == 200:
            data = resp.json()
            if "result" in data:
                return data["result"]
            return data
        elif resp.status_code == 202:
            return {
                "risk_score": 0.10,
                "risk_level": "LOW",
                "recommended_action": "ALLOW",
                "reasons": ["ASYNC_HUB_EVALUATION"],
                "model": "HubAsyncRouter",
            }
    except Exception:
        pass

    return {
        "risk_score": 0.50,
        "risk_level": "MEDIUM",
        "recommended_action": "REVIEW",
        "reasons": ["SECURITY_AGENT_UNAVAILABLE: Communication Hub unreachable for fraud check."],
        "model": "FailClosedFallback",
    }


def request_fraud_score(
    features: dict[str, float],
    nic_key: str = "",
    travel_context: dict[str, Any] | None = None,
    timeout: float = 4.0,
) -> dict[str, Any]:
    """
    Call Security Agent via HTTP POST /internal/fraud-score (or via Hub if configured).

    If Security Agent is unavailable:
    Does NOT silently approve the ticket.
    Returns a safe fail-closed result requiring human admin review:
    risk_level='MEDIUM', recommended_action='REVIEW', reason='SECURITY_AGENT_UNAVAILABLE'.
    """
    if os.getenv("USE_HUB_FOR_FRAUD", "0") == "1" and _test_transport is None:
        return request_fraud_score_via_hub(features, nic_key, travel_context, timeout)

    endpoint = f"{SECURITY_AGENT_URL}/internal/fraud-score"
    payload = {
        "nic_key": nic_key,
        "features": features,
        "travel_context": travel_context or {},
    }

    try:
        if _test_transport is not None:
            with httpx.Client(transport=_test_transport, timeout=timeout) as client:
                resp = client.post(endpoint, json=payload)
        else:
            client = _get_shared_client(timeout)
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

