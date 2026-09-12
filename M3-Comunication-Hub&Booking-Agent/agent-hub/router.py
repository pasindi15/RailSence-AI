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

from registry import get_agent_url, AgentNotFoundError  # noqa: E402
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

    Parameters
    ----------
    message : AgentMessage
        The validated and authenticated message envelope.
    client : httpx.AsyncClient | None, optional
        Active asynchronous HTTP client. If None, creates a standalone client.

    Returns
    -------
    tuple[int, dict[str, Any]]
        A tuple of (destination_status_code, destination_response_data).

    Raises
    ------
    RoutingError (404)
        If receiver_agent is not registered.
    RoutingError (503)
        If the destination agent cannot be reached (connection refused).
    RoutingError (504)
        If the destination agent request times out.
    RoutingError (502)
        If the destination agent returns a 4xx or 5xx error.
    """
    try:
        base_url = get_agent_url(message.receiver_agent)
    except AgentNotFoundError:
        raise RoutingError(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Receiver agent '{message.receiver_agent}' is not registered in the agent registry.",
        )

    destination_url = f"{base_url}/internal/messages"
    payload = message.model_dump(mode="json")

    async def _send(c: httpx.AsyncClient) -> httpx.Response:
        try:
            return await c.post(destination_url, json=payload)
        except (httpx.ConnectError, httpx.NetworkError):
            raise RoutingError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Destination agent '{message.receiver_agent}' is unavailable (connection refused).",
            ) from None
        except httpx.TimeoutException:
            raise RoutingError(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Destination agent '{message.receiver_agent}' timed out.",
            ) from None
        except httpx.HTTPError as exc:
            raise RoutingError(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Destination agent '{message.receiver_agent}' communication error: {exc.__class__.__name__}",
            ) from None

    if client is not None:
        response = await _send(client)
    else:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as local_client:
            response = await _send(local_client)

    # Handle downstream HTTP errors
    if response.status_code >= 500:
        raise RoutingError(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Destination agent '{message.receiver_agent}' returned a server error (HTTP {response.status_code}).",
        )
    elif response.status_code >= 400:
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

    # Parse response body
    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}

    return response.status_code, data
