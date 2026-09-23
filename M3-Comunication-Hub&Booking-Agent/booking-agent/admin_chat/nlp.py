"""
admin_chat/nlp.py
-----------------
NLP query understanding pipeline for the Admin Booking Intelligence Assistant.
"""

from __future__ import annotations

import re
from typing import Any
from .entity_extractor import extract_entities
from .intent_classifier import classify_intent
from .privacy import sanitize_admin_input
from .schemas import AdminQueryUnderstanding


COMMON_QUERY_CORRECTIONS = {
    # Common chat typos seen in railway administrator questions.
    "meny": "many",
    "tommorow": "tomorrow",
    "tomorow": "tomorrow",
    "manike": "menike",
    "availble": "available",
    "bookng": "booking",
    "cancelltion": "cancellation",
}


def normalize_query_language(text: str) -> str:
    """Correct a small, domain-safe set of frequent chat spelling mistakes."""
    normalized = text
    for misspelling, correction in COMMON_QUERY_CORRECTIONS.items():
        normalized = re.sub(rf"\b{re.escape(misspelling)}\b", correction, normalized, flags=re.IGNORECASE)
    return normalized


def process_admin_nlp(
    message: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Execute full NLP query understanding:
    1. Sanitize query and filter prompt injection.
    2. Extract railway domain entities and normalize dates.
    3. Contextual follow-up entity stitching from conversation history.
    4. Classify intent.
    """
    clean_message = normalize_query_language(sanitize_admin_input(message))
    entities = extract_entities(clean_message)

    # Contextual Follow-up Resolution:
    # If key entities (train, date) are missing in current query, inspect recent user/assistant turns
    if history:
        for turn in reversed(history):
            past_content = turn.get("content", "")
            past_entities = extract_entities(past_content)

            # Inherit booking / ticket references so follow-up questions like
            # "what is the passenger email?" still resolve to the same record.
            # Only for clearly follow-up style queries, never aggregate ones
            # ("how many bookings today"), to avoid hijacking the intent.
            followup_cue = bool(re.search(
                r"\b(email|contact|passenger|nic|name|that booking|same booking|it|its|that one)\b",
                clean_message,
                re.IGNORECASE,
            ))
            aggregate_cue = bool(re.search(
                r"\b(how many|count|number of|total|summary|today|queue|manifest)\b",
                clean_message,
                re.IGNORECASE,
            ))
            if followup_cue and not aggregate_cue:
                if "booking_reference" not in entities and "booking_reference" in past_entities:
                    entities["booking_reference"] = past_entities["booking_reference"]
                if "ticket_reference" not in entities and "ticket_reference" in past_entities:
                    entities["ticket_reference"] = past_entities["ticket_reference"]

            # Inherit train_name / train_id if not present
            if "train_name" not in entities and "train_name" in past_entities:
                entities["train_name"] = past_entities["train_name"]
            if "train_id" not in entities and "train_id" in past_entities:
                entities["train_id"] = past_entities["train_id"]

            # Inherit travel_date if not present
            if "travel_date" not in entities and "travel_date" in past_entities:
                entities["travel_date"] = past_entities["travel_date"]

            # Inherit stations if not present
            if "origin_station" not in entities and "origin_station" in past_entities:
                entities["origin_station"] = past_entities["origin_station"]
            if "destination_station" not in entities and "destination_station" in past_entities:
                entities["destination_station"] = past_entities["destination_station"]

    intent = classify_intent(clean_message, extracted_entities=entities)
    understanding = AdminQueryUnderstanding(
        intent=intent,
        confidence=0.92 if intent != "unknown_booking_query" else 0.25,
        entities=entities,
        filters={
            "count_only": bool(entities.get("is_count_request")),
            "all_trains": not bool(entities.get("train_name") or entities.get("train_id")),
            "include_passengers": intent == "booking_manifest_query",
        },
    )

    return {
        "raw_message": message,
        "clean_message": clean_message,
        "intent": intent,
        "entities": entities,
        "understanding": understanding,
    }
