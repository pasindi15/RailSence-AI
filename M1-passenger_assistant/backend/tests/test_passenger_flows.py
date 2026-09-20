"""
End-to-end /chat flows for source-of-truth routing.

Runs the real FastAPI app, the real Chroma index and the real NLU; only the
Hub transport and the LLM are replaced (so no network, no quota). Supabase chat
persistence is disabled so these tests never write rows to the real database.

Assertions are on WHERE the answer came from (intent/source/what the LLM was
shown/which agent the Hub was asked), not on LLM wording.
"""
import pytest
from fastapi.testclient import TestClient

import hub_client
import main

client = TestClient(main.app)


class FakeGemini:
    def __init__(self, reply="LLM reply"):
        self.reply = reply
        self.last_prompt = None
        self.calls = 0

    def generate_content(self, prompt):
        self.calls += 1
        self.last_prompt = prompt

        class _R:
            text = self.reply

        return _R()


class HubSpy:
    """Records every envelope M1 sends to the Hub and answers with a canned response."""

    def __init__(self, response=None):
        self.sent = []
        self._response = response

    async def __call__(self, message):
        self.sent.append(message)
        if self._response is not None:
            return self._response
        return hub_client.send_to_hub_mock(message)

    @property
    def receivers(self):
        return [m.receiver_agent for m in self.sent]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(main, "supabase", None)
    llm = FakeGemini()
    monkeypatch.setattr(main, "gemini_model", llm)
    hub = HubSpy()
    monkeypatch.setattr(main, "send_to_hub", hub)
    return llm, hub


def chat(message):
    r = client.post("/chat", json={"message": message})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------- policy questions -> FAQ ---

POLICY_CASES = [
    ("How much luggage can I carry?", "up to 25kg"),
    ("Can I get a refund?", "75%"),
    ("What is the refund policy?", "75%"),
    ("Can I cancel my ticket?", "administrator"),
    ("How does reserved seating work?", "Seats are assigned in the order"),
    ("What is the ticket validity period?", "Point-to-point tickets are valid only"),
    ("How can I make a complaint?", "Maintenance Department"),
    ("What is the complaint procedure?", "Maintenance Department"),
    ("What happens if my train is cancelled?", "100%"),
    ("What happens if my train is delayed?", "more than 3 hours"),
    ("How many seats can I book at once?", "at most 10 seats"),
]


@pytest.mark.parametrize("message,expected_fact", POLICY_CASES, ids=[c[0] for c in POLICY_CASES])
def test_policy_question_is_answered_from_policies_faq(message, expected_fact, _isolate):
    llm, hub = _isolate
    body = chat(message)

    assert body["intent"] == "policy_query"
    assert "policies.md" in body["source"]
    assert expected_fact in llm.last_prompt, "the retrieved policy context did not contain the expected fact"
    # A question about the rules must not trigger any action or agent.
    assert body["action"] is None and body["cancellation"] is None and body["prefill"] is None
    assert hub.sent == [], f"policy question was sent to the Hub: {hub.receivers}"


# ------------------------------------------------ actions / live -> agents ---

def test_cancel_booking_is_a_cancellation_workflow_not_rag(_isolate):
    llm, hub = _isolate
    body = chat("Cancel my booking RS-12345")
    assert body["intent"] == "cancel_booking"
    assert body["action"]["type"] == "cancellation_confirmation_card"
    assert body["action"]["booking_reference"] == "RS-12345"
    assert llm.calls == 0


def test_booking_request_generates_prefilled_link_without_hub(_isolate):
    _, hub = _isolate
    body = chat("Book second class, 2 seats from Colombo Fort to Kandy on 2026-12-03 train PM-4082")
    assert body["intent"] == "booking_request"
    assert hub.sent == []
    assert body["source"] == "Passenger Assistant booking link"
    assert body["action"]["type"] == "continue_to_booking"
    assert body["action"]["prefill"] == {
        "from_station": "Colombo Fort",
        "to_station": "Kandy",
        "travel_date": "2026-12-03",
        "train_id": "PM-4082",
        "seat_class": "Second Class",
        "passenger_count": 2,
    }
    assert "train_id=PM-4082" in body["action"]["url"]
    assert "passenger_count=2" in body["action"]["url"]


def test_live_delay_goes_to_operations_agent_via_hub_not_policies(_isolate):
    llm, hub = _isolate
    body = chat("Is IC-8746 delayed?")
    assert body["intent"] == "delay_check"
    assert "Operations Agent" in body["source"]
    assert hub.receivers[0] == "operations-agent"
    assert llm.calls == 0


def test_problem_report_creates_a_maintenance_ticket_via_hub(_isolate):
    _, hub = _isolate
    body = chat("I want to report a problem with my journey")
    assert body["intent"] == "complaint"
    assert hub.receivers == ["maintenance-agent"]


def test_complaint_procedure_question_does_not_create_a_maintenance_ticket(_isolate):
    _, hub = _isolate
    chat("What is the complaint procedure?")
    assert "maintenance-agent" not in hub.receivers


