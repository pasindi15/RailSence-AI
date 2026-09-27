"""
admin_chat/entity_extractor.py
------------------------------
Deterministic Named Entity Extractor for railway admin queries.
"""

from __future__ import annotations

import re
from difflib import get_close_matches
from typing import Any
from .date_parser import parse_query_date


KNOWN_TRAIN_NAMES = [
    "Udarata Menike", "Podi Menike", "Denuwara Menike", "Yal Devi",
    "Uttara Devi", "Rajarata Rejini", "Ruhunu Kumari", "Samudra Devi",
    "Intercity Express", "Galu Kumari", "Tikiri Menike", "Senkadagala Menike",
    "Night Mail Express", "Sagarika", "Badulla Express"
]

KNOWN_STATIONS = [
    "Colombo Fort", "Colombo", "Kandy", "Galle", "Matara", "Badulla",
    "Jaffna", "Anuradhapura", "Peradeniya", "Ella", "Nanu Oya", "Beliatta",
    "Polgahawela", "Kurunegala", "Vavuniya"
]


def extract_entities(query: str) -> dict[str, Any]:
    """
    Extract structured railway domain entities from admin query.
    """
    entities: dict[str, Any] = {}
    normalized = query.strip()
    lowered = normalized.lower()

    # 1. Travel Date
    parsed_date, iso_date = parse_query_date(query)
    if iso_date:
        entities["travel_date"] = iso_date

    # 2. Booking Reference (also supports compact BK12345 references)
    bkg_match = re.search(r"\b((?:RS|BKG|BK|BOOKING)-?[A-Za-z0-9]{3,12})\b", normalized, re.IGNORECASE)
    if bkg_match:
        ref_raw = bkg_match.group(1).upper()
        # Canonicalize to standard RS- or retain BKG- for matching
        entities["booking_reference"] = ref_raw

    # 3. Case Reference (e.g. FR-10221, CAN-104)
    case_match = re.search(r"\b((?:FR|CAN)-?[0-9]{3,8})\b", normalized, re.IGNORECASE)
    if case_match:
        entities["case_reference"] = case_match.group(1).upper()

    # 4. Ticket Reference / Token
    tkt_match = re.search(r"\b(TKT-[A-Za-z0-9]{4,16})\b", normalized, re.IGNORECASE)
    if tkt_match:
        entities["ticket_reference"] = tkt_match.group(1).upper()

    # 5. Train Name
    for name in KNOWN_TRAIN_NAMES:
        if re.search(rf"\b{re.escape(name.lower())}\b", lowered):
            entities["train_name"] = name
            break
    if "train_name" not in entities:
        words = re.findall(r"[a-z]+", lowered)
        candidates = []
        for name in KNOWN_TRAIN_NAMES:
            name_words = name.lower().split()
            score = sum(1 for word in words if get_close_matches(word, name_words, n=1, cutoff=0.78))
            if score:
                candidates.append((score, name))
        candidates.sort(reverse=True)
        if candidates and (len(candidates) == 1 or candidates[0][0] > candidates[1][0]):
            entities["train_name"] = candidates[0][1]

    # 6. Train Number / ID (e.g. "train 1005", "1005", "PM-4082")
    tid_match = re.search(r"\b(?:train\s*(?:#|no\.?|id)?\s*)?([A-Za-z]{2}-\d{3,5})\b", normalized, re.IGNORECASE)
    if tid_match and not entities.get("booking_reference") and not entities.get("case_reference"):
        entities["train_id"] = tid_match.group(1).upper()
    else:
        num_match = re.search(r"\b(?:train\s*(?:#|no\.?|id)?\s*)(\d{4})\b", normalized, re.IGNORECASE)
        if num_match:
            entities["train_id"] = num_match.group(1)
        elif not entities.get("train_id") and not entities.get("booking_reference"):
            lone_num = re.search(r"\b(1005|1006|1015|1016|4082|6011)\b", normalized)
            if lone_num:
                entities["train_id"] = lone_num.group(1)

    # 7. Seat Class
    if re.search(r"\b(1st|first)\s*(?:class)?\b", lowered):
        entities["seat_class"] = "First Class"
    elif re.search(r"\b(2nd|second)\s*(?:class)?\b", lowered):
        entities["seat_class"] = "Second Class"
    elif re.search(r"\b(3rd|third)\s*(?:class)?\b", lowered):
        entities["seat_class"] = "Third Class"

    # 8. Stations (Origin / Destination)
    route_match = re.search(r"\b(?:between|from|departing)\s+([a-zA-Z\s]+?)\s+(?:and|to|for|towards)\s+([a-zA-Z\s]+?)(?:\s+(?:on|tomorrow|today|\?|$))", normalized, re.IGNORECASE)
    if not route_match:
        route_match = re.search(r"\b([a-zA-Z][a-zA-Z\s]+?)\s*(?:->|→)\s*([a-zA-Z][a-zA-Z\s]+?)(?:\s+(?:on|tomorrow|today)|\?|$)", normalized, re.IGNORECASE)
    if not route_match:
        route_match = re.search(r"\b([a-zA-Z][a-zA-Z\s]+?)\s+from\s+([a-zA-Z][a-zA-Z\s]+?)(?:\s+(?:on|tomorrow|today)|\?|$)", normalized, re.IGNORECASE)
    if route_match:
        cand_from = route_match.group(1).strip()
        cand_to = route_match.group(2).strip()
        for s in KNOWN_STATIONS:
            if s.lower() in cand_from.lower():
                entities["origin_station"] = s
            if s.lower() in cand_to.lower():
                entities["destination_station"] = s
    else:
        found_stations = []
        for s in KNOWN_STATIONS:
            if re.search(rf"\b{re.escape(s.lower())}\b", lowered):
                found_stations.append(s)
        if len(found_stations) >= 2:
            entities["origin_station"] = found_stations[0]
            entities["destination_station"] = found_stations[1]
        elif len(found_stations) == 1:
            entities["station"] = found_stations[0]

    # 9. Risk Level (HIGH, MEDIUM, LOW)
    if re.search(r"\bhigh(?:\s*-?\s*risk)?\b", lowered):
        entities["risk_level"] = "HIGH"
    elif re.search(r"\bmedium(?:\s*-?\s*risk)?\b", lowered):
        entities["risk_level"] = "MEDIUM"
    elif re.search(r"\blow(?:\s*-?\s*risk)?\b", lowered):
        entities["risk_level"] = "LOW"

    # 10. Review / Cancellation Status
    if re.search(r"\b(pending|waiting)\b", lowered):
        entities["review_status"] = "PENDING"
    elif re.search(r"\bapproved\b", lowered):
        entities["review_status"] = "APPROVED"
    elif re.search(r"\brejected\b", lowered):
        entities["review_status"] = "REJECTED"

    # 11. Count / Aggregation request
    if re.search(r"\b(how\s+many|count|number\s+of|total)\b", lowered):
        entities["is_count_request"] = True

    # 12. Thresholds (e.g., "less than 10 seats", "< 10")
    thresh_match = re.search(r"\b(fewer|less)\s+than\s+(\d+)\s+seats?\b", lowered)
    if thresh_match:
        entities["seat_threshold_op"] = "<"
        entities["seat_threshold_val"] = int(thresh_match.group(2))

    return entities
