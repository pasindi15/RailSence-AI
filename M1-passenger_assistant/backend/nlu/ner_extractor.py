"""
Named Entity extraction for Passenger Assistant Agent.
Phase 1: simple regex/keyword based extraction for station names & times.
Phase 2: when the regex/alias lookup finds no station, fall back to Gemini
so misspellings, nicknames, or phrasing outside STATION_ALIASES still resolve
to a known station instead of silently returning nothing.
"""
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from llm_client import build_model

# Anchor to backend/.env - see main.py for why load_dotenv() with no path is unsafe.
load_dotenv(Path(__file__).parent.parent / ".env")

# Optional (OpenRouter); alias-based extraction still works offline without it.
_llm_model = build_model()

# Extend this dict as you confirm real station names with your dataset.
# Each canonical (English) name maps to its English/Sinhala/Tamil aliases.
STATION_ALIASES = {
    # Bare "colombo" (no "fort") is how passengers actually phrase it most of
    # the time (e.g. "colombo to badulla") - without it, extraction found
    # only the destination station, the RAG retrieval query fell back to a
    # single weak "badulla"-only search, and multiple unrelated routes came
    # back mixed together instead of just Colombo Fort - Badulla.
    # The Sinhala/Tamil full names stay first: _station_display() in main.py uses
    # the first script-matching alias as the localized display name. The bare
    # "කොළඹ"/"கொழும்பு" are the same everyday shorthand as bare "colombo" - without
    # them "කොළඹ ඉඳන් මහනුවරට ..." found only Kandy, so a route fare answer was
    # built from a one-station query instead of Colombo Fort - Kandy.
    "Colombo Fort": ["colombo fort", "colombo", "කොළඹ කොටුව", "கொழும்பு கோட்டை", "කොළඹ", "கொழும்பு", "கொழும்ப"],
    "Kandy": ["kandy", "මහනුවර", "கண்டி"],
    "Galle": ["galle", "ගාල්ල", "காலி"],
    "Jaffna": ["jaffna", "යාපනය", "யாழ்ப்பாணம்", "யாழ்ப்பாண"],
    "Anuradhapura": ["anuradhapura", "අනුරාධපුරය", "அனுராதபுரம்", "அனுராதபுர"],
    "Matara": ["matara", "මාතර", "மாத்தறை"],
    "Badulla": ["badulla", "බදුල්ල", "பதுளை"],
}

# Maps common train name aliases to M4 canonical T-IDs.
# Ordered longest-first so "intercity express" wins over bare "intercity".
_TRAIN_NAME_TO_ID: list[tuple[str, str]] = [
    ("udarata menike",   "T-001"),
    ("intercity express","T-002"),
    ("yal devi",         "T-003"),
    ("ruhunu kumari",    "T-004"),
    ("podi menike",      "T-005"),
    ("galu kumari",      "T-006"),
    ("night mail",       "T-007"),
    ("denuwara menike",  "T-008"),
    # shorter aliases after full names
    ("udarata",          "T-001"),
    ("intercity",        "T-002"),
    ("yal",              "T-003"),
    ("ruhunu",           "T-004"),
    ("podi",             "T-005"),
    ("galu",             "T-006"),
    ("denuwara",         "T-008"),
]


def _extract_train_name_id(text: str) -> str | None:
    """Return a T-xxx ID if any known train name appears in the text."""
    lowered = text.lower()
    for alias, tid in _TRAIN_NAME_TO_ID:
        if alias in lowered:
            return tid
    return None


TIME_PATTERN = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d\b")
DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
TRAIN_ID_PATTERN = re.compile(r"\b[A-Z]{2,12}-\d{3,5}\b", re.IGNORECASE)
# The canonical registry holds two id conventions: prefixed ids seeded from
# operations history (PM-8056, IC-8746) and bare Sri Lanka Railways service
# numbers (4085, 50, 1005) - the latter are what the daily train board shows,
# so "Is 4085 delayed?" has to resolve. A bare number is ambiguous, so it is
# only read as a train id when a train-ish word sits next to it, and times,
# ISO dates and passenger counts are excluded by the callers below.
BARE_TRAIN_NUMBER_PATTERN = re.compile(
    r"(?:\b(?:train|service|express|no\.?|number|#)\s*#?\s*(\d{1,4})\b"
    r"|\b(\d{1,4})\s*(?=(?:train|service|express)\b)"
    r"|(?:\bis\s+(\d{1,4})\b)"
    r"|(?:\bof\s+(\d{1,4})\b))",
    re.IGNORECASE,
)


