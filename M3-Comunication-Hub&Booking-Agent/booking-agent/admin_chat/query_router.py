"""
admin_chat/query_router.py
--------------------------
Central query router and orchestration service for the Admin Booking Intelligence Assistant.
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from sqlalchemy.orm import Session

from .llm_service import generate_chat_response
from .nlp import process_admin_nlp
from .rag_context import build_rag_context
from .retrieval import (
    retrieve_booking_lookup,
    retrieve_booking_summary,
    retrieve_cancellations,
    retrieve_fraud_reviews,
    retrieve_manifest,
    retrieve_seat_availability,
)
from .schemas import AdminChatRequest, AdminChatResponse


class AdminChatService:
    """
    Orchestrates Query Understanding (NLP), Live Database Retrieval (IR),
    Policy Knowledge Base (RAG), and Grounded LLM Explanation.
    """

    def __init__(self, db: Session):
        self.db = db

    def process_chat_message(self, request: AdminChatRequest) -> AdminChatResponse:
        t0 = time.time()
        conv_id = request.conversation_id or f"conv_{uuid.uuid4().hex[:8]}"

        # 1. NLP Query Understanding & Follow-up Entity Stitching
        history_dicts = [m.model_dump() for m in request.history] if request.history else None
        nlp_result = process_admin_nlp(request.message, history=history_dicts)

        intent = nlp_result["intent"]
        entities = nlp_result["entities"]
        clean_msg = nlp_result["clean_message"]

        # 2. Information Retrieval from M3 Database
        db_evidence: dict[str, Any] = {}

        if intent == "unsupported_mutation":
            db_evidence = {"refusal": True}

        elif intent in ("seat_availability_query", "schedule_query"):
            db_evidence = retrieve_seat_availability(self.db, entities)

        elif intent == "fraud_review_query":
            db_evidence = retrieve_fraud_reviews(self.db, entities)

        elif intent == "cancellation_query":
            db_evidence = retrieve_cancellations(self.db, entities)

        elif intent == "booking_manifest_query":
            db_evidence = retrieve_manifest(self.db, entities)

        elif intent == "booking_lookup":
            b_ref = entities.get("booking_reference", "")
            db_evidence = retrieve_booking_lookup(self.db, b_ref)

        elif intent == "booking_statistics":
            db_evidence = retrieve_booking_summary(self.db, entities)

        else:
            # Fallback search attempts
            if entities.get("train_name") or entities.get("train_id"):
                db_evidence = retrieve_seat_availability(self.db, entities)
            else:
                db_evidence = {"found": False}

        # 3. Hybrid RAG Context Building
        rag_context = build_rag_context(
            intent=intent,
            query=clean_msg,
            db_evidence=db_evidence,
        )

        # 4. LLM Generation & Factual Consistency Verification
        response = generate_chat_response(
            intent=intent,
            rag_context=rag_context,
            entities=entities,
            conversation_id=conv_id,
        )

        # 5. Audit Logging (privacy-safe, no plaintext PII)
        elapsed_ms = (time.time() - t0) * 1000.0
        try:
            from agent_hub.audit.service import write_audit_log
            write_audit_log(
                message_id=f"CHAT-{uuid.uuid4().hex[:8]}",
                sender_agent="admin-console",
                receiver_agent="booking-intelligence-chat",
                intent=intent,
                status="VALIDATED",
                duration_ms=elapsed_ms,
            )
        except Exception:
            pass

        return response
