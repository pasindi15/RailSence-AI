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

try:
    import google.generativeai as genai
except ImportError:  # Gemini is optional; alias-based extraction still works offline.
    genai = None
from dotenv import load_dotenv

# Anchor to backend/.env - see main.py for why load_dotenv() with no path is unsafe.
load_dotenv(Path(__file__).parent.parent / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
_llm_model = None
if GEMINI_API_KEY and genai is not None:
    genai.configure(api_key=GEMINI_API_KEY)
    _llm_model = genai.GenerativeModel("gemini-flash-latest")

# Extend this dict as you confirm real station names with your dataset.
# Each canonical (English) name maps to its English/Sinhala/Tamil aliases.
STATION_ALIASES = {
    "Colombo Fort": ["colombo fort", "කොළඹ කොටුව", "கொழும்பு கோட்டை"],
    "Kandy": ["kandy", "මහනුවර", "கண்டி"],
    "Galle": ["galle", "ගාල්ල", "காலி"],
    "Jaffna": ["jaffna", "යාපනය", "யாழ்ப்பாணம்"],
    "Anuradhapura": ["anuradhapura", "අනුරාධපුරය", "அனுராதபுரம்"],
    "Matara": ["matara", "මාතර", "மாத்தறை"],
    "Badulla": ["badulla", "බදුල්ල", "பதுளை"],
}

TIME_PATTERN = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d\b")
DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
TRAIN_ID_PATTERN = re.compile(r"\b[A-Z]{2,12}-\d{3,5}\b", re.IGNORECASE)
BOOKING_REF_PATTERN = re.compile(r"\b(RS-[A-Za-z0-9]{4,10})\b", re.IGNORECASE)
SEAT_CLASS_KEYWORDS = ["first class", "second class", "third class"]
PASSENGER_COUNT_PATTERN = re.compile(
    r"\b(\d+)\s*(passenger|passengers|people|seat|seats)\b", re.IGNORECASE
)

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}


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


def extract_entities(text: str) -> dict:
    lowered_text = text.lower()
    found_stations = [
        canonical
        for canonical, aliases in STATION_ALIASES.items()
        if any(alias.lower() in lowered_text for alias in aliases)
    ]
    if not found_stations:
        found_stations = _llm_extract_stations(text)

    time_match = TIME_PATTERN.search(text)
    date_match = DATE_PATTERN.search(text)
    train_id_match = TRAIN_ID_PATTERN.search(text)
    booking_ref_match = BOOKING_REF_PATTERN.search(text)
    passenger_count_match = PASSENGER_COUNT_PATTERN.search(text)
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
        "from_station": found_stations[0] if len(found_stations) >= 1 else None,
        "to_station": found_stations[1] if len(found_stations) >= 2 else None,
        "time": time_match.group(0) if time_match else None,
        "travel_date": travel_date,
        "train_id": train_id_match.group(0) if train_id_match else None,
        "booking_reference": booking_ref,
        "reason": reason,
        "seat_class": next((keyword.title() for keyword in SEAT_CLASS_KEYWORDS if keyword in lowered), None),
        "passenger_count": int(passenger_count_match.group(1)) if passenger_count_match else 1,
    }


if __name__ == "__main__":
    print(extract_entities("Is the 14:35 Colombo Fort to Kandy train delayed?"))
    print(extract_entities("කොළඹ කොටුවෙන් මහනුවරට දුම්රිය ගාස්තුව කීයද?"))
    print(extract_entities("கொழும்பு கோட்டையிலிருந்து கண்டிக்கு ரயில் கட்டணம் எவ்வளவு?"))