def _extract_bare_train_number(text: str) -> str | None:
    """Return a standalone SLR service number, or None when nothing safe matches."""
    # Blank out times (05:45) and ISO dates so their digits can never be read
    # as a service number, then look for a train-qualified bare number.
    masked = TIME_PATTERN.sub(" ", text)
    masked = DATE_PATTERN.sub(" ", masked)
    match = BARE_TRAIN_NUMBER_PATTERN.search(masked)
    if not match:
        return None
    number = next((g for g in match.groups() if g), None)
    return number or None
BOOKING_REF_PATTERN = re.compile(r"\b(RS-[A-Za-z0-9]{4,10})\b", re.IGNORECASE)
SEAT_CLASS_KEYWORDS = ["first class", "second class", "third class"]
# Separate from SEAT_CLASS_KEYWORDS above - that field's exact "First/Second/
# Third Class" format is part of the booking_request payload contract sent to
# the Booking Agent (M3) and must not change. This is only for fare_query:
# filtering fares.md results down to the class the passenger actually asked
# about, so it needs looser phrasing ("1st"/"AC"/"reserved" on their own) and
# can carry both a tier and a subtype together (e.g. "1st class AC").
#
# Normalised to the spelled-out word ("first"/"second"/"third") because that is
# how the booking system names its classes ("First Class"/"Second Class", the
# labels in fares.md); "1st"/"2nd"/"3rd" would never match those labels.
_FARE_ORDINAL_MAP = {
    "1st": "first", "first": "first",
    "2nd": "second", "second": "second",
    "3rd": "third", "third": "third",
}
_FARE_ORDINAL_PATTERN = re.compile(r"\b(1st|first|2nd|second|3rd|third)\b", re.IGNORECASE)
# "unreserved" before "reserved" is just readability - \b on both sides of
# each alternative already stops "reserved" from matching inside
# "unreserved" (no word boundary between the "un" and "reserved" in it).
_FARE_SUBTYPE_PATTERN = re.compile(
    r"\b(unreserved|reserved|observation saloon|ac)\b", re.IGNORECASE
)
# "2 person"/"2 persons" were previously missing from the noun alternation, so
# a query like "colombo to kandy 2 person" silently fell through as if no
# count were given at all. "for 2" is a second, reversed phrasing (count
# after the noun-less "for") that needs its own pattern since the number
# comes second, not first.
PASSENGER_COUNT_PATTERN = re.compile(
    r"\b(\d+)\s*(passenger|passengers|person|persons|people|seat|seats)\b", re.IGNORECASE
)
PASSENGER_COUNT_FOR_PATTERN = re.compile(
    r"\bfor\s+(\d+)\s*(?:passenger|passengers|person|persons|people)?\b", re.IGNORECASE
)

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}


# --- Which station is the origin and which the destination? ------------------
# The station list is in dictionary order, so "first station = FROM" was wrong
# whenever only the destination was named ("a ticket to Kandy" gave FROM=Kandy).
# Roles now come from generic direction markers around each mention - nothing is
# specific to any station:
#   English : "from X" / "to|towards|into|for X"
#   Sinhala : X + ෙන්/ින්  or  "X ඉඳන්|සිට"  -> origin ;  X + ට  or  "X දක්වා|වෙත" -> destination
#   Tamil   : X + (ய)ிலிருந்து / இருந்து       -> origin ;  X + க்கு/ற்கு/த்துக்கு / "X வரை" -> destination
# A station with no marker takes the opposite role of a marked one ("Colombo to
# Kandy"); with nothing marked and two stations, spoken order decides. A single
# station with no marker stays unassigned - the origin is never guessed.
_ORIGIN_AFTER = re.compile(r"^(?:ෙන්|ින්|ගෙන්|\s*(?:ඉඳන්|ඉදන්|සිට|පටන්|වෙතින්)|ய?ிலிருந்து|\s*இலிருந்து|\s*இருந்து)")
_DEST_AFTER = re.compile(r"^(?:ට|\s*(?:දක්වා|වෙත)|க்கு|ற்கு|த்துக்கு|\s*வரை)")
_ORIGIN_BEFORE = re.compile(r"\bfrom\s+(?:the\s+)?$")
_DEST_BEFORE = re.compile(r"\b(?:to|towards|into|for|reach)\s+(?:the\s+)?$")


