"""
schema.py — Pydantic message schema for M3 Security Agent / Hub

Phase 2 additions:
  - HubMessage.encrypt_payload — per-message AES-256 encryption flag
  - HubMessage payload sanitization validator — rejects HTML/control chars
  - RevokeRequest — body model for POST /auth/revoke

All inter-agent communication uses HubMessage; agents declare themselves
with AgentRegistration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, validator

from auth.sanitize import sanitize_text


class HubMessage(BaseModel):
    """
    Canonical inter-agent message envelope.

    Every agent (Passenger, Operations, Maintenance) wraps its request in
    this model before sending it to POST /hub/send.  The Hub validates the
    model on arrival; any field violation returns 422 before any routing
    logic runs.

    Phase 2 additions:
      - encrypt_payload flag controls per-message AES-256 payload encryption.
      - Payload string values are sanitized against HTML injection and control
        characters before any routing logic runs.
    """

    message_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique message identifier (UUID). Auto-generated if omitted.",
        example="b7e1-uuid",
    )
    sender_agent: str = Field(
        ...,
        description="Registered name of the sending agent.",
        example="passenger-agent",
        max_length=64,
    )
    receiver_agent: str = Field(
        ...,
        description="Registered name of the target agent.",
        example="operations-agent",
        max_length=64,
    )
    intent: str = Field(
        ...,
        description="Action the receiver should perform (e.g. 'delay_check', 'book_ticket').",
        example="delay_check",
        max_length=64,
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value data for the intent. Schema is intent-specific.",
        example={"route": "Colombo Fort - Kandy", "train_id": "PM-4082"},
    )
    auth_token: str = Field(
        ...,
        description=(
            "Authentication token.  Phase 1: any non-empty string is accepted. "
            "Phase 2: must be a valid HS256 JWT issued by POST /auth/login."
        ),
        example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        min_length=1,
    )
    encrypt_payload: bool = Field(
        False,
        description=(
            "Phase 2: if True, the Hub will AES-256 encrypt the payload "
            "before forwarding to the target agent. Use for messages containing "
            "passenger PII or sensitive booking data."
        ),
        example=False,
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="ISO-8601 UTC timestamp of message creation.",
        example="2026-09-10T13:58:12",
    )

    @validator("sender_agent", "receiver_agent", "intent", pre=True)
    def _strip_whitespace(cls, v: str) -> str:  # noqa: N805
        return v.strip()

    @validator("payload", pre=True)
    def _sanitize_payload_strings(cls, v: Any) -> Any:  # noqa: N805
        """
        Sanitize all string values inside the payload dict.

        Non-string values (ints, lists, nested dicts) are left untouched.
        Any string value that fails sanitization raises a ValueError which
        Pydantic converts to a 422 response.
        """
        if not isinstance(v, dict):
            return v
        for key, value in v.items():
            if isinstance(value, str):
                sanitize_text(value, field_name=f"payload.{key}")
        return v

    class Config:
        json_encoders = {datetime: lambda dt: dt.isoformat()}
        schema_extra = {
            "example": {
                "message_id": "b7e1-uuid",
                "sender_agent": "passenger-agent",
                "receiver_agent": "operations-agent",
                "intent": "delay_check",
                "payload": {"route": "Colombo Fort - Kandy", "train_id": "PM-4082"},
                "auth_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "encrypt_payload": False,
                "timestamp": "2026-09-10T13:58:12",
            }
        }


class AgentRegistration(BaseModel):
    """
    Sent by each agent to POST /hub/register on startup.

    Phase 1: no authentication required.
    Phase 2: requires a shared secret header before registration is accepted
             (only enforced when AGENT_REGISTRATION_SECRET env var is set).
    """

    agent_id: str = Field(
        ...,
        description="Unique agent name (must match sender_agent in future HubMessages).",
        example="passenger-agent",
        max_length=64,
    )
    base_url: str = Field(
        ...,
        description="Base URL the Hub will forward messages to for this agent.",
        example="http://localhost:8002",
        max_length=256,
    )
    port: Optional[int] = Field(
        None,
        description="Convenience field — port extracted from base_url if not supplied.",
        example=8002,
    )

    @validator("agent_id", "base_url", pre=True)
    def _strip_whitespace(cls, v: str) -> str:  # noqa: N805
        return v.strip()

    class Config:
        schema_extra = {
            "example": {
                "agent_id": "passenger-agent",
                "base_url": "http://localhost:8002",
                "port": 8002,
            }
        }


class LoginRequest(BaseModel):
    """Credentials sent to POST /auth/login."""

    agent_id: str = Field(..., example="passenger-agent", max_length=64)
    secret: str = Field(
        ...,
        description="Shared agent secret. Phase 2: validated against stored bcrypt hash.",
        example="agent-secret",
        min_length=1,
    )


class VerifyRequest(BaseModel):
    """Token sent to POST /auth/verify or POST /auth/revoke."""

    token: str = Field(
        ...,
        description="JWT token to verify or revoke.",
        example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        min_length=1,
    )


class RevokeRequest(BaseModel):
    """Token sent to POST /auth/revoke."""

    token: str = Field(
        ...,
        description="JWT token to immediately invalidate.",
        example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        min_length=1,
    )
