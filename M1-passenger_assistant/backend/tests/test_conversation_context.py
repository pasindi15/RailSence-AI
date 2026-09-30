"""
Conversation context / chat history for follow-up questions within a session.

Flow under test: a follow-up that names no station/train of its own ("What
about for 2 people?") previously fell through classify_intent() ("unknown")
and extract_entities() (no stations) untouched by history, so
compose_rag_answer()'s off-topic guardrail rejected it with the fixed
out-of-scope notice *before ever reaching Gemini* - despite
get_conversation_context() already building a full prior-turns transcript for
the prompt. _previous_turn_context() (main.py) re-derives intent/entities from
recent stored user messages in the same session (nothing beyond role+message
is persisted, so there's no new column/table) and fills gaps in the current
turn's entities/intent before routing - see its docstring for the exact
carry-forward rules.

/chat/quick (Choo) is used throughout: it runs this exact pipeline but keeps
history in an in-process dict keyed by session_id instead of Supabase, so
these tests need no database and get the same session isolation for free.
Gemini is faked (no network/quota); RAG, NLU and language detection are real.
"""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


class FakeGemini:
    def __init__(self, reply="OK"):
        self.reply = reply
        self.prompts: list[str] = []

    def generate_content(self, prompt):
        self.prompts.append(prompt)

        class _R:
            text = self.reply

        return _R()


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch):
    fake = FakeGemini()
    monkeypatch.setattr(main, "gemini_model", fake)
    return fake


def ask(session_id, message):
    r = client.post("/chat/quick", json={"session_id": session_id, "message": message})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------- required scenarios ---

def test_passenger_count_followup_resolves_previous_route(_fake_llm):
    """Required test 1: "How much...Colombo to Kandy?" then "What about for 2 people?"."""
    sid = "ctx-passenger-count"
    ask(sid, "How much is a Colombo to Kandy ticket?")
    body = ask(sid, "What about for 2 people?")

    assert body["intent"] == "fare_query"
    assert body["entities"]["from_station"] == "Colombo Fort"
    assert body["entities"]["to_station"] == "Kandy"
    assert body["entities"]["passenger_count"] == 2
    assert body["source"] == "fares.md"  # reached compose_rag_answer, not the off-topic notice


def test_passenger_count_followup_precomputes_group_total_in_code(_fake_llm):
    """FIX 2 (main.py) computes the group total in code rather than asking the
    LLM to multiply - must still apply when the count comes from a follow-up,
    not just when it's in the same message as the route."""
    sid = "ctx-group-total"
    ask(sid, "How much is a Colombo to Kandy ticket?")
    ask(sid, "What about for 2 people?")

    prompt = _fake_llm.prompts[-1]
    assert "Pre-computed total fares for 2 passengers" in prompt
    assert "LKR 5000" in prompt  # 2500 (First Class) x 2
    assert "LKR 2400" in prompt  # 1200 (Second Class) x 2


def test_tomorrow_followup_resolves_previous_route(_fake_llm):
    """Required test 2: "How much...Colombo to Kandy?" then "What about tomorrow?"."""
    sid = "ctx-tomorrow"
    ask(sid, "How much is a Colombo to Kandy ticket?")
    body = ask(sid, "What about tomorrow?")

    assert body["intent"] == "fare_query"
    assert body["entities"]["from_station"] == "Colombo Fort"
    assert body["entities"]["to_station"] == "Kandy"
    assert body["entities"]["travel_date"]  # "tomorrow" still resolved on its own
    assert body["source"] == "fares.md"


def test_new_session_does_not_inherit_previous_sessions_context(_fake_llm):
    """Required isolation test: a brand-new session must not inherit context
    from a completely different, unrelated session."""
    ask("ctx-source-session", "How much is a Colombo to Kandy ticket?")

    body = ask("ctx-fresh-session", "What about for 2 people?")

    assert body["entities"].get("from_station") is None
    assert body["entities"].get("to_station") is None
    # No station context and no self-contained topic -> same as this message
    # would behave with no history at all (the pre-existing off-topic path).
    assert body["intent"] != "fare_query"


# --------------------------------------------------------------- other follow-ups ---

def test_booking_followup_inherits_route_for_prefill(_fake_llm):
    sid = "ctx-booking-followup"
    ask(sid, "How much is a Colombo to Kandy ticket?")
    body = ask(sid, "Can I book it?")

    assert body["intent"] == "booking_request"
    assert body["prefill"]["from_station"] == "Colombo Fort"
    assert body["prefill"]["to_station"] == "Kandy"
    assert body["action"]["type"] == "continue_to_booking"


def test_route_swap_followup_uses_new_stations_and_inherited_intent(_fake_llm):
    """"What about Kandy to Colombo?" names its OWN two stations - those must
    win over the previous turn's route, while the intent (fare_query) still
    carries forward since the message has no fare keyword of its own."""
    sid = "ctx-route-swap"
    ask(sid, "How much is a Colombo to Kandy ticket?")
    body = ask(sid, "What about Kandy to Colombo?")

    assert body["intent"] == "fare_query"
    assert body["entities"]["from_station"] == "Kandy"
    assert body["entities"]["to_station"] == "Colombo Fort"


def test_chained_followups_keep_resolving_the_route(_fake_llm):
    """A follow-up OF a follow-up ("...for 2 people?" then "...and tomorrow?")
    must still resolve - the second follow-up's own raw text has no station
    either, so only looking at the immediately preceding turn would lose the
    route again. _previous_turn_context() scans a short window of recent
    turns for exactly this reason."""
    sid = "ctx-chained"
    ask(sid, "How much is a Colombo to Kandy ticket?")
    ask(sid, "What about for 2 people?")
    body = ask(sid, "What about tomorrow?")

    assert body["intent"] == "fare_query"
    assert body["entities"]["from_station"] == "Colombo Fort"
    assert body["entities"]["to_station"] == "Kandy"


def test_unrelated_intent_in_between_resets_carried_intent(_fake_llm):
    """A complaint between two fare-shaped turns ends the fare topic - a later
    vague follow-up should NOT silently resume being answered as a fare
    question about a route the passenger may no longer be asking about.
    The route itself is still harmless to carry (it doesn't change what gets
    asked/answered), only the intent inheritance is guarded here."""
    sid = "ctx-reset"
    ask(sid, "How much is a Colombo to Kandy ticket?")
    complaint = ask(sid, "The AC in my compartment is broken")
    assert complaint["intent"] == "complaint"

    body = ask(sid, "What about for 2 people?")
    assert body["intent"] != "fare_query"


def test_topic_shift_followup_is_not_forced_into_previous_intent(_fake_llm):
    """"How long does it take?" asks something genuinely different from the
    previous fare question, using the same route - it must NOT be pinned to
    fares.md (source_filter), which likely has no duration content; staying
    "unknown" lets compose_rag_answer search the whole knowledge base while
    still benefiting from the merged-in route for retrieval."""
    sid = "ctx-topic-shift"
    ask(sid, "How much is a Colombo to Kandy ticket?")
    body = ask(sid, "How long does it take?")

    assert body["intent"] == "unknown"
    assert body["entities"]["from_station"] == "Colombo Fort"
    assert body["entities"]["to_station"] == "Kandy"
    assert body["source"] != ""  # reached compose_rag_answer, not the off-topic notice
