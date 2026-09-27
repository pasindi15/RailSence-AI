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
    r"\bfr-\d+\b", r"\bhigh[\s-]risk\b",
    r"\bsuspicious\s+(?:booking|reservation|pattern)s?\b",
    r"\bflagged\s+(?:booking|reservation)s?\b"
]

CANCELLATION_PATTERNS = [
    r"\bcancellations?\b", r"\brefunds?\b", r"\bcan-\d+\b",
    r"\bcancel\s*request\b", r"\bcancellation\s*queue\b",
    r"\bneed\s+(?:my\s+)?attention\b.*\bcancel",
    r"\bwaiting\s+for\s+(?:human\s+)?review\b.*\bcancel"
]

SEAT_PATTERNS = [
    r"\bseats?\s*(?:available|left|remaining|held)\b",
    r"\b(?:available|open|free|vacant|remaining)\s+seats?\b",
    r"\bavailability\b", r"\bhow\s+many\s+seats\b",
    r"\bfirst\s+class\s+seats\b", r"\bsecond\s+class\s+seats\b",
    r"\bseats?\s*are\s*being\s*held\b", r"\bwaiting\s*list\b",
    r"\bfully\s*booked\b", r"\bsold\s*out\b", r"\bseat\s*inventory\b",
    r"\b(?:room|space|capacity)\s+(?:left|remaining|available)\b",
    r"\b(?:getting\s+close\s+to|near)\s+capacity\b",
    r"\bhow\s+busy\b", r"\bhow\s+much\s+space\b",
    r"\bhow\s+much\s+capacity\b", r"\benough\s+room\b",
    r"\btrains?\b.*\bseats?\b"
]

MANIFEST_PATTERNS = [
    r"\bmanifest\b", r"\bpassengers?\s*(?:booked|travelling|traveling|list)\b",
    r"\bconfirmed\s*(?:tickets?|bookings?|passengers?)\b",
    r"\bwho\s+is\s+travelling\b", r"\bwho\s+is\s+traveling\b",
    r"\bpassenger\s+list\b", r"\bwho\s+booked\b"
]

SCHEDULE_PATTERNS = [
    r"\bschedules?\b", r"\btrains?\s*(?:operate|running|departing|operating)\b",
    r"\bwhat\s+trains\b", r"\btrain\s+time\b", r"\btimetable\b",
    r"\bwhen\s+(?:does|is)\b.*\b(?:leave|depart|arrive|run|operate)\b",
    r"\bdeparture\s+time\b", r"\barrival\s+time\b"
]

STATISTICS_PATTERNS = [
    r"\bbooking\s*summary\b", r"\btoday(?:'s)?\s*summary\b",
    r"\btoday(?:'s)?\s*bookings?\s*count\b", r"\bhow\s+many\s+bookings?\s*today\b",
    r"\bhow\s+many\s+bookings?\s+(?:do\s+we\s+have|are\s+there)\b.*\b(today|tomorrow)\b",
    r"\btotal\s*bookings?\b", r"\bbooking\s+totals?\b", r"\bbookings?\s+today\b",
    r"\bdaily\s*summary\b"
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

    # Capacity wording and "can I still book" are availability questions,
    # even when they do not contain the literal word "seats".
    if (
        (entities.get("travel_date") or entities.get("train_name") or entities.get("train_id"))
        and (
            re.search(r"\b(?:full|room|capacity|book)\b", lowered)
            or re.search(r"\bcan\s+i\s+still\s+book\b", lowered)
        )
    ):
        return "seat_availability_query"

    # 9. Schedule Query
    if any(re.search(pat, lowered) for pat in SCHEDULE_PATTERNS):
        return "schedule_query"

    # Broad availability questions can omit the word "available" entirely.
    if any(re.search(pat, lowered) for pat in (r"\bopen\s+seats?\b", r"\bfree\s+seats?\b", r"\bsold\s*out\b")):
        return "seat_availability_query"

    # A dated train question asking for booking totals is a manifest/count
    # query, even when it does not use the word "manifest".
    if (
        entities.get("travel_date")
        and "booking" in lowered
        and re.search(r"\b(how\s+many|count|number\s+of|total|have)\b", lowered)
    ):
        return "booking_manifest_query"

    # Entity fallback heuristics
    if entities.get("train_name") or entities.get("train_id"):
        if entities.get("seat_class") or "seat" in lowered:
            return "seat_availability_query"
        if entities.get("travel_date"):
            return "schedule_query"

    if "booking" in lowered and entities.get("travel_date"):
        return "booking_manifest_query"

    return "unknown_booking_query"
