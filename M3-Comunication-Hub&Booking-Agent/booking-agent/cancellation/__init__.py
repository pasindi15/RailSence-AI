"""
cancellation package for RailSense AI.
"""

from .nlp import (
    process_cancellation_nlp,
    classify_cancellation_reason,
    extract_cancellation_entities,
    analyze_admin_rejection_reason,
)
from .rag import retrieve_relevant_policies
from .rules import calculate_cancellation_refund
from .llm import generate_admin_advisory_summary
from .service import (
    CancellationService,
    CancellationError,
    BookingNotFoundError,
    BookingAlreadyCancelledError,
    CancellationAlreadyPendingError,
)

__all__ = [
    "process_cancellation_nlp",
    "classify_cancellation_reason",
    "extract_cancellation_entities",
    "analyze_admin_rejection_reason",
    "retrieve_relevant_policies",
    "calculate_cancellation_refund",
    "generate_admin_advisory_summary",
    "CancellationService",
    "CancellationError",
    "BookingNotFoundError",
    "BookingAlreadyCancelledError",
    "CancellationAlreadyPendingError",
]
