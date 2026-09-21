"""
admin_chat/intent_classifier.py
-------------------------------
Rule-based Intent Classifier for the Admin Booking Intelligence Assistant.
"""

from __future__ import annotations

import re


MUTATION_PATTERNS = [
    r"(?i)\b(?:approve|reject|accept|deny|adjudicate)\s+(?:booking|cancellation|case|review|fraud|ref|bkg|rs-)",
    r"(?i)\b(?:cancel|delete|remove|modify|update|change)\s+(?:booking|ticket|seat|reservation|case|review|fraud)",
    r"(?i)\b(?:create|make|issue)\s+(?:new\s+)?(?:booking|ticket|reservation|case)",
]

FRAUD_PATTERNS = [
    r"\bfraud\b", r"\bsuspicious\b", r"\brisk\s*score\b", r"\brisk\s*level\b",
    r"\bflagged\b", r"\banomaly\b", r"\bml\s*risk\b", r"\bvelocity\b",
    r"\bfr-\d+\b", r"\bhigh[\s-]risk\b"
]

CANCELLATION_PATTERNS = [
    r"\bcancellations?\b", r"\brefunds?\b", r"\bcan-\d+\b",
    r"\bcancel\s*request\b", r"\bcancellation\s*queue\b"
]

SEAT_PATTERNS = [
    r"\bseats?\s*(?:available|left|remaining|held)\b",
    r"\bavailability\b", r"\bhow\s+many\s+seats\b",
    r"\bfirst\s+class\s+seats\b", r"\bsecond\s+class\s+seats\b",
    r"\bseats?\s*are\s*being\s*held\b", r"\bwaiting\s*list\b",
    r"\bfully\s*booked\b", r"\bseat\s*inventory\b"
]

MANIFEST_PATTERNS = [
    r"\bmanifest\b", r"\bpassengers?\s*(?:booked|travelling|traveling|list)\b",
    r"\bconfirmed\s*(?:tickets?|bookings?|passengers?)\b",
    r"\bwho\s+is\s+travelling\b"
]

SCHEDULE_PATTERNS = [
    r"\bschedules?\b", r"\btrains?\s*(?:operate|running|departing|operating)\b",
    r"\bwhat\s+trains\b", r"\btrain\s+time\b", r"\btimetable\b"
]

STATISTICS_PATTERNS = [
    r"\bbooking\s*summary\b", r"\btoday(?:'s)?\s*summary\b",
    r"\btoday(?:'s)?\s*bookings?\s*count\b", r"\bhow\s+many\s+bookings?\s*today\b",
    r"\btotal\s*bookings\b", r"\bdaily\s*summary\b"
]


def classify_intent(query: str, extracted_entities: dict | None = None) -> str:
    """
    Classify administrator query into one of the designated booking intents.
    """
    if not query:
        return "unknown_booking_query"

    normalized = query.strip()
    lowered = normalized.lower()
    entities = extracted_entities or {}

    # 1. Action / Mutation detection (Read-only administrative guard)
    for pat in MUTATION_PATTERNS:
        if re.search(pat, normalized):
            return "unsupported_mutation"

    # 2. Specific Booking Reference Lookup ("What happened to BKG-...", "Find booking BKG-...")
    if entities.get("booking_reference"):
        if any(re.search(pat, lowered) for pat in FRAUD_PATTERNS):
            return "fraud_review_query"
        if any(re.search(pat, lowered) for pat in CANCELLATION_PATTERNS):
            return "cancellation_query"
        return "booking_lookup"

    # 3. Ticket Reference Lookup
    if entities.get("ticket_reference"):
        return "ticket_query"

    # 4. Summary / Aggregates
    if any(re.search(pat, lowered) for pat in STATISTICS_PATTERNS):
        return "booking_statistics"

    # 5. Fraud Review Queue
    if any(re.search(pat, lowered) for pat in FRAUD_PATTERNS):
        return "fraud_review_query"

    # 6. Cancellation Queue
    if any(re.search(pat, lowered) for pat in CANCELLATION_PATTERNS):
        return "cancellation_query"

    # 7. Seat Availability Query
    if any(re.search(pat, lowered) for pat in SEAT_PATTERNS):
        return "seat_availability_query"

    # 8. Passenger Manifest Query
    if any(re.search(pat, lowered) for pat in MANIFEST_PATTERNS):
        return "booking_manifest_query"

    # 9. Schedule Query
    if any(re.search(pat, lowered) for pat in SCHEDULE_PATTERNS):
        return "schedule_query"

    # Entity fallback heuristics
    if entities.get("train_name") or entities.get("train_id"):
        if entities.get("seat_class") or "seat" in lowered:
            return "seat_availability_query"
        if entities.get("travel_date"):
            return "schedule_query"

    if "booking" in lowered and entities.get("travel_date"):
        return "booking_manifest_query"

    return "unknown_booking_query"