def _locate_station(lowered: str, canonical: str):
    """(start, end) of the earliest, longest alias of `canonical` in the text."""
    best = None
    for alias in STATION_ALIASES[canonical]:
        alias = alias.lower()
        idx = lowered.find(alias)
        if idx >= 0 and (best is None or (idx, -len(alias)) < (best[0], -(best[1] - best[0]))):
            best = (idx, idx + len(alias))
    return best


def resolve_route_roles(text: str, stations: list[str]) -> tuple[str | None, str | None]:
    """(origin, destination) among `stations`; either may be None."""
    lowered = text.lower()
    located = []
    for name in stations:
        span = _locate_station(lowered, name)
        if not span:
            continue
        before, after = lowered[:span[0]], lowered[span[1]:]
        if _ORIGIN_AFTER.match(after) or _ORIGIN_BEFORE.search(before):
            role = "origin"
        elif _DEST_AFTER.match(after) or _DEST_BEFORE.search(before):
            role = "dest"
        else:
            role = None
        located.append((span[0], name, role))
    located.sort()
    origin = next((n for _, n, r in located if r == "origin"), None)
    dest = next((n for _, n, r in located if r == "dest" and n != origin), None)
    unmarked = [n for _, n, r in located if r is None and n not in (origin, dest)]
    if origin is None and dest is None and len(located) >= 2:
        origin, dest = located[0][1], located[1][1]
    elif origin is None and dest is not None and unmarked:
        origin = unmarked[0]
    elif dest is None and origin is not None and unmarked:
        dest = unmarked[0]
    return origin, dest


def _llm_extract_stations(text: str) -> list[str]:
    """Ask Gemini to match station names outside the alias list (nicknames,
    misspellings, other phrasing). Returns [] if the LLM is unavailable, the
    call fails, or nothing in the response matches a known station."""
    if not _llm_model:
        return []

    known = ", ".join(STATION_ALIASES.keys())
    prompt = (
        "You extract Sri Lanka Railways station names from a passenger's message. "
        f"Known stations: {known}.\n"
        "The message may be in English, Sinhala, or Tamil, and may name a station "
        "by nickname or misspelling. Return ONLY a JSON array (no markdown fences) "
        "of station names from the known list that are mentioned, in the order they "
        "appear (departure first, then destination). If none match, return [].\n\n"
        f"Message: {text}"
    )
    try:
        response = _llm_model.generate_content(prompt)
        match = re.search(r"\[.*\]", response.text, re.DOTALL)
        if not match:
            return []
        stations = json.loads(match.group(0))
        known_set = set(STATION_ALIASES.keys())
        return [s for s in stations if s in known_set]
    except Exception as e:
        print(f"LLM station extraction failed: {e}")
        return []


def _extract_fare_class_keywords(text: str) -> list[str]:
    """Extract the fare class the passenger asked about, e.g. "1st class AC"
    -> ["1st", "ac"], "2nd class reserved" -> ["2nd", "reserved"], bare "AC"
    -> ["ac"]. Returns [] when no class is mentioned at all, so fare_query
    keeps showing every class for the route (the existing default)."""
    lowered = text.lower()
    keywords = []
    ordinal_match = _FARE_ORDINAL_PATTERN.search(lowered)
    if ordinal_match:
        keywords.append(_FARE_ORDINAL_MAP[ordinal_match.group(1).lower()])
    subtype_match = _FARE_SUBTYPE_PATTERN.search(lowered)
    if subtype_match:
        keywords.append(subtype_match.group(1).lower())
    return keywords


