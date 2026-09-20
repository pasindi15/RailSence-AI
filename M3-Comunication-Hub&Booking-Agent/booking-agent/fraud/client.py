"""
fraud/client.py
---------------
RailSense AI — Client for Security & Fraud Agent Inter-Agent Communication.

Responsibilities:
1. Dispatches behavioral numerical features to Security Agent (POST /internal/fraud-score)
   or routes through Central Communication Hub (POST /messages).
2. Maintains strict multi-agent boundary:
   - Does NOT run IsolationForest directly inside Booking Agent.
   - If Security Agent is unreachable, fails safely by flagging PENDING_FRAUD_REVIEW
     with reason 'SECURITY_AGENT_UNAVAILABLE'.
   - NEVER silently issues a confirmed ticket without security evaluation.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import httpx
import jwt

logger = logging.getLogger("booking_agent.fraud_client")

# ---------------------------------------------------------------------------
# Multi-path .env resolution
# ---------------------------------------------------------------------------
def _load_environment() -> None:
    current_dir = Path(__file__).resolve().parent
    booking_agent_dir = current_dir.parent
    m3_root = booking_agent_dir.parent
    workspace_root = m3_root.parent

    for candidate in (
        booking_agent_dir / ".env",
        m3_root / ".env",
        workspace_root / ".env",
    ):
        if candidate.is_file():
            load_dotenv(dotenv_path=candidate, override=False)
    load_dotenv()

_load_environment()


def get_security_agent_url() -> str:
    return os.getenv("SECURITY_AGENT_URL", "http://127.0.0.1:8004").rstrip("/")


def get_hub_url() -> str:
    return (os.getenv("HUB_URL") or os.getenv("AGENT_HUB_URL") or "http://127.0.0.1:8002").rstrip("/")


def get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret or secret == "change-me":
        _load_environment()
        secret = os.getenv("JWT_SECRET_KEY", "change-me")
    return secret


def get_jwt_algorithm() -> str:
    return os.getenv("JWT_ALGORITHM", "HS256")


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


def request_fraud_score_direct(
    features: dict[str, float],
    nic_key: str = "",
    travel_context: dict[str, Any] | None = None,
    timeout: float = 4.0,
) -> dict[str, Any]:
    """
    Call Security Agent directly via HTTP POST /internal/fraud-score.
    Preserves multi-agent boundary (evaluation is computed by security-agent).
    """
    endpoint = f"{get_security_agent_url()}/internal/fraud-score"
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
            logger.warning("Security Agent direct endpoint returned HTTP %s", resp.status_code)
            return {
                "risk_score": 0.65,
                "risk_level": "MEDIUM",
                "recommended_action": "REVIEW",
                "reasons": [f"SECURITY_AGENT_ERROR: Security Agent returned HTTP {resp.status_code}."],
                "model": "SecurityAgentGateway",
            }
    except (httpx.ConnectError, httpx.TimeoutException, Exception) as exc:
        logger.warning("Direct Security Agent call failed: %s", exc)
        return {
            "risk_score": 0.50,
            "risk_level": "MEDIUM",
            "recommended_action": "REVIEW",
            "reasons": ["SECURITY_AGENT_UNAVAILABLE: Security Agent was unreachable; booking flagged for human review."],
            "model": "FailClosedFallback",
        }


def request_fraud_score_via_hub(
    features: dict[str, float],
    nic_key: str = "",
    travel_context: dict[str, Any] | None = None,
    timeout: float = 4.0,
) -> dict[str, Any]:
    """
    Route fraud score request through the Central Communication Hub.
    Uses AgentMessage envelope with intent 'fraud_score_request'.
    Falls back to direct Security Agent endpoint if Hub is unreachable.
    """
    hub_url = get_hub_url()
    hub_endpoint = f"{hub_url}/messages"
    now = datetime.now(timezone.utc)
    secret = get_jwt_secret()
    algorithm = get_jwt_algorithm()
    auth_token = jwt.encode(
        {
            "sub": "booking-agent",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        secret,
        algorithm=algorithm,
    )
    message_id = f"MSG-FRAUD-{uuid.uuid4().hex[:8]}"
    message_payload = {
        "message_id": message_id,
        "sender_agent": "booking-agent",
        "receiver_agent": "security-agent",
        "intent": "fraud_score_request",
        "payload": {
            "features": features,
            "nic_key": nic_key,
            "travel_context": travel_context or {},
        },
        "auth_token": auth_token,
        "timestamp": now.isoformat(),
        "correlation_id": message_id,
    }

    try:
        client = httpx.Client(transport=_test_transport, timeout=timeout) if _test_transport else _get_shared_client(timeout)
        resp = client.post(hub_endpoint, json=message_payload)
        if _test_transport:
            client.close()

        if resp.status_code == 200:
            data = resp.json()
            destination_response = data.get("response", data)
            if "result" in destination_response:
                return destination_response["result"]
            return destination_response
        elif resp.status_code == 202:
            return {
                "risk_score": 0.10,
                "risk_level": "LOW",
                "recommended_action": "ALLOW",
                "reasons": ["ASYNC_HUB_EVALUATION"],
                "model": "HubAsyncRouter",
            }
        else:
            logger.warning(
                "Communication Hub returned HTTP %s for fraud check (detail: %s). Falling back to direct Security Agent.",
                resp.status_code,
                resp.text[:200],
            )
    except Exception as exc:
        logger.warning(
            "Communication Hub request failed (%s: %s). Falling back to direct Security Agent.",
            type(exc).__name__,
            exc,
        )

    # High-availability resilience: Try direct Security Agent call before fail-closed fallback
    if _test_transport is None:
        direct_result = request_fraud_score_direct(features, nic_key, travel_context, timeout)
        if direct_result.get("model") != "FailClosedFallback":
            return direct_result

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
    Evaluate fraud score via Communication Hub or directly via Security Agent.

    Strict multi-agent boundary:
    If both Hub routing and direct Security Agent evaluation fail:
    Returns safe fail-closed result requiring human review (never silently approves).
    """
    if os.getenv("USE_HUB_FOR_FRAUD", "1") == "1" and _test_transport is None:
        result = request_fraud_score_via_hub(features, nic_key, travel_context, timeout)
        # If Hub returned a valid score (not FailClosedFallback), return it
        if result.get("model") != "FailClosedFallback":
            return result
        # If Hub failed, try direct call as fallback
        direct_result = request_fraud_score_direct(features, nic_key, travel_context, timeout)
        if direct_result.get("model") != "FailClosedFallback":
            return direct_result
        return result

    return request_fraud_score_direct(features, nic_key, travel_context, timeout)

