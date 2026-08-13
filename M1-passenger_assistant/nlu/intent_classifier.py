"""
nlu/intent_classifier.py
Phase 1: minimal keyword-based stub so the function signature exists and
main.py can be wired against it without waiting for Phase 2.
Phase 2: replace the body with a real spaCy/LLM-function-call classifier
and add an evaluation script under tests/.
"""

from typing import Literal

Intent = Literal["schedule_query", "delay_check", "complaint", "fare_query", "unknown"]

_KEYWORDS: dict[Intent, list[str]] = {
    "delay_check": ["delay", "late", "on time", "expected"],
    "schedule_query": ["schedule", "time", "departs", "next train"],
    "fare_query": ["fare", "price", "cost", "ticket price"],
    "complaint": ["broken", "issue", "problem", "complaint", "not working"],
}


def classify_intent(message: str) -> Intent:
    lowered = message.lower()
    for intent, keywords in _KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return intent
    return "unknown"
