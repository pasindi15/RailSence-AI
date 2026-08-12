"""
schemas.py
Pydantic models for the Passenger Assistant Agent's own API,
plus the shared Hub message envelope (Section 7.2 of the implementation guide).

Phase 1 note: ChatRequest validation IS your input-sanitization layer.
Reject bad input here, before it ever reaches an LLM prompt.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, Literal

from pydantic import BaseModel, Field, field_validator


# ---------- Your own /chat API ----------

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    session_id: Optional[str] = Field(default=None, max_length=100)
    language_hint: Optional[Literal["en", "si", "ta"]] = None

    @field_validator("message")
    @classmethod
    def sanitize_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message cannot be empty")

        # Reject obvious script/HTML injection attempts
        lowered = v.lower()
        blocked_patterns = ["<script", "javascript:", "onerror=", "onload="]
        if any(p in lowered for p in blocked_patterns):
            raise ValueError("message contains disallowed content")

        # Reject control characters (keeps Sinhala/Tamil unicode text intact —
        # only strips ASCII control chars, not multi-byte scripts)
        if any(ord(ch) < 9 for ch in v):
            raise ValueError("message contains invalid control characters")

        return v


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    detected_language: Optional[str] = None
    intent: Optional[str] = None
    sources: list[str] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    session_id: str
    rating: Literal["up", "down"]
    comment: Optional[str] = Field(default=None, max_length=500)


class HealthResponse(BaseModel):
    status: str
    agent: str


# ---------- Shared Hub message envelope ----------
# Mirrors Section 7.2 of the implementation guide.
# Keep this in sync with agent-hub/schema.py once Member C publishes it —
# this is the "contract" referenced in the Phase 3 integration note.

class HubMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender_agent: str = "passenger-agent"
    receiver_agent: str
    intent: str
    payload: dict
    auth_token: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class HubResponse(BaseModel):
    message_id: str
    status: Literal["ok", "error", "timeout"]
    payload: dict = Field(default_factory=dict)
    error: Optional[str] = None
