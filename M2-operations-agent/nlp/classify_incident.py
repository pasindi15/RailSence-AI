"""
M2 — Operations & Delay-Prediction Agent
Phase 3: Incident classification.

Two modes, chosen automatically:
    1. Rule-based keyword baseline (always available, zero API cost,
       deterministic — good for a viva demo and for evaluation).
    2. Optional LLM zero-shot classification via the Anthropic API, used
       only if ANTHROPIC_API_KEY is set in the environment. Falls back to
       the rule-based baseline on any API error so the endpoint never
       hard-fails on a missing/invalid key or network issue.

Categories match the incident_type values already present in
operations_history.csv, so the rule-based baseline can be evaluated
directly against real ground-truth labels (see evaluate_nlp.py).
"""

import os
import re
from typing import Optional

CATEGORIES = [
    "signal_fault",
    "mechanical",
    "weather",
    "track_obstruction",
    "staffing",
    "other",
]

# Keyword/phrase lists derived from real staff-style incident language
# (see data/generate_dataset.py INCIDENT_NOTE_TEMPLATES for the source style).
KEYWORDS = {
    "signal_fault": [
        "signal failure", "signal fault", "stuck on red", "interlocking",
        "manual override", "signal at",
    ],
    "mechanical": [
        "engine", "overheating", "brake", "locomotive", "mechanical fault",
        "replacement unit", "brake system",
    ],
    "weather": [
        "heavy rain", "visibility", "flooding", "flood", "speed restriction",
        "track bed",
    ],
    "track_obstruction": [
        "fallen tree", "obstruction", "livestock", "manual clearance",
        "cleared", "unscheduled stop",
    ],
    "staffing": [
        "crew", "relief crew", "staff shortage", "platform staff",
        "late arrival of", "boarding and dispatch",
    ],
}


def _rule_based_classify(text: str) -> str:
    if not text or not text.strip():
        return "none"

    text_lower = text.lower()
    scores: dict[str, int] = {}
    for category, phrases in KEYWORDS.items():
        score = sum(1 for phrase in phrases if phrase in text_lower)
        if score > 0:
            scores[category] = score

    if not scores:
        return "other"
    return max(scores, key=scores.get)


def _llm_classify(text: str) -> Optional[str]:
    """Zero-shot classification via Claude. Returns None on any failure
    so the caller falls back to the rule-based baseline."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        allowed = ", ".join(CATEGORIES)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=20,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Classify this railway incident report into exactly one of these "
                        f"categories: {allowed}. Reply with only the category name, nothing else.\n\n"
                        f"Incident report: {text}"
                    ),
                }
            ],
        )
        label = response.content[0].text.strip().lower()
        return label if label in CATEGORIES else None
    except Exception:
        return None


def classify_incident(text: str, prefer_llm: bool = False) -> dict:
    """
    Returns {"classified_type": str, "method": "rule_based" | "llm"}
    """
    if prefer_llm:
        llm_result = _llm_classify(text)
        if llm_result is not None:
            return {"classified_type": llm_result, "method": "llm"}

    return {"classified_type": _rule_based_classify(text), "method": "rule_based"}
