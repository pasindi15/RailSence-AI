"""
admin_chat/nlp.py
-----------------
NLP query understanding pipeline for the Admin Booking Intelligence Assistant.
"""

from __future__ import annotations

from typing import Any
from .entity_extractor import extract_entities
from .intent_classifier import classify_intent
from .privacy import sanitize_admin_input


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
    clean_message = sanitize_admin_input(message)
    entities = extract_entities(clean_message)

    # Contextual Follow-up Resolution:
    # If key entities (train, date) are missing in current query, inspect recent user/assistant turns
    if history:
        for turn in reversed(history):
            past_content = turn.get("content", "")
            past_entities = extract_entities(past_content)

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

    return {
        "raw_message": message,
        "clean_message": clean_message,
        "intent": intent,
        "entities": entities,
    }