def extract_entities(text: str) -> dict:
    lowered_text = text.lower()
    found_stations = [
        canonical
        for canonical, aliases in STATION_ALIASES.items()
        if any(alias.lower() in lowered_text for alias in aliases)
    ]
    if not found_stations:
        found_stations = _llm_extract_stations(text)

    route_origin, route_destination = resolve_route_roles(text, found_stations)

    time_match = TIME_PATTERN.search(text)
    date_match = DATE_PATTERN.search(text)
    train_id_match = TRAIN_ID_PATTERN.search(text)
    bare_train_number = None if train_id_match else _extract_bare_train_number(text)
    name_based_train_id = None if (train_id_match or bare_train_number) else _extract_train_name_id(text)
    booking_ref_match = BOOKING_REF_PATTERN.search(text)
    passenger_count_match = PASSENGER_COUNT_PATTERN.search(text) or PASSENGER_COUNT_FOR_PATTERN.search(text)
    lowered = text.lower()

    # Determine travel date: ISO format first, then conversational formats
    travel_date = date_match.group(0) if date_match else None
    if not travel_date:
        day_month = re.search(
            r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b",
            lowered
        )
        month_day = re.search(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})(?:st|nd|rd|th)?\b",
            lowered
        )
        if day_month:
            d = int(day_month.group(1))
            m = MONTH_MAP.get(day_month.group(2), 1)
            try:
                travel_date = date(2026, m, d).isoformat()
            except ValueError:
                pass
        elif month_day:
            m = MONTH_MAP.get(month_day.group(1), 1)
            d = int(month_day.group(2))
            try:
                travel_date = date(2026, m, d).isoformat()
            except ValueError:
                pass
        elif "tomorrow" in lowered:
            travel_date = (date.today() + timedelta(days=1)).isoformat()
        elif "today" in lowered:
            travel_date = date.today().isoformat()

    # Extract cancellation reason if applicable
    reason = None
    booking_ref = booking_ref_match.group(1).upper() if booking_ref_match else None
    if booking_ref:
        reason_match = re.search(r"\b(?:because|due to|as|reason:)\s+(.+)$", text, re.IGNORECASE)
        if reason_match:
            reason = reason_match.group(1).strip()
        else:
            cleaned = re.sub(
                r"^(?:please\s+)?(?:cancel\s+(?:my\s+)?(?:booking|ticket|reservation)?(?:\s+RS-[A-Za-z0-9]{4,10})?)\s*",
                "",
                text,
                flags=re.IGNORECASE,
            ).strip()
            reason = cleaned if cleaned else text

    return {
        "stations": found_stations,
        "from_station": route_origin,
        "to_station": route_destination,
        "time": time_match.group(0) if time_match else None,
        "travel_date": travel_date,
        "train_id": train_id_match.group(0) if train_id_match else (bare_train_number or name_based_train_id),
        "booking_reference": booking_ref,
        "reason": reason,
        "seat_class": next((keyword.title() for keyword in SEAT_CLASS_KEYWORDS if keyword in lowered), None),
        "fare_class_keywords": _extract_fare_class_keywords(text) or None,
        # None (not 1) when no count is mentioned - the caller decides how to
        # handle "unspecified" rather than this silently guessing a solo
        # passenger for what might be a group fare question.
        "passenger_count": int(passenger_count_match.group(1)) if passenger_count_match else None,
    }


if __name__ == "__main__":
    print(extract_entities("Is the 14:35 Colombo Fort to Kandy train delayed?"))
    print(extract_entities("කොළඹ කොටුවෙන් මහනුවරට දුම්රිය ගාස්තුව කීයද?"))
    print(extract_entities("கொழும்பு கோட்டையிலிருந்து கண்டிக்கு ரயில் கட்டணம் எவ்வளவு?"))
