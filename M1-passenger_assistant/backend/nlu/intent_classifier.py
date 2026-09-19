"""
Keyword-based intent classifier for Passenger Assistant Agent.

Intents:
 - train_info    : asking about a specific canonical train service
 - schedule_query : asking about train times / routes
 - fare_query      : asking about ticket price / cost
 - delay_check     : asking whether a specific train is delayed  -> routed to Hub (Operations)
 - complaint       : reporting a broken/faulty issue              -> routed to Hub (Maintenance)
 - booking_request : requesting a train booking                    -> routed to Hub (Booking)
 - train_status    : asking if a specific train is running/available -> routed to Hub (Maintenance)
 - unknown         : fallback, handled locally with a clarifying reply
"""
import re

# Same pattern ner_extractor.py uses for train_id (e.g. "PM-4082").
_TRAIN_ID_PATTERN = re.compile(r"\b[A-Z]{2,12}-\d{3,5}\b", re.IGNORECASE)

INTENT_KEYWORDS = {
    "train_status": [
        # "is train" / "is the train" were removed - as bare substrings they
        # matched almost any "What is the train fare/schedule...?" or "Is
        # the train ... delayed?" question, hijacking fare_query/
        # schedule_query/delay_check before their own keywords were ever
        # checked (train_status is the first key in this dict). The phrases
        # below are specific enough to still catch real train-status
        # questions (e.g. "Is train running?" still matches "train running")
        # without that false-positive footprint.
        "train running", "train available", "train cancelled", "train service",
        "will train", "train operating", "out of service", "under maintenance",
        "train working", "train today", "service today", "train status",
        "දුම්රිය ධාවනය", "දුම්රිය ක්‍රියාත්මකද",
        "ரயில் இயங்குகிறதா", "ரயில் நிலை",
    ],
    "delay_check": [
        "delay", "late", "on time", "on-time", "postpone",
        "ප්‍රමාද", "ප්‍රමාදයි", "ප්‍රමාදද",
        "தாமதம்", "தாமதமா",
    ],
    "cancel_booking": [
        "cancel booking", "cancel my booking", "cancel ticket", "cancel my ticket",
        "cancel reservation", "cancel my reservation", "cancellation", "cancel",
        "refund", "drop booking",
        "අවලංගු", "අවලංගු කරන්න", "ටිකට් අවලංගු",
        "ரத்து", "முன்பதிவு ரத்து", "டிக்கெட் ரத்து",
    ],
    "booking_request": [
        "book", "booking", "reserve", "reservation", "buy ticket", "purchase ticket",
        "වෙන්කරව", "වෙන් කරගන්න", "ටිකට් එක",
        "முன்பதிவு", "டிக்கெட் வாங்க", "இட ஒதுக்கீடு",
    ],
    "fare_query": [
        "fare", "price", "cost", "ticket price", "how much",
        "ගාස්තුව", "මිල", "කීයද",
        "கட்டணம்", "விலை", "எவ்வளவு",
    ],
    "schedule_query": [
        "schedule", "time", "departs", "departure", "arrival", "next train",
        "වේලාව", "වේලාසටහන", "ඊළඟ දුම්රිය",
        "நேரம்", "அட்டவணை", "அடுத்த ரயில்",
    ],
    "complaint": [
        "broken", "not working", "issue", "problem", "faulty", "damage", "complaint",
        "ගැටලුවක්", "කැඩිලා", "අබලද්ධ",
        "பிரச்சனை", "உடைந்த", "சிக்கல்",
    ],
}

# "what is" was removed - as a bare substring it matched almost any "What is
# ...?" question with no requirement that it even mention a train (e.g. "What
# is the weather in London?"), routing genuinely off-topic questions here
# instead of letting them correctly fall through to "unknown" (which the
# off-topic guardrail in compose_rag_answer() then catches).
#
# The remaining phrases here (e.g. "train details") have the exact same
# failure mode, just less obviously - "kandy colombo train details" matches
# "train details" and got promoted to train_info even though no specific
# train was named, and train_info's handler is useless without one (it just
# immediately asks for a train ID). classify_intent() below now requires an
# actual train ID pattern to be present before returning train_info via this
# list at all, rather than removing keywords one at a time as each one's
# false-positive turns up - a station-only "train details" question instead
# correctly falls through to "unknown", which has real, on-topic matches in
# schedules.md for a from/to station query like that.
TRAIN_INFO_KEYWORDS = [
    "where does", "where is", "which route", "train information",
    "train details", "active", "departs", "departure", "arrives", "arrival",
    "leave", "go",
]

# Whole-message greetings only ("hii", "vanakkam") - deliberately not a
# substring check like the keyword lists above, since "hi" as a substring
# would false-positive on real questions (e.g. a message that merely
# contains "history"). A greeting mixed with an actual question ("hi, what's
# the fare to kandy") should still fall through to normal intent
# classification instead of being swallowed here.
GREETING_WORDS = {
    "hi", "hii", "hiii", "hiiii", "hello", "helo", "hey", "heya", "yo",
    "good morning", "good afternoon", "good evening",
    "vanakkam", "ayubowan",
    "ආයුබෝවන්",
    "வணக்கம்",
}


def is_greeting(text: str) -> bool:
    cleaned = text.strip().lower().strip("!.,? ")
    return cleaned in GREETING_WORDS


def classify_intent(text: str) -> str:
    lowered = text.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in lowered:
                return intent
    if _TRAIN_ID_PATTERN.search(text) and any(kw in lowered for kw in TRAIN_INFO_KEYWORDS):
        return "train_info"
    return "unknown"


if __name__ == "__main__":
    tests = [
        "Is the 14:35 Colombo-Kandy train delayed?",
        "How much is a ticket from Colombo to Kandy?",
        "What time does the next train to Galle leave?",
        "The AC in my compartment is broken",
        "hello",
        "කොළඹ කොටුවෙන් මහනුවරට දුම්රිය ගාස්තුව කීයද?",
        "கொழும்பு கோட்டையிலிருந்து கண்டிக்கு ரயில் கட்டணம் எவ்வளவு?",
    ]
    for t in tests:
        print(t, "->", classify_intent(t))
