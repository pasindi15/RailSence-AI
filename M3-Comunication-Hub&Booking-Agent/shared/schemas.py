"""
shared/schemas.py
-----------------
Shared Pydantic v2 schemas for inter-agent communication across Member C.

These schemas define the envelope that all agents use when calling each other
via the Central Agent Hub.  The payload field is intentionally left as a
generic dict so that different agents can pass their own structured data
without this module needing to know every agent-specific shape.

Phase 1 note
------------
auth_token is captured and forwarded as-is.  JWT verification is NOT performed
here; that belongs to a later phase.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Intent enum
# ---------------------------------------------------------------------------

class MemberCIntent(str, Enum):
    """Supported intents handled by RailSense AI agents."""

    booking_request      = "booking_request"
    cancel_booking       = "cancel_booking"
    delay_check          = "delay_check"
    delay_check_response = "delay_check_response"
    delay_alert          = "delay_alert"
    historical_incidents = "historical_incidents"
    operational_alert    = "operational_alert"
    train_status_query   = "train_status_query"
    issue_report         = "issue_report"
    incident_report      = "incident_report"
    fraud_score_request  = "fraud_score_request"
    ack                  = "ack"


# Architectural alias for external and pipeline references
IntentType = MemberCIntent



# ---------------------------------------------------------------------------
# Inter-agent envelope
# ---------------------------------------------------------------------------

class AgentMessage(BaseModel):
    """
    Standard message envelope exchanged between agents via the Agent Hub.

    Attributes
    ----------
    message_id:        Unique identifier for this message (e.g. "MSG-2001").
    sender_agent:      Logical name of the originating agent.
    receiver_agent:    Logical name of the target agent.
    intent:            The action the receiver should perform.
    payload:           Arbitrary JSON-compatible dict carrying intent-specific data.
    auth_token:        Raw bearer token forwarded from the originating request.
    timestamp:         ISO-8601 datetime (timezone-aware recommended) of when the
                       message was created.
    correlation_id:    Unique ID spanning all related messages in a business workflow.
    parent_message_id: Direct causal predecessor message ID if applicable.
    schema_version:    Version identifier for the envelope schema.
    hop_count:         Monotonically incremented dispatch counter for loop prevention.
    """

    message_id:        str              = Field(..., min_length=1, description="Unique message identifier")
    sender_agent:      str              = Field(..., min_length=1, description="Originating agent name")
    receiver_agent:    str              = Field(..., min_length=1, description="Target agent name")
    intent:            MemberCIntent    = Field(...,               description="Action the receiver should perform")
    payload:           dict[str, Any]   = Field(...,               description="Intent-specific payload data")
    auth_token:        str              = Field(..., min_length=1, description="Bearer token")
    timestamp:         datetime         = Field(...,               description="Message creation time")
    correlation_id:    str | None       = Field(default=None,      description="End-to-end workflow correlation ID")
    parent_message_id: str | None       = Field(default=None,      description="Predecessor message ID")
    schema_version:    str              = Field(default="1.1",     description="Schema version")
    hop_count:         int              = Field(default=0, ge=0,   description="Monotonic hop counter")

    model_config = {"str_strip_whitespace": True}

    def get_correlation_id(self) -> str:
        """Return explicit correlation_id or fallback to message_id."""
        return self.correlation_id or self.message_id

