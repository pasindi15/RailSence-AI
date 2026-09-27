"""
admin_chat/rag_context.py
-------------------------
Hybrid RAG Context Builder combining structured live database evidence
with retrieved official railway policies from PolicyKnowledgeBase.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure access to cancellation/rag.py
_CURRENT_DIR = Path(__file__).resolve().parent
_BOOKING_AGENT_DIR = _CURRENT_DIR.parent
if str(_BOOKING_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOOKING_AGENT_DIR))

from cancellation.rag import PolicyKnowledgeBase

_policy_kb: PolicyKnowledgeBase | None = None


def get_policy_knowledge_base() -> PolicyKnowledgeBase:
    """Singleton getter for the railway policy knowledge base."""
    global _policy_kb
    if _policy_kb is None:
        _policy_kb = PolicyKnowledgeBase()
    return _policy_kb


def retrieve_policy_context(intent: str, query: str, top_k: int = 2) -> list[dict[str, Any]]:
    """
    Retrieve relevant policy articles using the existing RAG knowledge base.
    """
    # Live operational facts come from structured M3 retrieval. Policy RAG is
    # only relevant for cancellation/fraud policy questions or explicit policy
    # wording, avoiding irrelevant citations on seat and booking counts.
    policy_words = ("policy", "rule", "refund", "eligibility", "why", "reason")
    if intent not in ("cancellation_query", "fraud_review_query") and not any(
        word in query.lower() for word in policy_words
    ):
        return []

    kb = get_policy_knowledge_base()

    # Domain-guided search query
    if intent == "cancellation_query":
        search_term = f"cancellation refund rules {query}"
    elif intent == "fraud_review_query":
        search_term = f"security review anomaly fraud policy {query}"
    elif intent in ("seat_availability_query", "schedule_query"):
        search_term = f"seat reservation allocation inventory hold {query}"
    else:
        search_term = query

    try:
        chunks = kb.retrieve(search_term, top_k=top_k)
        results = []
        for ch in chunks:
            pid = ch.get("passage_id") or f"{ch.get('document_id', 'POL')}-ART-1"
            cit = ch.get("citation") or f"[{pid}]"
            results.append({
                "passage_id": pid,
                "citation": cit,
                "title": ch.get("document_title") or ch.get("document", "Railway Policy"),
                "section": ch.get("section", ""),
                "content": ch.get("content", ""),
            })
        return results
    except Exception as exc:
        print(f"[RAG Context] Policy retrieval note: {exc}")
        return []


def build_rag_context(
    intent: str,
    query: str,
    db_evidence: dict[str, Any],
) -> dict[str, Any]:
    """
    Assemble structured database evidence and policy citations into a unified RAG context.
    """
    policies = retrieve_policy_context(intent, query, top_k=2)

    return {
        "intent": intent,
        "query": query,
        "database_evidence": db_evidence,
        "policy_context": policies,
    }
