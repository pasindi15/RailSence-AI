from fastapi.testclient import TestClient
import hub_client
import main
from main import app

client = TestClient(app)


async def _mock_send_to_hub(message):
    """Routes through hub_client's offline stub instead of a real HTTP call -
    send_to_hub() now genuinely calls out to AGENT_HUB_URL by default, and
    these tests care about /chat's routing logic, not Hub availability."""
    return hub_client.send_to_hub_mock(message)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_schedule_query():
    r = client.post("/chat", json={"message": "What time does the next train to Kandy leave?"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "schedule_query"
    assert body["language"] == "en"


def test_delay_check_routes_to_hub_stub(monkeypatch):
    import main
    monkeypatch.setattr(main, "send_to_hub", _mock_send_to_hub)
    r = client.post("/chat", json={"message": "Is the 14:35 Colombo Fort to Kandy train delayed?"})
    body = r.json()
    assert body["intent"] == "delay_check"
    assert "Operations Agent" in body["source"]


def test_complaint_routes_to_maintenance_stub(monkeypatch):
    import main
    monkeypatch.setattr(main, "send_to_hub", _mock_send_to_hub)
    r = client.post("/chat", json={"message": "The AC is broken in my compartment"})
    body = r.json()
    assert body["intent"] == "complaint"
    assert "Maintenance Agent" in body["source"]


def test_booking_request_routes_to_booking_stub_with_entities(monkeypatch):
    import main
    monkeypatch.setattr(main, "send_to_hub", _mock_send_to_hub)
    r = client.post(
        "/chat",
        json={
            "message": (
                "Book second class, 2 seats from Colombo Fort to Kandy on 2026-12-03 "
                "train PM-4082"
            )
        },
    )
    body = r.json()
    assert body["intent"] == "booking_request"
    assert body["source"] == "via Booking Agent"
    assert body["entities"]["from_station"] == "Colombo Fort"
    assert body["entities"]["to_station"] == "Kandy"
    assert body["entities"]["travel_date"] == "2026-12-03"
    assert body["entities"]["train_id"] == "PM-4082"
    assert body["entities"]["seat_class"] == "Second Class"
    assert body["entities"]["passenger_count"] == 2


def test_sinhala_language_detection():
    r = client.post("/chat", json={"message": "මාර්ගයේ ඊළඟ දුම්රිය කීයටද?"})
    body = r.json()
    assert body["language"] == "si"


def test_fare_query_uses_rag_and_llm_composition(monkeypatch):
    import main

    class _FakeResponse:
        text = (
            "A one-way fare from Colombo Fort to Kandy ranges from LKR 130 "
            "(3rd class) up to LKR 1500 (1st class observation saloon)."
        )

    class _FakeGeminiModel:
        def generate_content(self, prompt):
            return _FakeResponse()

    monkeypatch.setattr(main, "gemini_model", _FakeGeminiModel())

    r = client.post("/chat", json={"message": "How much is a ticket to Kandy?"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "fare_query"
    # A Gemini-composed answer is prose, not the raw markdown dump
    # (raw fares.md content starts with a "#" heading and "Here's what I found:").
    assert not body["reply"].startswith("Here's what I found:")
    assert "##" not in body["reply"]
    assert "fares.md" in body["source"]


def test_cancel_booking():
    r = client.post("/chat", json={"message": "Cancel booking RS-84521 because I accidentally booked twice"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "cancel_booking"
    assert body["entities"]["booking_reference"] == "RS-84521"
    assert body["action"]["type"] == "cancellation_confirmation_card"
    assert body["action"]["booking_reference"] == "RS-84521"
    assert "booked twice" in body["action"]["reason"]


class _CapturingGeminiModel:
    """Records the prompt it was called with, so tests can assert on prompt
    content (the language instruction, the off-topic/passenger-count flags)
    without depending on live Gemini output or burning API quota."""

    def __init__(self, reply_text):
        self._reply_text = reply_text
        self.last_prompt = None

    def generate_content(self, prompt):
        self.last_prompt = prompt

        class _R:
            text = self._reply_text

        return _R()


# FIX 1 - greeting short-circuit (also covers FIX 4 for the greeting path:
# an English greeting must come back in English).
def test_greeting_short_circuit_replies_in_english():
    r = client.post("/chat", json={"message": "hii"})
    body = r.json()
    assert body["intent"] == "greeting"
    assert body["language"] == "en"
    assert body["reply"] == main.GREETING_REPLIES["en"]


# FIX 4 - a Sinhala fare question must carry an explicit Sinhala instruction
# in the prompt (not just the `language` field) and the reply is whatever
# the model returned unmodified.
def test_sinhala_fare_query_carries_explicit_language_instruction(monkeypatch):
    fake_model = _CapturingGeminiModel("සිංහල පිළිතුර")
    monkeypatch.setattr(main, "gemini_model", fake_model)

    r = client.post("/chat", json={"message": "මහනුවරට ගාස්තුව කීයද?"})
    body = r.json()

    assert body["language"] == "si"
    assert body["intent"] == "fare_query"
    assert "Respond only in Sinhala." in fake_model.last_prompt
    assert body["reply"] == "සිංහල පිළිතුර"


# FIX 4 - a Tamil delay_check question. The successful reply path is
# Hub-sourced content (English-only on M2's side, out of scope for this fix -
# see the comment on DELAY_UNREACHABLE_REPLIES in main.py), so this exercises
# the one part of delay_check that IS localized: the local fallback text used
# when the Hub can't be reached.
def test_tamil_delay_check_unreachable_fallback_is_in_tamil(monkeypatch):
    async def _failing_send_to_hub(message):
        return hub_client.HubResponse(status="error", message=None)

    monkeypatch.setattr(main, "send_to_hub", _failing_send_to_hub)

    r = client.post("/chat", json={"message": "PM-4082 ரயில் தாமதமா?"})
    body = r.json()

    assert body["language"] == "ta"
    assert body["intent"] == "delay_check"
    assert body["reply"] == main.DELAY_UNREACHABLE_REPLIES["ta"]


# FIX 2 - passenger_count is multiplied in code, not left for the LLM to
# guess; the pre-computed totals must be in the prompt verbatim.
def test_fare_query_with_passenger_count_computes_total_in_code(monkeypatch):
    fake_model = _CapturingGeminiModel("Your total fare is LKR 1000.")
    monkeypatch.setattr(main, "gemini_model", fake_model)

    r = client.post("/chat", json={"message": "how much colombo to kandy for 2 passengers"})
    body = r.json()

    assert body["entities"]["passenger_count"] == 2
    assert "LKR 500 x 2 passengers = LKR 1000" in fake_model.last_prompt
    assert "do not recalculate" in fake_model.last_prompt


# FIX 2 - when passenger_count isn't mentioned at all, the LLM is told to
# ask for it rather than silently answering as if for one passenger.
def test_fare_query_without_passenger_count_asks_instead_of_assuming(monkeypatch):
    fake_model = _CapturingGeminiModel("How many passengers are travelling?")
    monkeypatch.setattr(main, "gemini_model", fake_model)

    r = client.post("/chat", json={"message": "how much is a ticket to kandy"})
    body = r.json()

    assert body["entities"]["passenger_count"] is None
    assert "PASSENGER_COUNT_UNKNOWN: true" in fake_model.last_prompt


# FIX 3 - a clearly non-railway question through the unclassified ("unknown"
# intent) path must be flagged off-topic instead of handing the LLM
# irrelevant context it could still try to answer from.
def test_offtopic_query_gets_decline_flag_not_context(monkeypatch):
    fake_model = _CapturingGeminiModel("I can only help with railway questions.")
    monkeypatch.setattr(main, "gemini_model", fake_model)

    r = client.post("/chat", json={"message": "write me a poem about the ocean"})
    body = r.json()

    assert body["intent"] == "unknown"
    assert "OFF_TOPIC: true" in fake_model.last_prompt
    assert body["source"] == ""


# Routing fix: intent_classifier's train_status keywords included bare "is
# train"/"is the train", which matched as a substring of almost any "What is
# the train fare/schedule...?" or "Is the train ... delayed?" question,
# hijacking it to train_status before fare_query/schedule_query/delay_check's
# own keywords were ever checked (train_status is the first key in the
# INTENT_KEYWORDS dict, and classify_intent returns on first match). These
# lock in the corrected routing so it can't regress silently.
def test_fare_query_with_is_the_train_phrasing_routes_correctly():
    r = client.post("/chat", json={"message": "What is the train fare from Colombo Fort to Kandy?"})
    assert r.json()["intent"] == "fare_query"


def test_fare_query_with_passenger_count_and_is_the_train_phrasing():
    r = client.post(
        "/chat",
        json={"message": "What is the train fare from Colombo Fort to Kandy for 2 people?"},
    )
    body = r.json()
    assert body["intent"] == "fare_query"
    assert body["entities"]["passenger_count"] == 2


def test_schedule_query_with_is_the_train_phrasing_routes_correctly():
    r = client.post("/chat", json={"message": "What is the train schedule from Colombo Fort to Badulla?"})
    assert r.json()["intent"] == "schedule_query"


def test_delay_check_with_is_the_train_phrasing_still_works(monkeypatch):
    monkeypatch.setattr(main, "send_to_hub", _mock_send_to_hub)
    r = client.post("/chat", json={"message": "Is the train from Colombo Fort to Kandy delayed?"})
    assert r.json()["intent"] == "delay_check"


def test_fare_schedule_delay_routing_in_sinhala_and_tamil(monkeypatch):
    monkeypatch.setattr(main, "send_to_hub", _mock_send_to_hub)

    r = client.post("/chat", json={"message": "කොළඹ සිට මහනුවර දුම්රිය ගාස්තුව කීයද?"})
    assert r.json()["intent"] == "fare_query"

    r = client.post("/chat", json={"message": "කොළඹ සිට මහනුවර දුම්රිය වේලාසටහන කුමක්ද?"})
    assert r.json()["intent"] == "schedule_query"

    r = client.post("/chat", json={"message": "දුම්රිය ප්‍රමාදද?"})
    assert r.json()["intent"] == "delay_check"

    r = client.post("/chat", json={"message": "கொழும்பு முதல் கண்டி வரை ரயில் கட்டணம் எவ்வளவு?"})
    assert r.json()["intent"] == "fare_query"

    r = client.post("/chat", json={"message": "கொழும்பு முதல் கண்டி வரை ரயில் அட்டவணை என்ன?"})
    assert r.json()["intent"] == "schedule_query"

    r = client.post("/chat", json={"message": "ரயில் தாமதமா?"})
    assert r.json()["intent"] == "delay_check"


# Regression guard for the train_status keywords that were narrowed (not
# removed) - a genuine train-status question must still route correctly.
def test_train_status_still_works_after_removing_broad_keywords(monkeypatch):
    monkeypatch.setattr(main, "send_to_hub", _mock_send_to_hub)
    r = client.post("/chat", json={"message": "Is the train running today?"})
    assert r.json()["intent"] == "train_status"


def test_is_train_available_routes_to_train_status(monkeypatch):
    monkeypatch.setattr(main, "send_to_hub", _mock_send_to_hub)
    r = client.post("/chat", json={"message": "Is train available?"})
    assert r.json()["intent"] == "train_status"


# Full routing table requested for this round of fixes, kept as one explicit,
# auditable block even where individual cases overlap with tests above.
INTENT_ROUTING_CASES = [
    ("What is the train fare from Colombo Fort to Kandy?", "fare_query"),
    ("What is the train fare from Colombo Fort to Kandy for 2 people?", "fare_query"),
    ("What is the train schedule from Colombo Fort to Badulla?", "schedule_query"),
    ("Is the train from Colombo Fort to Kandy delayed?", "delay_check"),
    ("Is the train delayed?", "delay_check"),
    ("Has the train been delayed?", "delay_check"),
    ("Is train running?", "train_status"),
    ("Is the train running today?", "train_status"),
    ("What is the weather in London?", "unknown"),
]


def test_intent_routing_table(monkeypatch):
    monkeypatch.setattr(main, "send_to_hub", _mock_send_to_hub)
    for message, expected_intent in INTENT_ROUTING_CASES:
        r = client.post("/chat", json={"message": message})
        assert r.json()["intent"] == expected_intent, f"{message!r} -> expected {expected_intent}"


SI_TA_INTENT_ROUTING_CASES = [
    ("කොළඹ සිට මහනුවර දුම්රිය ගාස්තුව කීයද?", "fare_query"),
    ("කොළඹ සිට මහනුවර දුම්රිය වේලාසටහන කුමක්ද?", "schedule_query"),
    ("දුම්රිය ප්‍රමාදද?", "delay_check"),
    ("கொழும்பு முதல் கண்டி வரை ரயில் கட்டணம் எவ்வளவு?", "fare_query"),
    ("கொழும்பு முதல் கண்டி வரை ரயில் அட்டவணை என்ன?", "schedule_query"),
    ("ரயில் தாமதமா?", "delay_check"),
]


def test_intent_routing_table_sinhala_tamil(monkeypatch):
    monkeypatch.setattr(main, "send_to_hub", _mock_send_to_hub)
    for message, expected_intent in SI_TA_INTENT_ROUTING_CASES:
        r = client.post("/chat", json={"message": message})
        assert r.json()["intent"] == expected_intent, f"{message!r} -> expected {expected_intent}"


# Issue B regression: TRAIN_INFO_KEYWORDS' bare "what is" matched any
# "What is ...?" question with no train-relatedness requirement at all,
# routing a clearly off-topic question to train_info (whose handler then
# demanded a train ID) instead of "unknown" -> the off-topic guardrail.
def test_offtopic_weather_query_is_unknown_not_train_info():
    r = client.post("/chat", json={"message": "What is the weather in London?"})
    body = r.json()
    assert body["intent"] == "unknown"
    assert "train ID" not in body["reply"]


# Issue A regression: the per-person -> per-group fare multiplication was
# only ever applied inside the Gemini prompt, so if the LLM call fails for
# any reason (not configured, quota exhausted, network error, ...) the raw
# fallback silently showed unmultiplied 1-person prices for a group query.
def test_fare_query_multi_passenger_fallback_still_multiplies_when_gemini_fails(monkeypatch):
    class _FailingGeminiModel:
        def generate_content(self, prompt):
            raise RuntimeError("simulated Gemini failure (e.g. quota exhausted)")

    monkeypatch.setattr(main, "gemini_model", _FailingGeminiModel())

    r = client.post(
        "/chat",
        json={"message": "What is the train fare from Colombo Fort to Kandy for 2 people?"},
    )
    body = r.json()
    assert body["intent"] == "fare_query"
    assert body["entities"]["passenger_count"] == 2
    # The raw fallback text must show the code-computed totals, not the raw
    # per-person "LKR 500" lines un-multiplied.
    assert "LKR 500 x 2 passengers = LKR 1000" in body["reply"]


# Issue C: delay_check required an explicit train_id (e.g. "PM-4082") before
# it would even contact Operations, so a perfectly normal route-only delay
# question got blocked with "TRAIN_NOT_FOUND: provide a train ID..." without
# the Hub ever being called. M2's PredictionRequest requires train_id
# server-side (no default), so the fix looks one up via the shared train
# registry (already used by train_info/train_status) instead of just
# omitting it.
def test_delay_check_without_train_id_resolves_one_via_shared_registry(monkeypatch):
    monkeypatch.setattr(main, "send_to_hub", _mock_send_to_hub)
    r = client.post("/chat", json={"message": "Is the train from Colombo Fort to Kandy delayed?"})
    body = r.json()
    assert body["intent"] == "delay_check"
    assert "Operations Agent" in body["source"]
    # Confirms the Hub was actually reached (the mock's canned delay reply),
    # not the old "TRAIN_NOT_FOUND: provide a train ID" early return.
    assert "Expected delay" in body["reply"]


def test_delay_check_without_any_route_info_still_asks_for_a_train_id():
    r = client.post("/chat", json={"message": "Is the train delayed?"})
    body = r.json()
    assert body["intent"] == "delay_check"
    assert "TRAIN_NOT_FOUND" in body["reply"]


# Third recurrence of the same bug class: TRAIN_INFO_KEYWORDS' "train
# details" matched a plain station-pair question with no actual train ID,
# promoting it to train_info even though that handler is useless without
# one. classify_intent() now requires a real train ID pattern before
# returning train_info via this keyword list at all.
def test_station_only_train_details_falls_through_to_rag_not_train_info():
    r = client.post("/chat", json={"message": "kandy colombo train details"})
    body = r.json()
    assert body["intent"] == "unknown"
    assert "train ID" not in body["reply"]


def test_train_details_with_explicit_train_id_still_routes_to_train_info():
    r = client.post("/chat", json={"message": "PM-4082 train details"})
    assert r.json()["intent"] == "train_info"