# ----------------------------------------------------------------- fares ---

def test_fare_answer_uses_booking_system_prices(_isolate):
    llm, _ = _isolate
    body = chat("What is the fare from Colombo Fort to Kandy?")
    assert body["intent"] == "fare_query"
    assert "LKR 1200 per seat" in llm.last_prompt and "LKR 2500 per seat" in llm.last_prompt
    assert "LKR 500" not in llm.last_prompt  # the old, conflicting M1-only value


def test_fare_for_a_route_the_booking_system_cannot_price_is_declined_not_guessed(_isolate):
    llm, _ = _isolate
    body = chat("What is the fare from Colombo Fort to Jaffna?")
    assert body["intent"] == "fare_query"
    assert body["reply"] == main.FARE_NOT_AVAILABLE_REPLIES["en"]
    assert llm.calls == 0  # no LLM, so no chance of quoting Kandy's price for Jaffna


def test_first_class_fare_is_filtered_to_first_class(_isolate):
    llm, _ = _isolate
    chat("first class fare from Colombo Fort to Kandy for 3 passengers")
    assert "FARE_CLASS_FILTER: true" in llm.last_prompt
    assert "First Class: LKR 2500 x 3 passengers = LKR 7500" in llm.last_prompt


def test_a_class_the_booking_system_does_not_sell_is_reported_as_unavailable(_isolate):
    llm, _ = _isolate
    chat("1st class AC fare from Colombo Fort to Kandy")
    assert "FARE_CLASS_NOT_FOUND: true" in llm.last_prompt


# ------------------------------------- out of scope / engineering boundary ---

OUT_OF_SCOPE_QUESTIONS = [
    "What is the weather in London?",
    "write me a poem about the ocean",
    "how do I bake a cake",
    "who won the cricket world cup",
    "write python code to sort a list",
    "best restaurants in Colombo",
]


@pytest.mark.parametrize("message", OUT_OF_SCOPE_QUESTIONS)
def test_non_railway_question_gets_the_fixed_service_notice(message, _isolate):
    llm, hub = _isolate
    body = chat(message)
    assert body["intent"] == "out_of_scope"
    assert body["reply"] == main.OUT_OF_SCOPE_REPLIES["en"]
    assert body["source"] == ""
    assert llm.calls == 0, "the LLM must not be consulted for out-of-scope questions"
    assert hub.sent == []


def test_out_of_scope_notice_is_localized(_isolate):
    llm, _ = _isolate
    si = chat("ලන්ඩන් හි කාලගුණය කුමක්ද?")
    ta = chat("லண்டனில் வானிலை என்ன?")
    assert si["language"] == "si" and si["reply"] == main.OUT_OF_SCOPE_REPLIES["si"]
    assert ta["language"] == "ta" and ta["reply"] == main.OUT_OF_SCOPE_REPLIES["ta"]
    assert llm.calls == 0


def test_engineering_question_is_not_answered_or_forwarded_to_maintenance(monkeypatch, _isolate):
    llm, hub = _isolate

    def _no_retrieval(*a, **k):
        raise AssertionError("engineering question must not even touch the FAQ index")

    monkeypatch.setattr(main, "retrieve_faq_chunks", _no_retrieval)
    body = chat("What does the brake emergency valve do?")

    assert body["intent"] == "engineering_query"
    assert body["reply"] == main.ENGINEERING_NOTICE_REPLIES["en"]
    assert hub.sent == [] and llm.calls == 0


# ------------------------------------- historical vs live operations data ---

def _ops_response(**payload):
    return hub_client.HubResponse(status="ok", sender_agent="operations-agent", payload=payload)


def test_historical_observation_is_labelled_as_history_not_live_status(monkeypatch):
    hub = HubSpy(_ops_response(
        predicted_delay_minutes=6.8,
        model_version="historical-observation-v1",
        retrieval_method="historical_record",
        reason=(
            "Historical observation for IC-8746: 6.8 minutes on Colombo Fort - Kandy. "
            "Recorded operational cause: Flooding risk near Kandy."
        ),
        similar_incident="weather at Kandy: Flooding risk (historical delay 6.8 min).",
    ))
    monkeypatch.setattr(main, "send_to_hub", hub)

    reply = chat("Is IC-8746 delayed?")["reply"]

    assert reply.startswith("Expected delay: 6.8 minutes")
    assert "not a live status" in reply
    assert "recorded history" in reply and "Historical record:" in reply


def test_model_estimate_and_similar_incident_are_labelled_as_such(monkeypatch):
    hub = HubSpy(_ops_response(
        predicted_delay_minutes=12.0,
        model_version="delay-gbr-v3",
        retrieval_method="pgvector",
        reason="Peak-hour congestion on this line.",
        similar_incident="signal_fault at Galle (historical delay 15 min).",
    ))
    monkeypatch.setattr(main, "send_to_hub", hub)

    reply = chat("Is IC-8746 delayed?")["reply"]

    assert "an estimate, not a live status" in reply
    assert "Similar past incident (historical, not current):" in reply
