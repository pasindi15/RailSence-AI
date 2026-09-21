"""
admin_chat/schemas.py
---------------------
Pydantic schemas and data transfer objects for the Admin Booking Intelligence Chatbot.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, field_validator


class AdminChatMessage(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message text")


class AdminChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500, description="Natural language question from administrator")
    conversation_id: str | None = Field(default=None, description="Optional conversation tracking ID")
    history: list[AdminChatMessage] | None = Field(default=None, description="Recent conversation turns for follow-up context")


class SourceEvidence(BaseModel):
    type: str = Field(..., description="Source type e.g. 'schedule', 'seat_inventory', 'policy', 'cancellation', 'fraud_review', 'manifest'")
    id: str = Field(..., description="Entity ID or passage ID e.g. '1005', 'POL-REF-003-ART-2'")
    label: str = Field(..., description="Human-readable reference description")
    details: dict[str, Any] | None = Field(default=None, description="Optional structured metadata")


class CardPayload(BaseModel):
    type: str = Field(..., description="Card type e.g. 'seat_availability', 'fraud_review', 'cancellation', 'booking_summary'")
    title: str = Field(..., description="Card title")
    subtitle: str | None = Field(default=None, description="Card subtitle")
    items: list[dict[str, Any]] = Field(default_factory=list, description="Key-value pairs or row entries")

    @field_validator("items", mode="before")
    @classmethod
    def normalize_items(cls, v: Any) -> list[dict[str, Any]]:
        if not isinstance(v, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in v:
            if isinstance(item, dict):
                normalized.append(item)
            elif isinstance(item, str):
                if ":" in item:
                    k, val = item.split(":", 1)
                    normalized.append({"label": k.strip(), "value": val.strip()})
                else:
                    normalized.append({"label": item.strip(), "value": ""})
            else:
                normalized.append({"label": str(item), "value": ""})
        return normalized


class AdminChatResponse(BaseModel):
    answer: str = Field(..., description="Grounded natural-language answer for the administrator")
    intent: str = Field(..., description="Classified intent")
    entities: dict[str, Any] = Field(default_factory=dict, description="Extracted entities")
    sources: list[SourceEvidence] = Field(default_factory=list, description="Verified evidence sources")
    card: CardPayload | None = Field(default=None, description="Optional structured presentation card")
    retrieved_records: int = Field(default=0, description="Number of primary database records retrieved")
    is_fallback: bool = Field(default=False, description="True if response generated via deterministic synthesizer")
    conversation_id: str | None = Field(default=None, description="Conversation tracking ID")
