"""
agent-hub/registry.py
---------------------
RailSense AI — Agent Registry
Phase 1: logical-name -> base-URL mapping for all known agents.

Architectural rules
-------------------
- This module is LOOKUP ONLY.  It never makes HTTP calls.
- Service URLs are read from environment variables so that the same image
  works in development, staging, and production without code changes.
- Unknown agent names raise AgentNotFoundError so callers always get a
  clear, catchable error rather than a silent None bug.

Phase 2 additions (not implemented here)
-----------------------------------------
- httpx forwarding using the URLs returned by get_agent_url()
- Health-check polling to mark agents online/offline
- Dynamic registration via a POST /registry/register endpoint
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Registry entry — plain immutable class (no @dataclass to avoid importlib
# dynamic-load edge cases with cls.__module__ resolution)
# ---------------------------------------------------------------------------

class AgentEntry:
    """Immutable descriptor for a registered agent."""

    __slots__ = ("name", "base_url", "description")

    def __init__(self, name: str, base_url: str, description: str = "") -> None:
        object.__setattr__(self, "name",        name)
        object.__setattr__(self, "base_url",    base_url)
        object.__setattr__(self, "description", description)

    def __setattr__(self, key: str, value: object) -> None:  # type: ignore[override]
        raise AttributeError("AgentEntry is immutable")

    def __repr__(self) -> str:
        return f"AgentEntry(name={self.name!r}, base_url={self.base_url!r})"


# ---------------------------------------------------------------------------
# Application-specific exception
# ---------------------------------------------------------------------------

class AgentNotFoundError(KeyError):
    """
    Raised when get_agent_url() is called with an unrecognised agent name.

    Inherits from KeyError so it behaves naturally in dict-like lookups while
    still being catchable with its own specific type.
    """

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        super().__init__(
            f"No registered agent named {agent_name!r}. "
            f"Known agents: {', '.join(REGISTRY.keys())}"
        )


# ---------------------------------------------------------------------------
# Registry — populated from environment variables
# ---------------------------------------------------------------------------
# Development defaults are provided so the hub starts without a .env file
# during initial local setup.  In production, all values MUST be set
# explicitly via environment variables or a secrets manager.
#
# Port conventions (Member C):
#   8002  ->  agent-hub           (this service)
#   8003  ->  booking-agent
#
# Port conventions (other members — placeholders, may change):
#   8001  ->  passenger-agent
#   8004  ->  security-agent
#   8005  ->  operations-agent
#   8006  ->  maintenance-agent

REGISTRY: dict[str, AgentEntry] = {

    "passenger-agent": AgentEntry(
        name="passenger-agent",
        base_url=os.getenv("PASSENGER_AGENT_URL", "http://localhost:8001"),
        description=(
            "Passenger-facing conversational agent. "
            "Collects booking/cancellation intent and dispatches AgentMessages."
        ),
    ),

    "booking-agent": AgentEntry(
        name="booking-agent",
        base_url=os.getenv("BOOKING_AGENT_URL", "http://localhost:8003"),
        description=(
            "Booking & Reservation Agent (Member C). "
            "Processes booking_request and cancel_booking intents against the "
            "PostgreSQL database. Availability and fare are determined by "
            "deterministic backend logic — never by an LLM."
        ),
    ),

    "security-agent": AgentEntry(
        name="security-agent",
        base_url=os.getenv("SECURITY_AGENT_URL", "http://localhost:8004"),
        description=(
            "Security agent responsible for authentication and authorisation. "
            "JWT verification will be delegated here in Phase 2."
        ),
    ),

    "operations-agent": AgentEntry(
        name="operations-agent",
        base_url=os.getenv("OPERATIONS_AGENT_URL", "http://localhost:8005"),
        description="Train operations and schedule management agent.",
    ),

    "maintenance-agent": AgentEntry(
        name="maintenance-agent",
        base_url=os.getenv("MAINTENANCE_AGENT_URL", "http://localhost:8006"),
        description="Rolling-stock and infrastructure maintenance agent.",
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_agent_url(agent_name: str) -> str:
    """
    Return the registered base URL for the given logical agent name.

    Parameters
    ----------
    agent_name : str
        The logical name exactly as it appears in AgentMessage.sender_agent /
        receiver_agent (e.g. ``"booking-agent"``).

    Returns
    -------
    str
        The base URL of the agent's HTTP service (no trailing slash).

    Raises
    ------
    AgentNotFoundError
        If *agent_name* is not present in the registry.

    Notes
    -----
    Phase 1: lookup only — no HTTP requests are made here.
    Phase 2: this URL will be used by the hub's routing layer to forward
    validated AgentMessages via httpx.
    """
    entry = REGISTRY.get(agent_name)
    if entry is None:
        raise AgentNotFoundError(agent_name)
    return entry.base_url.rstrip("/")


def get_agent_entry(agent_name: str) -> AgentEntry:
    """
    Return the full AgentEntry for *agent_name*.

    Useful when the caller needs metadata (description) in addition to the URL.

    Raises
    ------
    AgentNotFoundError
        If *agent_name* is not registered.
    """
    entry = REGISTRY.get(agent_name)
    if entry is None:
        raise AgentNotFoundError(agent_name)
    return entry


def list_agents() -> list[AgentEntry]:
    """Return all registered agents as an ordered list (alphabetical by name)."""
    return sorted(REGISTRY.values(), key=lambda e: e.name)
