"""
tests/test_cancellation_rag_pgvector.py
---------------------------------------
Unit and integration tests for Supabase pgvector RAG integration and
local TF-IDF fallback in the RailSense AI Cancellation Agent.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure booking-agent is on sys.path
_TEST_DIR = Path(__file__).resolve().parent
_M3_DIR = _TEST_DIR.parent
_BOOKING_AGENT_DIR = _M3_DIR / "booking-agent"
if str(_BOOKING_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOOKING_AGENT_DIR))

from cancellation.embed_policies import parse_policy_chunks
from cancellation.rag import (
    PolicyKnowledgeBase,
    _get_embedding_model,
    _search_supabase_pgvector,
    retrieve_relevant_policies,
)


class TestCancellationRAGPgVector:
    """Test suite for pgvector policy retrieval and fallback mechanics."""

    def test_parse_policy_chunks(self):
        """Verify markdown policy parsing extracts valid citations and document IDs."""
        chunks = parse_policy_chunks()
        assert len(chunks) >= 10, "Expected at least 10 policy chunks across 5 markdown documents"

        # Check fields
        for chunk in chunks:
            assert "document" in chunk
            assert "document_id" in chunk
            assert "section" in chunk
            assert "citation" in chunk
            assert "content" in chunk
            assert chunk["citation"].startswith("[") and chunk["citation"].endswith("]")

    def test_query_embedding_dimension(self):
        """Verify SentenceTransformer model produces 384-dimensional dense vectors."""
        model = _get_embedding_model()
        vec = model.encode("I need to cancel my booking", normalize_embeddings=True)
        assert len(vec) == 384, f"Expected 384 dimensions, got {len(vec)}"

    def test_local_tfidf_fallback_in_test_environment(self):
        """Verify that in test mode, retrieval safely uses local TF-IDF with citations."""
        kb = PolicyKnowledgeBase()
        results = kb.retrieve("accidental double booking duplicate reservation", top_k=3)

        assert len(results) <= 3
        assert len(results) > 0
        assert results[0]["retrieval_method"] == "local_tfidf"
        assert "citation" in results[0]
        assert "similarity_score" in results[0]

        # Top result for duplicate booking should be related to duplicate policy or refund
        citations_text = " ".join(r["citation"] for r in results)
        assert "POL-REF-003" in citations_text or "POL-RES-005" in citations_text

    def test_empty_query_returns_empty_list(self):
        """Verify that blank queries gracefully return empty results."""
        kb = PolicyKnowledgeBase()
        assert kb.retrieve("") == []
        assert kb.retrieve("   ") == []

    @patch("cancellation.rag._search_supabase_pgvector")
    def test_supabase_pgvector_takes_precedence_when_available(self, mock_search):
        """Verify that when pgvector returns results, they take precedence over local TF-IDF."""
        mock_search.return_value = [
            {
                "document": "refund_policy.md",
                "document_id": "POL-REF-003",
                "section": "Article 2: Special Condition Exceptions",
                "citation": "[POL-REF-003 - Article 2: Special Condition Exceptions]",
                "content": "Duplicate Bookings: 100% full refund.",
                "similarity_score": 0.9124,
                "retrieval_method": "supabase_pgvector",
            }
        ]

        kb = PolicyKnowledgeBase()
        results = kb.retrieve("booked twice by accident", top_k=1)

        assert len(results) == 1
        assert results[0]["retrieval_method"] == "supabase_pgvector"
        assert results[0]["similarity_score"] == 0.9124
        assert results[0]["citation"] == "[POL-REF-003 - Article 2: Special Condition Exceptions]"
        mock_search.assert_called_once()

    @patch("cancellation.rag.engine.connect")
    def test_pgvector_db_error_falls_back_seamlessly(self, mock_connect):
        """Verify that if database connection fails, the system falls back to local TF-IDF without crashing."""
        mock_connect.side_effect = RuntimeError("Simulated database timeout")

        kb = PolicyKnowledgeBase()
        # Even with DB error, retrieve must succeed via fallback
        results = kb.retrieve("medical emergency hospital cancellation", top_k=2)

        assert len(results) > 0
        assert results[0]["retrieval_method"] == "local_tfidf"
        assert "POL-REF-003" in results[0]["citation"] or "POL-BOOK-001" in results[0]["citation"]

    def test_public_retrieve_relevant_policies_interface(self):
        """Verify module-level function retrieve_relevant_policies functions identically."""
        results = retrieve_relevant_policies("train cancellation refund eligibility", top_k=2)
        assert len(results) == 2
        assert all("citation" in r and "content" in r for r in results)
