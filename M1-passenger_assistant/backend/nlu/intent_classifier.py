"""
Keyword-based intent classifier for Passenger Assistant Agent.

Intents:
 - schedule_query : asking about train times / routes
 - fare_query      : asking about ticket price / cost
 - delay_check     : asking whether a specific train is delayed  -> routed to Hub (Operations)
 - complaint       : reporting a broken/faulty issue              -> routed to Hub (Maintenance)
 - booking_request : requesting a train booking                    -> routed to Hub (Booking)
 - unknown         : fallback, handled locally with a clarifying reply
"""

INTENT_KEYWORDS = {
    "delay_check": [
        "delay", "late", "on time", "on-time", "postpone",
        "ප්‍රමාද", "ප්‍රමාදයි", "ප්‍රමාදද",
        "தாமதம்", "தாமதமா",
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


def classify_intent(text: str) -> str:
    lowered = text.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in lowered:
                return intent
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
