"""
cancellation/nlp.py
-------------------
NLP processing for passenger booking cancellation requests.

Responsibilities:
1. Rule-based & keyword classification of cancellation reasons into one of 7 standard categories:
   - duplicate_booking
   - personal_emergency
   - schedule_change
   - wrong_booking
   - service_issue
   - travel_plan_changed
   - other
2. Entity extraction:
   - booking_reference (e.g. RS-84521)
   - train_id
   - travel_date
   - stations
"""

from __future__ import annotations

import re
from typing import Any


KNOWN_STATIONS = [
    "Colombo", "Kandy", "Galle", "Matara", "Badulla",
    "Jaffna", "Anuradhapura", "Peradeniya", "Ella", "Nanu Oya"
]

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "duplicate_booking": [
        "duplicate", "twice", "double", "booked 2 times", "booked two times",
        "accidental double", "charged twice", "same ticket twice", "duplicate booking"
    ],
    "personal_emergency": [
        "emergency", "hospital", "medical", "illness", "sick", "doctor",
        "surgery", "accident", "death", "funeral", "family emergency", "health issue"
    ],
    "schedule_change": [
        "meeting", "work", "rescheduled", "office", "exam", "conference",
        "shift", "postponed at work", "business trip", "schedule change", "schedule changed"
    ],
    "wrong_booking": [
        "wrong date", "wrong station", "wrong train", "wrong time", "wrong passenger",
        "mistake in date", "incorrect date", "selected wrong", "mistake", "wrong ticket"
    ],
    "service_issue": [
        "train cancelled", "railway strike", "delay", "derailment", "breakdown",
        "service issue", "track maintenance", "bad service", "rail disruption"
    ],
    "travel_plan_changed": [
        "trip cancelled", "change of plans", "not traveling", "plans changed",
        "vacation cancelled", "holiday cancelled", "cannot make it", "changed my mind"
    ],
}


def classify_cancellation_reason(reason_text: str) -> str:
    """
    Classify free-text cancellation reason into one of the 7 supported categories.
    Defaults to 'other' if no distinctive keywords match.
    """
    if not reason_text:
        return "other"

    normalized = reason_text.lower().strip()

    # Match in order of priority (specific intent patterns first)
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", normalized):
                return category

    return "other"


def extract_cancellation_entities(text: str) -> dict[str, Any]:
    """
    Extract useful entities from user's cancellation text:
    - booking_reference: RS-XXXXX
    - train_id: PM-XXXX or similar
    - stations: recognized station names
    - travel_date: ISO date or recognizable date strings
    """
    entities: dict[str, Any] = {}

    # 1. Booking Reference (e.g. RS-84521, RS-70882)
    ref_match = re.search(r"\b(RS-[A-Za-z0-9]{4,10})\b", text, re.IGNORECASE)
    if ref_match:
        entities["booking_reference"] = ref_match.group(1).upper()

    # 2. Train ID (e.g. PM-4082, INACT-9999)
    all_codes = re.findall(r"\b([A-Za-z]{2,4}-\d{3,5})\b", text)
    for code in all_codes:
        if code.upper() != entities.get("booking_reference"):
            entities["train_id"] = code.upper()
            break

    # 3. Stations
    found_stations = [s for s in KNOWN_STATIONS if re.search(rf"\b{re.escape(s)}\b", text, re.IGNORECASE)]
    if found_stations:
        entities["stations"] = found_stations

    # 4. ISO Date
    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if date_match:
        entities["travel_date"] = date_match.group(1)

    return entities


def process_cancellation_nlp(reason_text: str, message_text: str = "") -> dict[str, Any]:
    """
    Full NLP pipeline:
    Categorizes the reason and extracts any present entities from reason or message text.
    """
    combined_text = f"{message_text} {reason_text}".strip()
    category = classify_cancellation_reason(reason_text or combined_text)
    entities = extract_cancellation_entities(combined_text)

    return {
        "intent": "cancel_booking",
        "booking_reference": entities.get("booking_reference"),
        "reason": reason_text.strip(),
        "reason_category": category,
        "extracted_entities": entities,
    }


# ---------------------------------------------------------------------------
# Administrator Rejection NLP Analyzer
# ---------------------------------------------------------------------------

