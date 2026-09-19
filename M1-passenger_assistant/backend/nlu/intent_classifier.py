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

INTENT_KEYWORDS = {
    "operational_alert": [
        "operational delay alert", "operational alert", "delay alert",
        "require an operational", "require a delay alert", "require an alert",
    ],
    "historical_incidents": [
        "historical incident", "historical incidents", "similar incident", "similar incidents",
        "similar past incident", "similar to the delay", "past incident", "past incidents",
        "incident history",
    ],
    "delay_check": [
        "delay", "delayed", "late", "on time", "on-time", "how late", "expected delay",
        "postpone", "running late",
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
    "train_status": [
        "is train", "train running", "train available", "train cancelled", "train service",
        "is the train", "will train", "train operating", "out of service", "under maintenance",
        "train working", "service today", "train status",
        "දුම්රිය ධාවනය", "දුම්රිය ක්‍රියාත්මකද",
        "ரயில் இயங்குகிறதா", "ரயில் நிலை",
    ],
    "fare_query": [
        "fare", "price", "cost", "ticket price", "how much",
        "ගාස්තුව", "මිල", "කීයද",
        "கட்டணம்", "விலை", "எவ்வளவு",
    ],
    "schedule_query": [
        "trains available", "available to travel", "trains go from", "trains run from",
        "trains from", "trains to", "kandy trains", "colombo trains", "today's trains",
        "available tomorrow", "available today", "which trains", "what trains",
        "show me today", "show me kandy", "show me colombo",
        "schedule", "time", "departs", "departure", "arrival", "next train", "timetable",
        "වේලාව", "වේලාසටහන", "ඊළඟ දුම්රිය",
        "நேரம்", "அட்டவணை", "அடுத்த ரயில்",
    ],
    "complaint": [
        "broken", "not working", "issue", "problem", "faulty", "damage", "complaint",
        "ගැටලුවක්", "කැඩිලා", "අබලද්ධ",
        "பிரச்சனை", "உடைந்த", "சிக்கல்",
    ],
}

TRAIN_INFO_KEYWORDS = [
    "what is", "where does", "where is", "which route", "train information",
    "train details", "active", "departs", "departure", "arrives", "arrival",
    "leave", "go",
]


def classify_intent(text: str) -> str:
    lowered = text.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in lowered:
                return intent
    if any(kw in lowered for kw in TRAIN_INFO_KEYWORDS):
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
