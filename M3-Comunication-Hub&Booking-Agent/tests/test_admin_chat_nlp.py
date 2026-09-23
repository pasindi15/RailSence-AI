"""
tests/test_admin_chat_nlp.py
----------------------------
Test suite for NLP query understanding layer in the Admin Booking Intelligence Assistant:
- Intent classification across all designated intents
- Train name & ID extraction
- Booking & case reference extraction
- Date parsing & normalization in Asia/Colombo
- Seat class & risk level extraction
- Conversational follow-up context resolution
"""

import sys
from pathlib import Path
import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_M3_ROOT = _TESTS_DIR.parent
_BOOKING_AGENT_DIR = _M3_ROOT / "booking-agent"

for p in (str(_M3_ROOT), str(_BOOKING_AGENT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from admin_chat.date_parser import parse_query_date, get_current_colombo_date
from admin_chat.entity_extractor import extract_entities
from admin_chat.intent_classifier import classify_intent
from admin_chat.nlp import process_admin_nlp


class TestAdminChatNLP:

    def test_intent_classification_fraud(self):
        """1. Fraud Review queries."""
        q1 = "How many suspicious bookings are waiting for review?"
        assert classify_intent(q1) == "fraud_review_query"

        q2 = "Show high-risk bookings waiting for review today."
        assert classify_intent(q2) == "fraud_review_query"

        q3 = "Why was booking BKG-102 flagged?"
        ents = extract_entities(q3)
        assert classify_intent(q3, ents) == "fraud_review_query"

    def test_intent_classification_cancellation(self):
        """2. Cancellation queries."""
        q1 = "How many cancellation requests are pending?"
        assert classify_intent(q1) == "cancellation_query"

        q2 = "How much refund is expected for BKG-443?"
        ents = extract_entities(q2)
        assert classify_intent(q2, ents) == "cancellation_query"

        q3 = "Show rejected cancellation requests today."
        assert classify_intent(q3) == "cancellation_query"

    def test_intent_classification_seats_and_schedules(self):
        """3. Schedules & seat availability."""
        q1 = "How many seats are available on Udarata Menike tomorrow?"
        ents = extract_entities(q1)
        assert classify_intent(q1, ents) == "seat_availability_query"

        q2 = "How many first class seats are left?"
        ents = extract_entities(q2)
        assert classify_intent(q2, ents) == "seat_availability_query"

        q3 = "What trains operate tomorrow?"
        assert classify_intent(q3) == "schedule_query"

        assert classify_intent("Is Podi Menike sold out tomorrow?", extract_entities("Is Podi Menike sold out tomorrow?")) == "seat_availability_query"
        assert classify_intent("Which trains have open seats tomorrow?", extract_entities("Which trains have open seats tomorrow?")) == "seat_availability_query"
        assert classify_intent("When does Udarata Menike leave?", extract_entities("When does Udarata Menike leave?")) == "schedule_query"

    def test_intent_classification_manifest_and_summary(self):
        """4. Manifest and booking statistics."""
        q1 = "Show passengers booked on train 1005 tomorrow."
        assert classify_intent(q1) == "booking_manifest_query"

        q2 = "Give me today's booking summary."
        assert classify_intent(q2) == "booking_statistics"

        assert classify_intent("Give me the booking totals for today.") == "booking_statistics"

        q3 = "Find booking RS-10023."
        ents = extract_entities(q3)
        assert classify_intent(q3, ents) == "booking_lookup"

    def test_intent_classification_mutation_guard(self):
        """5. Unsupported mutation/action requests."""
        assert classify_intent("Approve booking BKG-1005") == "unsupported_mutation"
        assert classify_intent("Cancel booking RS-99212") == "unsupported_mutation"
        assert classify_intent("Reject fraud review case FR-102") == "unsupported_mutation"
        assert classify_intent("Delete booking RS-12345") == "unsupported_mutation"

    def test_entity_extraction_comprehensive(self):
        """6. Train name, date, class extraction."""
        query = "How many first class seats are available on Udarata Menike on September 25?"
        ents = extract_entities(query)
        assert ents.get("train_name") == "Udarata Menike"
        assert ents.get("seat_class") == "First Class"
        assert ents.get("travel_date") is not None
        assert "09-25" in ents["travel_date"]

    def test_entity_extraction_risk_and_status(self):
        """7. Risk level and review status."""
        query = "Show high risk bookings waiting for review today"
        ents = extract_entities(query)
        assert ents.get("risk_level") == "HIGH"
        assert ents.get("review_status") == "PENDING"
        assert ents.get("travel_date") is not None

    def test_date_parsing_relative(self):
        """8. Date parsing: today, tomorrow, yesterday."""
        today = get_current_colombo_date()
        d_today, str_today = parse_query_date("Show bookings today")
        assert d_today == today
        assert str_today == today.isoformat()

        d_tom, str_tom = parse_query_date("Trains tomorrow")
        assert (d_tom - today).days == 1

        d_yest, str_yest = parse_query_date("cancellations yesterday")
        assert (today - d_yest).days == 1

    def test_conversational_follow_up_stitching(self):
        """9. Conversational follow-up entity stitching."""
        history = [
            {"role": "user", "content": "Show Udarata Menike seat availability tomorrow."},
            {"role": "assistant", "content": "First Class: 9, Second Class: 24"}
        ]
        follow_up = "What about first class?"
        result = process_admin_nlp(follow_up, history=history)

        assert result["intent"] == "seat_availability_query"
        assert result["entities"].get("seat_class") == "First Class"
        assert result["entities"].get("train_name") == "Udarata Menike"
        assert result["entities"].get("travel_date") is not None

    def test_common_chat_typos_are_normalized(self):
        """Frequent spelling mistakes still resolve the requested train and date."""
        query = "how meny booking have podi manike tommorow?"
        result = process_admin_nlp(query)
        assert result["intent"] == "booking_manifest_query"
        assert result["entities"].get("train_name") == "Podi Menike"
        assert result["entities"].get("travel_date") is not None

    def test_availability_paraphrases_share_intent(self):
        queries = [
            "How many seats are available on Udarata Menike tomorrow?",
            "Is Udarata Menike full tomorrow?",
            "Can I still book Udarata Menike tomorrow?",
            "Are we getting close to capacity on Udarata tomorrow?",
            "How meny seats are availble on Udarata Manike tommorow?",
        ]
        for query in queries:
            result = process_admin_nlp(query)
            assert result["intent"] == "seat_availability_query"
            assert result["understanding"].filters["all_trains"] is False

    def test_broad_and_route_availability_intents(self):
        broad = process_admin_nlp("Which trains still have seats tomorrow?")
        route = process_admin_nlp("Which trains from Colombo to Kandy have seats tomorrow?")
        assert broad["intent"] == "seat_availability_query"
        assert broad["understanding"].filters["all_trains"] is True
        assert route["intent"] == "seat_availability_query"
        assert route["entities"]["origin_station"] == "Colombo"
        assert route["entities"]["destination_station"] == "Kandy"

    def test_ticket_and_schedule_paraphrases(self):
        ticket = process_admin_nlp("What's happening with ticket TKT-12345?")
        schedule = process_admin_nlp("When does Udarata Menike leave tomorrow?")
        assert ticket["intent"] == "ticket_query"
        assert schedule["intent"] == "schedule_query"
