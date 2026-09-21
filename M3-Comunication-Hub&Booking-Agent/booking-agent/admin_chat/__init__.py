"""
admin_chat
----------
RailSense AI — Admin Booking Intelligence Assistant Module.
"""

from .schemas import (
    AdminChatMessage,
    AdminChatRequest,
    AdminChatResponse,
    CardPayload,
    SourceEvidence,
)
from .query_router import AdminChatService
from .nlp import process_admin_nlp

__all__ = [
    "AdminChatMessage",
    "AdminChatRequest",
    "AdminChatResponse",
    "CardPayload",
    "SourceEvidence",
    "AdminChatService",
    "process_admin_nlp",
]
