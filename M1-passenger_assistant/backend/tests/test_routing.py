"""
Regression table for information-vs-action routing (nlu/intent_classifier.py).

The same topic word must route differently depending on whether the passenger
is ASKING ABOUT THE RULES (-> passenger FAQ) or REQUESTING AN ACTION / LIVE
LOOKUP (-> Booking / Operations / Maintenance via the Hub). No Hub, LLM or
database is involved here.
"""
import pytest

from nlu.intent_classifier import classify_intent

# (message, expected intent, why)
CASES = [
    # --- policy vs fare ("how much") ---------------------------------------
    ("How much luggage can I carry?", "policy_query", "'how much' must not make luggage a fare question"),
    ("How much is a ticket from Colombo Fort to Kandy?", "fare_query", "real fare question"),
    ("What is the train fare from Colombo Fort to Kandy?", "fare_query", "real fare question"),
    # --- policy vs cancellation / refund -----------------------------------
    ("Can I cancel my ticket?", "policy_query", "asking whether cancelling is allowed"),
    ("Can I get a refund?", "policy_query", "asking about the refund rules"),
    ("What is the refund policy?", "policy_query", "asking about the refund rules"),
    ("How much refund will I get?", "policy_query", "refund rules, not a fare"),
    ("How do I cancel my booking?", "policy_query", "asking for the procedure"),
    ("Cancel my booking RS-12345", "cancel_booking", "action with a booking reference"),
    ("Can I cancel booking RS-12345?", "cancel_booking", "a concrete booking reference means action"),
    ("Cancel booking RS-84521 because I accidentally booked twice", "cancel_booking", "action + reason"),
    ("I want to cancel my ticket", "cancel_booking", "first-person action request"),
    # --- policy vs live delay ----------------------------------------------
    ("What happens if my train is delayed?", "policy_query", "hypothetical -> compensation/refund rules"),
    ("What happens if my train is cancelled?", "policy_query", "hypothetical -> refund rules"),
    ("Is IC-8746 delayed?", "delay_check", "live lookup for a specific train"),
    ("Is the train from Colombo Fort to Kandy delayed?", "delay_check", "live lookup"),
    ("Are there any delays on the Kandy line?", "delay_check", "live question, no policy wording"),
    ("How much delay expected for IC-8746 from Colombo Fort to Kandy at 6.00?", "delay_check", "train id + time = live"),
    # --- policy vs booking --------------------------------------------------
    ("How does reserved seating work?", "policy_query", "rules of reserved seating"),
    ("How many seats can I book at once?", "policy_query", "booking limit, no route/date"),
    ("Book a reserved seat from Colombo Fort to Kandy", "booking_request", "booking action"),
    ("Can I book a reserved seat from Colombo Fort to Kandy?", "booking_request", "route given -> action"),
    ("Book 2 seats from Colombo Fort to Kandy", "booking_request", "booking action"),
    # --- complaint ----------------------------------------------------------
    ("What is the complaint procedure?", "policy_query", "asking about the procedure, no ticket to raise"),
    ("How can I make a complaint?", "policy_query", "asking about the procedure"),
    ("I want to report a problem with my journey", "complaint", "action -> maintenance ticket"),
    ("The AC is broken in my compartment", "complaint", "fault report"),
    ("The brake is making a strange noise in my coach", "complaint", "fault report, not an engineering question"),
    # --- other policy topics ------------------------------------------------
    ("What is the ticket validity period?", "policy_query", ""),
    # --- fare / schedule / status stay as they were -------------------------
    ("What time does the next train to Kandy leave?", "schedule_query", ""),
    ("Is the train running today?", "train_status", ""),
    ("Is train running?", "train_status", ""),
    # --- engineering questions: not a passenger service ---------------------
    ("What does the brake emergency valve do?", "engineering_query", "manual content is engineer-only"),
    ("How does a pantograph work?", "engineering_query", ""),
    ("Explain the bogie inspection procedure", "engineering_query", ""),
    # --- nothing railway-related --------------------------------------------
    ("What is the weather in London?", "unknown", "falls through to the out-of-scope guard"),
    ("write me a poem about the ocean", "unknown", ""),
]


@pytest.mark.parametrize("message,expected,why", CASES, ids=[c[0][:60] for c in CASES])
def test_intent_routing(message, expected, why):
    assert classify_intent(message) == expected, why


def test_topic_words_alone_never_become_policy_queries():
    """A bare imperative/statement with a topic word is still an action."""
    for message in ("cancel booking", "please cancel my reservation", "book a ticket to Kandy", "my train is late"):
        assert classify_intent(message) != "policy_query", message
