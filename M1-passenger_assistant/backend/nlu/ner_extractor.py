"""
Named Entity extraction stub for Passenger Assistant Agent.
Phase 1: simple regex/keyword based extraction for station names & times.
Phase 2+: replace with spaCy model or LLM function-calling.
"""
import re

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
TRAIN_ID_PATTERN = re.compile(r"\b[A-Z]{2}-\d{3,4}\b")
SEAT_CLASS_KEYWORDS = ["first class", "second class", "third class"]
PASSENGER_COUNT_PATTERN = re.compile(
    r"\b(\d+)\s*(passenger|passengers|people|seat|seats)\b", re.IGNORECASE
)


def extract_entities(text: str) -> dict:
    lowered_text = text.lower()
    found_stations = [
        canonical
        for canonical, aliases in STATION_ALIASES.items()
        if any(alias.lower() in lowered_text for alias in aliases)
    ]
    time_match = TIME_PATTERN.search(text)
    date_match = DATE_PATTERN.search(text)
    train_id_match = TRAIN_ID_PATTERN.search(text)
    passenger_count_match = PASSENGER_COUNT_PATTERN.search(text)
    lowered = text.lower()

    return {
        "stations": found_stations,
        "from_station": found_stations[0] if len(found_stations) >= 1 else None,
        "to_station": found_stations[1] if len(found_stations) >= 2 else None,
        "time": time_match.group(0) if time_match else None,
        "travel_date": date_match.group(0) if date_match else None,
        "train_id": train_id_match.group(0) if train_id_match else None,
        "seat_class": next((keyword.title() for keyword in SEAT_CLASS_KEYWORDS if keyword in lowered), None),
        "passenger_count": int(passenger_count_match.group(1)) if passenger_count_match else 1,
    }


if __name__ == "__main__":
    print(extract_entities("Is the 14:35 Colombo Fort to Kandy train delayed?"))
    print(extract_entities("කොළඹ කොටුවෙන් මහනුවරට දුම්රිය ගාස්තුව කීයද?"))
    print(extract_entities("கொழும்பு கோட்டையிலிருந்து கண்டிக்கு ரயில் கட்டணம் எவ்வளவு?"))
