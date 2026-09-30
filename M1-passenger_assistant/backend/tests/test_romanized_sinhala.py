"""
Romanized Sinhala ("Singlish") support.

Flow under test: detect_language / classify_intent / extract_entities all
run before any LLM call, and their output decides routing (booking card vs.
RAG vs. Hub) in main.py - so these are the layers that matter for a message
like "mata colomba idala badullata ticket ekak ganna oni". Table-driven unit
tests cover the building blocks in nlu/romanized.py directly; one end-to-end
test drives the actual /chat route (Gemini faked, same pattern as
test_multilingual.py) to prove the whole pipeline reaches a booking action.
"""
import pytest
from fastapi.testclient import TestClient

import main
from nlu.lang_detect import detect_language
from nlu.intent_classifier import classify_intent
from nlu.ner_extractor import extract_entities
from nlu.romanized import is_romanized_sinhala, match_intent, match_stations, normalize

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr(main, "supabase", None)


# --------------------------------------------------------------- normalize ---

@pytest.mark.parametrize("raw,expected", [
    ("oniii", "oni"),
    ("ONI", "oni"),
    ("wenkaranna", "wenkarana"),
    ("colomba", "colomba"),
    ("badullata", "badulata"),
    ("ticket!", "ticket"),
    ("vaadi", "wadi"),  # v -> w fold
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


# ------------------------------------------------------- language detection ---

@pytest.mark.parametrize("message,expected", [
    ("mata colomba idala badullata ticket ekak ganna oni", True),
    ("mata kandy idala colombata welawa kiyada", True),
    ("kochchiya pramadai", True),               # domain word alone, no grammar word
    ("cancel karanna oni", True),
    # negatives - must NOT be mistaken for romanized Sinhala
    ("Is the 14:35 Colombo Fort to Kandy train delayed?", False),
    ("What is the ticket fare from Colombo Fort to Kandy?", False),
    ("mata", False),                            # a single grammar word is too weak alone
    ("", False),
])
def test_is_romanized_sinhala(message, expected):
    assert is_romanized_sinhala(message) is expected


def test_detect_language_returns_si_not_a_new_code():
    # "si", not a separate "si-latn" code - see nlu/lang_detect.py docstring:
    # every language == "si" branch in main.py/i18n.py must already handle it.
    assert detect_language("mata colomba idala badullata ticket ekak ganna oni") == "si"


def test_detect_language_still_prefers_script_over_romanization():
    # A message that has BOTH Sinhala script and Latin Singlish-looking words
    # is still "si" via the (unrelated, pre-existing) unicode-scan path.
    assert detect_language("ticket eka මොකද්ද") == "si"


# ------------------------------------------------------------ intent match ---

@pytest.mark.parametrize("message,expected", [
    ("mata ticket ekak ganna oni", "booking_request"),
    ("colombata ticket ekak book karanna oni", "booking_request"),
    ("kochchiya pramadai", "delay_check"),
    ("kochchiya parakku", "delay_check"),
    ("booking eka cancel karanna", "cancel_booking"),
    ("kandy welawa kiyada", "schedule_query"),  # "welawa" (time) wins - bare "kiyada" is a generic question suffix, not fare-specific
    ("mage baggage eka kadila", "complaint"),
    ("mokakwත් nowe", None),
])
def test_match_intent(message, expected):
    assert match_intent(message) == expected


def test_classify_intent_uses_romanized_lexicon():
    assert classify_intent("mata colomba idala badullata ticket ekak ganna oni") == "booking_request"


def test_classify_intent_falls_through_to_english_keywords_when_mixed():
    # Singlish sentence with an English booking verb and no romanized-lexicon
    # phrase match - the fallback keyword loop (not the romanized one) must
    # still catch it.
    assert classify_intent("mata colombata book karanna oni") == "booking_request"


# --------------------------------------------------------------- stations ---

def test_match_stations_headline_example():
    result = match_stations("mata colomba idala badullata ticket ekak ganna oni")
    by_name = {name: role for name, role, _ in result}
    assert by_name == {"Colombo Fort": "origin", "Badulla": "dest"}


def test_match_stations_dative_suffix_without_particle():
    # "kandyta" has no separate "idala"/"sita" origin particle nearby - the
    # attached dative suffix alone must still resolve the destination role.
    result = match_stations("mata badulla idan kandyta yanna oni")
    by_name = {name: role for name, role, _ in result}
    assert by_name.get("Kandy") == "dest"
    assert by_name.get("Badulla") == "origin"


def test_match_stations_fuzzy_misspelling():
    # "kolombo" is not itself a listed alias (those are colomba/kolamba/
    # colombo/kotuwa) but is edit-distance 1 from "colombo" - must resolve
    # via the fuzzy fallback, not an exact/suffix match.
    result = match_stations("mata kolombo idala badullata ticket ekak ganna oni")
    names = {name for name, _, _ in result}
    assert "Colombo Fort" in names
    assert "Badulla" in names


def test_match_stations_short_token_not_fuzzy_matched():
    # "mata" (4 chars) must never fuzzy-match a short alias like "kandy" - the
    # fuzzy fallback only runs for tokens/aliases of length >= 5.
    result = match_stations("mata oni")
    assert result == []


# ------------------------------------------------------------ extract_entities ---

def test_extract_entities_headline_example():
    entities = extract_entities("mata colomba idala badullata ticket ekak ganna oni")
    assert entities["from_station"] == "Colombo Fort"
    assert entities["to_station"] == "Badulla"
    assert set(entities["stations"]) == {"Colombo Fort", "Badulla"}


def test_extract_entities_llm_fallback_fires_below_two_stations(monkeypatch):
    # Regression guard for the ner_extractor.py fix: the LLM station fallback
    # must run whenever fewer than two stations were found by the alias/
    # romanized scan - not only when zero were found - so a message that
    # resolves just one station still gets a chance at the second.
    from nlu import ner_extractor

    calls = []

    def fake_llm_extract(text):
        calls.append(text)
        return ["Kandy"]

    monkeypatch.setattr(ner_extractor, "_llm_extract_stations", fake_llm_extract)
    entities = ner_extractor.extract_entities("some unrelated text mentioning badulla only")
    assert calls, "LLM fallback should have been invoked with fewer than 2 stations found"
    assert "Kandy" in entities["stations"]


# --------------------------------------------------------------- end to end ---

class FakeGemini:
    def __init__(self, reply):
        self.reply, self.prompt, self.calls = reply, None, 0

    def generate_content(self, prompt):
        self.calls += 1
        self.prompt = prompt

        class _R:
            text = self.reply

        return _R()


def test_chat_route_romanized_booking_request_returns_booking_action(monkeypatch):
    monkeypatch.setattr(main, "gemini_model", FakeGemini("(unused for booking_request)"))

    r = client.post("/chat", json={
        "message": "mata colomba idala badullata ticket ekak ganna oni",
        "session_id": "test-singlish-session",
    })
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["language"] == "si"
    assert body["intent"] == "booking_request"
    assert body["prefill"]["from_station"] == "Colombo Fort"
    assert body["prefill"]["to_station"] == "Badulla"
    assert body["action"]["type"] == "continue_to_booking"


def test_chat_route_romanized_fare_query_prompts_gemini_in_sinhala_script(monkeypatch):
    fake = FakeGemini("කොළඹ කොටුව සිට මහනුවර දක්වා: LKR 2500.")
    monkeypatch.setattr(main, "gemini_model", fake)

    r = client.post("/chat", json={
        "message": "mata kandy idala colombata welawa kiyada",
        "session_id": "test-singlish-session-2",
    })
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["language"] == "si"
    assert fake.calls == 1
    # The prompt sent to Gemini must tell it the input was romanized and to
    # reply in Sinhala script anyway (see main.py::_language_prompt_block).
    assert "romanized Sinhala" in fake.prompt
