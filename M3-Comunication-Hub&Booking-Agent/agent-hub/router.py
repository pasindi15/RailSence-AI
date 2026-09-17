"""
agent-hub/router.py
-------------------
RailSense AI — Central Agent Communication Hub Message Router
Phase 2: Asynchronous inter-agent HTTP routing via httpx.

Architectural rules:
- Resolves destination agent base URL from registry.py using receiver_agent.
- Appends /internal/messages endpoint.
- Forwards validated AgentMessage without modifying booking payload or business data.
- Never prints or logs auth_token (preserves it in transit).
- Maps connection/network errors to HTTP 503 (Service Unavailable).
- Maps timeouts to HTTP 504 (Gateway Timeout).
- Maps destination 4xx/5xx errors to HTTP 502 (Bad Gateway).
- Uses sensible timeouts (configurable via HTTP_TIMEOUT env var, default 5.0s).
"""

from __future__ import annotations

import os
import sys
from typing import Any, AsyncGenerator

import httpx
from fastapi import HTTPException, status

# Path resolution
_CURRENT_DIR = os.path.dirname(__file__)
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_CURRENT_DIR))

_MEMBER_C_ROOT = os.path.abspath(os.path.join(_CURRENT_DIR, ".."))
if _MEMBER_C_ROOT not in sys.path:
    sys.path.insert(0, _MEMBER_C_ROOT)

from auth.jwt_utils import mint_delegation_token  # noqa: E402
from registry import get_agent_url, AgentNotFoundError  # noqa: E402
from resilience import hub_resilience  # noqa: E402
from shared.schemas import AgentMessage  # noqa: E402

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "30.0"))
_DEFAULT_TEST_TRANSPORT: httpx.BaseTransport | None = None


def set_default_transport(transport: httpx.BaseTransport | None) -> None:
    """Set default transport for testing environments without live agents."""
    global _DEFAULT_TEST_TRANSPORT
    _DEFAULT_TEST_TRANSPORT = transport


class RoutingError(HTTPException):
    """Exception raised when forwarding a message to a downstream agent fails."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(status_code=status_code, detail=detail)


async def get_http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    FastAPI dependency yielding an asynchronous HTTP client with sensible timeout.
    Can be overridden in tests to mock downstream agents.
    """
    if _DEFAULT_TEST_TRANSPORT is not None:
        async with httpx.AsyncClient(transport=_DEFAULT_TEST_TRANSPORT, timeout=HTTP_TIMEOUT) as client:
            yield client
    else:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            yield client


async def route_message(
    message: AgentMessage,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, dict[str, Any]]:
    """
    Forward an AgentMessage to the registered destination agent.

    Applies per-receiver circuit breaker checks, bounded retry on transient network errors,
    attaches trusted Hub delegation token, and preserves typed downstream domain errors.
    """
    try:
        base_url = get_agent_url(message.receiver_agent)
    except AgentNotFoundError:
        raise RoutingError(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Receiver agent '{message.receiver_agent}' is not registered in the agent registry.",
        )

    # Circuit Breaker Check
    breaker = hub_resilience.get_breaker(message.receiver_agent)
    if not breaker.allow_request():
        time_rem = breaker.get_time_until_probe()
        raise RoutingError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Circuit breaker for '{message.receiver_agent}' is OPEN ({time_rem:.1f}s remaining). Downstream agent temporarily unavailable.",
        )

    # Target endpoint
    destination_url = f"{base_url}/internal/messages"

    # Mint delegation token asserting Hub verified the sender
    original_user = message.payload.get("user_id") if isinstance(message.payload, dict) else None
    delegation_jwt = mint_delegation_token(
        original_sender=message.sender_agent,
        receiver_agent=message.receiver_agent,
        user_id=original_user,
    )

    headers = {
        "X-Delegation-Token": delegation_jwt,
        "X-Correlation-ID": message.get_correlation_id(),
        "X-Sender-Agent": message.sender_agent,
    }

    payload = message.model_dump(mode="json")
    # Propagate correlation_id and increment hop_count for loop defense
    payload["correlation_id"] = message.get_correlation_id()
    payload["hop_count"] = message.hop_count + 1

    max_retries = 2
    retry_delays = [0.05, 0.1]
    response: httpx.Response | None = None

    async def _attempt_send(c: httpx.AsyncClient) -> httpx.Response:
        return await c.post(destination_url, json=payload, headers=headers)

    for attempt in range(max_retries + 1):
        try:
            if client is not None:
                response = await _attempt_send(client)
            else:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as local_client:
                    response = await _attempt_send(local_client)
            break
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            if attempt < max_retries:
                import asyncio
                await asyncio.sleep(retry_delays[attempt])
                continue
            breaker.record_failure()
            raise RoutingError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Destination agent '{message.receiver_agent}' is unavailable (connection refused).",
            ) from None
        except httpx.TimeoutException:
            if attempt < max_retries:
                import asyncio
                await asyncio.sleep(retry_delays[attempt])
                continue
            breaker.record_failure()
            raise RoutingError(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Destination agent '{message.receiver_agent}' timed out.",
            ) from None
        except httpx.HTTPError as exc:
            breaker.record_failure()
            raise RoutingError(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Destination agent '{message.receiver_agent}' communication error: {exc.__class__.__name__}",
            ) from None

    if response is None:
        breaker.record_failure()
        raise RoutingError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Destination agent '{message.receiver_agent}' failed to respond.",
        )

    # Successful HTTP connection reached downstream
    if response.status_code >= 500:
        breaker.record_failure()
        raise RoutingError(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Destination agent '{message.receiver_agent}' returned a server error (HTTP {response.status_code}).",
        )
    elif response.status_code >= 400:
        # Service is alive and returning valid application domain responses
        breaker.record_success()
        try:
            err_data = response.json()
            downstream_detail = err_data.get("detail", str(err_data))
        except Exception:
            downstream_detail = response.text or ""
        msg = f"Destination agent '{message.receiver_agent}' returned an error (HTTP {response.status_code})"
        if downstream_detail:
            msg += f": {downstream_detail}"
        raise RoutingError(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=msg,
        )

    # 2xx Success
    breaker.record_success()
    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}

    return response.status_code, data

