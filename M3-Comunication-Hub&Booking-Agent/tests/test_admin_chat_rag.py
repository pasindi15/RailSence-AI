"""
tests/test_admin_chat_rag.py
----------------------------
Test suite for RAG context building, policy citations, and factual consistency validation.
"""

import sys
from pathlib import Path
import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_M3_ROOT = _TESTS_DIR.parent
_BOOKING_AGENT_DIR = _M3_ROOT / "booking-agent"

for p in (str(_M3_ROOT), str(_BOOKING_AGENT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from admin_chat.fallback import generate_deterministic_response
from admin_chat.llm_service import verify_factual_consistency
from admin_chat.rag_context import build_rag_context, retrieve_policy_context


class TestAdminChatRAG:

    def test_policy_retrieval_citations(self):
        """1. RAG retrieves official policy citations."""
        c_policies = retrieve_policy_context("cancellation_query", "How much refund for medical emergency?", top_k=2)
        assert len(c_policies) > 0
        p0 = c_policies[0]
        assert "POL-" in p0["passage_id"] or "POL-" in p0["citation"]

        s_policies = retrieve_policy_context("fraud_review_query", "high velocity booking", top_k=2)
        assert len(s_policies) > 0
        assert "POL-" in s_policies[0]["passage_id"] or "POL-" in s_policies[0]["citation"]

    def test_rag_context_assembly(self):
        """2. Hybrid context structure combines DB facts and policy passages."""
        db_ev = {
            "train_name": "Udarata Menike",
            "train_id": "1005",
            "travel_date": "2026-09-25",
            "records": [
                {"seat_class": "First Class", "capacity": 44, "confirmed": 32, "held": 3, "available": 9}
            ]
        }
        ctx = build_rag_context("seat_availability_query", "seats on Udarata Menike", db_ev)
        assert ctx["intent"] == "seat_availability_query"
        assert ctx["database_evidence"]["train_name"] == "Udarata Menike"
        assert len(ctx["policy_context"]) >= 0

    def test_factual_consistency_validator_pass(self):
        """3. Consistent response passes validator."""
        ctx = {
            "database_evidence": {
                "booking_reference": "RS-10055",
                "records": [
                    {"seat_class": "First Class", "capacity": 44, "confirmed": 32, "held": 3, "available": 9}
                ]
            }
        }
        answer = "Udarata Menike currently has 9 First Class seats available for Booking RS-10055."
        valid, issues = verify_factual_consistency(answer, ctx)
        assert valid is True
        assert len(issues) == 0

    def test_factual_consistency_validator_detects_mismatch(self):
        """4. Inconsistent response fails validator (e.g. LLM invented 10 instead of 9)."""
        ctx = {
            "database_evidence": {
                "booking_reference": "RS-10055",
                "records": [
                    {"seat_class": "First Class", "capacity": 44, "confirmed": 32, "held": 3, "available": 9}
                ]
            }
        }
        # LLM hallucinated 15 seats
        answer = "Udarata Menike currently has 15 First Class seats available for Booking RS-10055."
        valid, issues = verify_factual_consistency(answer, ctx)
        assert valid is False
        assert any("Inconsistent seat availability" in s for s in issues)

    def test_deterministic_fallback_preserves_accuracy(self):
        """5. Deterministic fallback produces valid grounded response."""
        db_ev = {
            "train_name": "Udarata Menike",
            "train_id": "1005",
            "travel_date": "2026-09-25",
            "records": [
                {"schedule_id": 101, "train_id": "1005", "train_name": "Udarata Menike", "seat_class": "First Class", "capacity": 44, "confirmed": 32, "held": 3, "available": 9}
            ]
        }
        ctx = {
            "intent": "seat_availability_query",
            "query": "How many seats are available?",
            "database_evidence": db_ev,
            "policy_context": [{"passage_id": "POL-SEAT-001-ART-3", "citation": "[POL-SEAT-001 - Article 3]"}]
        }
        resp = generate_deterministic_response("seat_availability_query", ctx, {"train_name": "Udarata Menike"})
        assert resp.is_fallback is True
        assert "9 seats available" in resp.answer
        assert len(resp.sources) >= 1
        assert resp.card is not None
        assert resp.card.type == "seat_availability"