ADMIN_REJECTION_KEYWORDS: dict[str, list[str]] = {
    "LATE_NOTICE_INELIGIBLE": [
        "late", "24h", "24 hours", "24 hrs", "less than 24", "under 24", "same day",
        "departure", "too late", "after departure", "after train left", "short notice",
        "notice window", "non-refundable time", "past departure"
    ],
    "UNVERIFIED_DUPLICATE": [
        "not duplicate", "single ticket", "different seat", "different train",
        "different passenger", "different date", "no duplicate found", "duplicate unverified",
        "not a double booking", "separate journey", "no record of second booking"
    ],
    "MISSING_DOCUMENTATION": [
        "certificate", "medical note", "doctor", "hospital document", "proof required",
        "missing document", "no proof", "documentation missing", "medical certificate",
        "evidence", "affidavit", "proof of illness"
    ],
    "NON_REFUNDABLE_FARE": [
        "non-refundable", "promo", "discounted fare", "special fare", "advance saver",
        "group discount", "promotional", "cannot be refunded", "special class"
    ],
    "POLICY_EXCLUSION": [
        "policy", "rule", "section", "guideline", "clause", "terms and conditions",
        "ineligible", "railway regulations", "statutory rule", "pol-ref", "pol-res"
    ],
}

FORMAL_PASSENGER_TEMPLATES: dict[str, str] = {
    "LATE_NOTICE_INELIGIBLE": (
        "We regret to inform you that your cancellation request cannot be approved. "
        "Under Sri Lanka Railways cancellation policy, reservations submitted less than 24 hours "
        "prior to scheduled departure are non-refundable."
    ),
    "UNVERIFIED_DUPLICATE": (
        "Following an audit of our central booking records, no duplicate booking was identified for your travel details. "
        "Your cancellation request cannot be authorized under duplicate booking exceptions."
    ),
    "MISSING_DOCUMENTATION": (
        "Your cancellation request cannot be processed due to missing supporting documentation "
        "(such as an official medical certificate or emergency verification). Please visit a station counter for assistance."
    ),
    "NON_REFUNDABLE_FARE": (
        "Your ticket was issued under non-refundable fare terms or special promotional conditions and is ineligible "
        "for cancellation refund under railway regulations."
    ),
    "POLICY_EXCLUSION": (
        "Your cancellation request has been evaluated against Sri Lanka Railways ticketing policies "
        "and does not meet standard eligibility requirements for refund authorization."
    ),
    "ADMINISTRATIVE_DISCRETION": (
        "Your cancellation request has been reviewed and declined by railway administration."
    ),
}


def analyze_admin_rejection_reason(
    reason_text: str,
    booking_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    NLP Analysis of the human administrator's typed rejection explanation.

    Extracts:
    1. rejection_category: Standardized classification category.
    2. policy_citations: Extracted policy codes (e.g. POL-REF-003, Section 3.2).
    3. time_references: Detected time windows (e.g. '24 hours', '48 hours').
    4. tone: Assessed tone (Formal Policy Adherence, Documentation Deficiency, etc.).
    5. polished_explanation: Professional, courteous passenger-ready explanation.
    """
    raw_text = (reason_text or "").strip()
    if not raw_text:
        raw_text = "Does not meet cancellation policy requirements."

    normalized = raw_text.lower()

    # 1. Categorization via NLP keywords
    detected_category = "ADMINISTRATIVE_DISCRETION"
    for cat, keywords in ADMIN_REJECTION_KEYWORDS.items():
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", normalized):
                detected_category = cat
                break
        if detected_category != "ADMINISTRATIVE_DISCRETION":
            break

    # 2. Extract policy citations
    policy_citations = re.findall(
        r"\b(?:POL-[A-Z0-9-]+|Section\s+\d+(?:\.\d+)?)\b",
        raw_text,
        re.IGNORECASE,
    )

    # 3. Extract time references
    time_references = re.findall(
        r"\b(?:\d+\s*(?:hours?|hrs?|days?|minutes?|mins?))\b",
        raw_text,
        re.IGNORECASE,
    )

    # 4. Assess tone
    tone_map = {
        "LATE_NOTICE_INELIGIBLE": "Timing & Notice Adherence",
        "UNVERIFIED_DUPLICATE": "Ledger Audit Verification",
        "MISSING_DOCUMENTATION": "Documentation Compliance",
        "NON_REFUNDABLE_FARE": "Fare Class Conditions",
        "POLICY_EXCLUSION": "Formal Policy Regulation",
        "ADMINISTRATIVE_DISCRETION": "Station Administrative Discretion",
    }
    tone = tone_map.get(detected_category, "Professional Administrative Review")

    # 5. Build formal passenger explanation
    base_template = FORMAL_PASSENGER_TEMPLATES.get(
        detected_category,
        FORMAL_PASSENGER_TEMPLATES["ADMINISTRATIVE_DISCRETION"],
    )
    if raw_text and raw_text not in base_template:
        polished_explanation = f"{base_template} Administrator Remarks: \"{raw_text}\""
    else:
        polished_explanation = base_template

    return {
        "raw_reason": raw_text,
        "rejection_category": detected_category,
        "category_label": detected_category.replace("_", " ").title(),
        "policy_citations": policy_citations,
        "time_references": time_references,
        "tone": tone,
        "polished_explanation": polished_explanation,
    }
