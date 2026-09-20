"""
Keyword-based intent classifier for Passenger Assistant Agent.

Intents:
 - train_info    : asking about a specific canonical train service
 - schedule_query : asking about train times / routes
 - fare_query      : asking about ticket price / cost
 - delay_check     : asking whether a specific train is delayed  -> routed to Hub (Operations)
 - policy_query   : asking about refund/cancellation/luggage/seating/etc. rules -> passenger FAQ (policies.md)
 - engineering_query : asking how rolling-stock/track equipment works -> not a passenger service (fixed notice)
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
        "operational status",
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
        # Sinhala booking VERBS (වෙන්කර... / වෙන් කර... = reserve/book). The bare noun
        # "ටිකට් එක" ("the ticket") was here and routed "... ටිකට් එක කීයද?" (a fare
        # question) to booking_request, so it is not a booking keyword.
        "වෙන්කර", "වෙන් කර", "බුක් කර", "ටිකට් එකක් ඕන", "ටිකට් එකක් ගන්න",
        "முன்பதிவு", "டிக்கெட் வாங்க", "இட ஒதுக்கீடு",
    ],
    "fare_query": [
        "fare", "price", "cost", "ticket price", "how much",
        "ගාස්තුව", "මිල", "කීයද",
        "கட்டணம்", "விலை", "எவ்வளவு",
    ],
    "schedule_query": [
        "schedule", "time", "departs", "departure", "arrival", "next train",
        # "What trains run from A to B?" - asking which services exist on a route
        "what trains", "which trains", "trains run", "trains from", "trains between",
        "වේලාව", "වේලාසටහන", "ඊළඟ දුම්රිය", "දුම්රිය මොනවාද", "යන දුම්රිය",
        "நேரம்", "அட்டவணை", "அடுத்த ரயில்", "ரயில்கள் என்ன", "செல்லும் ரயில்கள்",
    ],
    "complaint": [
        "broken", "not working", "issue", "problem", "faulty", "damage", "complaint",
        "noise", "leaking",
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
    # Sinhala / Tamil: "details", "information", "where" (a train ID is still required)
    "විස්තර", "තොරතුරු", "කොහෙද", "விவரங்கள்", "விவரம்", "தகவல்", "எங்கே",
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


# --- Information questions vs. actions / live requests ----------------------
#
# The keyword loop below answers "which topic word is in the message?", which
# cannot tell "Can I get a refund?" (a question about the rules) from "Cancel my
# booking RS-12345" (an action), or "How much luggage can I carry?" from "How
# much is a ticket?". Words like refund / cancel / delay / reservation /
# complaint / "how much" therefore shadowed the policy FAQ (policies.md) and
# even created cancellation cards and maintenance tickets for plain questions.
#
# classify_intent() now first asks: is this an INFORMATION question (question
# framing + a policy topic) with NO sign of an action or a live lookup? If so it
# is "policy_query" and is answered from the passenger FAQ. Any specific object
# (a booking reference, a train ID, a clock time, or a booking verb together
# with a route/date/seat count) keeps it on the operational path.

_BOOKING_REF_PATTERN = re.compile(r"\bRS-[A-Za-z0-9]{4,10}\b", re.IGNORECASE)
_CLOCK_TIME_PATTERN = re.compile(r"\b(?:[01]?\d|2[0-3])[:.][0-5]\d\b")

# Question framing: opens like a question, or is explicitly about rules.
_INFO_FRAME_PATTERN = re.compile(
    r"^\s*(?:what|what's|whats|how|can|could|may|do|does|will|would|is there|are there|"
    r"am i|tell me|explain|where can|when can|who can)\b"
    r"|\b(?:polic(?:y|ies)|rules?|procedure|terms|entitled|eligible|eligibility|"
    r"allowed|allowance|what happens|what if|happens if|explain)\b"
)

_POLICY_TOPIC_PATTERN = re.compile(
    r"\b(?:luggage|baggage|bags?|bicycles?|refunds?|refunded|"
    r"cancel(?:l?ed|l?ing|l?ation|s)?|reserved seat(?:ing|s)?|seat reservations?|"
    r"reservations?|validity|valid|expire[sd]?|complain(?:t|ts|ing)?|transfer(?:able)?|"
    r"non-?transferable|season tickets?|identity card|nic|booking (?:limit|rules?)|"
    r"how many (?:seats|tickets|passengers))\b"
)
# "delay"/"late" only count as a policy topic when phrased hypothetically or
# about compensation - "Are there any delays on the Kandy line?" is a live
# question and must still reach Operations.
_DELAY_TOPIC_PATTERN = re.compile(r"\b(?:delay(?:s|ed)?|late)\b")
_DELAY_POLICY_MARKER_PATTERN = re.compile(
    r"\b(?:polic(?:y|ies)|compensat\w*|entitle\w*|what happens|what if|happens if|"
    r"if (?:my|the|a|our) train|rules?)\b"
)
_HOW_TO_REPORT_PATTERN = re.compile(
    r"\bhow (?:do|can|to|would)\b.*\b(?:report|complain|complaint|file a)\b"
)

_BOOK_VERB_PATTERN = re.compile(r"\b(?:book|buy|purchase|reserve)\b")
_DATE_OR_COUNT_PATTERN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|\b(?:today|tomorrow|tonight)\b|"
    r"\b\d+\s*(?:seats?|tickets?|passengers?|people|persons?)\b"
)

# Engineering / maintenance-manual topics. Those manuals belong to the
# Maintenance Agent and are engineer-facing; a passenger asking how a component
# works gets a "not available" notice instead of manual content.
_ENGINEERING_TOPIC_PATTERN = re.compile(
    r"\b(?:brake|brakes|bogies?|pantograph|traction motors?|locomotives?|diesel engine|"
    r"turbocharger|transformer|inverter|axles?|bearings?|gearbox|draw gear|interlocking|"
    r"point motors?|track circuits?|ballast|sleepers?|rail welding|signal equipment|"
    r"emergency valve|air brake|vacuum brake|wheel slip|fault codes?|torque|"
    r"maintenance manual|technical manual|service intervals?|inspection intervals?)\b"
)
_ENGINEERING_FRAME_PATTERN = re.compile(
    r"\b(?:what does|what is|what are|how does|how do|how to|explain|procedure|steps|"
    r"manual|maintain|maintenance|repair|inspect|inspection|replace|why does|purpose of|"
    r"function of|work)\b"
)
# A passenger describing a fault they can see is a complaint, not an
# engineering question - keep that on the maintenance-ticket path.
_PASSENGER_FAULT_PATTERN = re.compile(
    r"\b(?:my|in my|compartment|coach|carriage|our train|this train|making noise|"
    r"broken|not working|faulty|leaking|smell|smoke)\b"
)


def _has_station(lowered: str) -> bool:
    from nlu.ner_extractor import STATION_ALIASES  # lazy: ner_extractor pulls in the LLM client

    return any(alias.lower() in lowered for aliases in STATION_ALIASES.values() for alias in aliases)


def _is_engineering_question(lowered: str) -> bool:
    return bool(
        _ENGINEERING_TOPIC_PATTERN.search(lowered)
        and _ENGINEERING_FRAME_PATTERN.search(lowered)
        and not _PASSENGER_FAULT_PATTERN.search(lowered)
    )


def _is_policy_question(text: str, lowered: str) -> bool:
    if not _INFO_FRAME_PATTERN.search(lowered):
        return False
    topic = (
        _POLICY_TOPIC_PATTERN.search(lowered)
        or _HOW_TO_REPORT_PATTERN.search(lowered)
        or (_DELAY_TOPIC_PATTERN.search(lowered) and _DELAY_POLICY_MARKER_PATTERN.search(lowered))
    )
    if not topic:
        return False
    # A concrete object means the passenger wants an action or a live lookup.
    if _BOOKING_REF_PATTERN.search(text) or _TRAIN_ID_PATTERN.search(text) or _CLOCK_TIME_PATTERN.search(lowered):
        return False
    if _BOOK_VERB_PATTERN.search(lowered) and (_has_station(lowered) or _DATE_OR_COUNT_PATTERN.search(lowered)):
        return False
    return True


def _normalize(text: str) -> str:
    """Lower-case and drop zero-width joiners/non-joiners. Sinhala conjuncts such
    as "ප්‍රමාද" contain U+200D, and many keyboards/copy-pastes omit it - without
    this the keyword only matched one of the two spellings."""
    return text.lower().replace("\u200d", "").replace("\u200c", "")


def classify_intent(text: str) -> str:
    lowered = _normalize(text)
    if _is_engineering_question(lowered):
        return "engineering_query"
    if _is_policy_question(text, lowered):
        return "policy_query"
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            kw = _normalize(kw)
            if kw == "reserve":
                # Bare "reserve" as a substring also matches inside "reserved"
                # - a fare/seat class adjective (e.g. "2nd class reserved"),
                # not a booking verb - which was hijacking fare_query into
                # booking_request. Require it as its own word; "reservation"
                # is unaffected since it's already a separate keyword above.
                if re.search(r"\breserve\b", lowered):
                    return intent
                continue
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
