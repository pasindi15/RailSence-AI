"""
Multilingual final answers: Sinhala question -> Sinhala answer, Tamil -> Tamil,
English -> English.

Flow under test:  detect language -> intent/NER -> RAG -> Gemini (prompt carries
the detected language) -> reply returned exactly as Gemini wrote it. If Gemini is
unavailable, the fallback is in the passenger's language (not English).

Gemini is faked (no network/quota); RAG, NLU and language detection are real.
"""
import pytest
from fastapi.testclient import TestClient

import main
from nlu.lang_detect import detect_language

client = TestClient(main.app)

SI_Q = "කොළඹ ඉඳන් මහනුවරට ticket එක කීයද?"
TA_Q = "கொழும்பு கோட்டையிலிருந்து கண்டிக்கு ரயில் கட்டணம் எவ்வளவு?"
EN_Q = "What is the ticket fare from Colombo Fort to Kandy?"

SI_ANSWER = "කොළඹ කොටුව සිට මහනුවර දක්වා: පළමු පන්තිය ආසනයකට LKR 2500, දෙවන පන්තිය ආසනයකට LKR 1200."
TA_ANSWER = "கொழும்பு கோட்டையிலிருந்து கண்டிக்கு: முதல் வகுப்பு LKR 2500, இரண்டாம் வகுப்பு LKR 1200."
EN_ANSWER = "Colombo Fort to Kandy: First Class LKR 2500, Second Class LKR 1200 per seat."


class FakeGemini:
    def __init__(self, reply):
        self.reply, self.prompt, self.calls = reply, None, 0

    def generate_content(self, prompt):
        self.calls += 1
        self.prompt = prompt

        class _R:
            text = self.reply

        return _R()


class BrokenGemini:
    """Simulates the 429 quota error seen in production."""

    def __init__(self):
        self.calls = 0

    def generate_content(self, prompt):
        self.calls += 1
        raise RuntimeError("429 You exceeded your current quota")


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr(main, "supabase", None)


def chat(message):
    r = client.post("/chat", json={"message": message})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------ language detection ---

@pytest.mark.parametrize("message,expected", [
    (SI_Q, "si"),               # Sinhala with an embedded English word ("ticket")
    (TA_Q, "ta"),
    (EN_Q, "en"),
    ("ticket එක", "si"),         # mixed: any Sinhala script wins over the English word
    ("PM-4082 ரயில் தாமதமா?", "ta"),
])
def test_language_detection(message, expected):
    assert detect_language(message) == expected


# --------------------------------------- language reaches Gemini, RAG grounds ---

@pytest.mark.parametrize("message,code,name,answer", [
    (SI_Q, "si", "Sinhala", SI_ANSWER),
    (TA_Q, "ta", "Tamil", TA_ANSWER),
    (EN_Q, "en", "English", EN_ANSWER),
])
def test_gemini_is_called_with_detected_language_and_rag_context(monkeypatch, message, code, name, answer):
    fake = FakeGemini(answer)
    monkeypatch.setattr(main, "gemini_model", fake)

    body = chat(message)

    assert body["language"] == code and body["intent"] == "fare_query"
    assert fake.calls == 1, "Gemini must generate the final answer"
    # detected language is explicit in the prompt
    assert f"Detected passenger language: {name} ({code})" in fake.prompt
    assert "You must answer the passenger in the detected language." in fake.prompt
    assert LANG_RULE[code] in fake.prompt
    assert f"Respond only in {name}." in fake.prompt
    # grounding: the retrieved fare section (from the booking-system table) is in the prompt
    assert "LKR 2500 per seat" in fake.prompt and "LKR 1200 per seat" in fake.prompt
    assert "Colombo Fort - Kandy" in fake.prompt
    assert "state railway facts ONLY from the retrieved" in fake.prompt
    # the reply is Gemini's own answer, returned unmodified (no post-translation, no raw RAG dump)
    assert body["reply"] == answer
    assert "Here's what I found" not in body["reply"] and "{" not in body["reply"]
    assert body["source"] == "fares.md"


LANG_RULE = {"si": "Answer completely in Sinhala.", "ta": "Answer completely in Tamil.", "en": "Answer in English."}


def test_sinhala_mixed_message_resolves_the_full_route():
    """Bare "කොළඹ"/"கொழும்பு" must resolve to Colombo Fort, otherwise only Kandy is
    found and the fare context is built from a one-station query."""
    assert chat(SI_Q)["entities"]["stations"] == ["Colombo Fort", "Kandy"]
    assert chat(TA_Q)["entities"]["stations"] == ["Colombo Fort", "Kandy"]


def test_language_reaches_the_prompt_for_schedule_questions_too(monkeypatch):
    fake = FakeGemini("සිංහල පිළිතුර")
    monkeypatch.setattr(main, "gemini_model", fake)
    body = chat("කොළඹ සිට මහනුවර දුම්රිය වේලාව මොකක්ද?")
    assert body["language"] == "si" and body["intent"] == "schedule_query"
    assert "Answer completely in Sinhala." in fake.prompt
    assert "[schedules.md]" in fake.prompt and body["reply"] == "සිංහල පිළිතුර"


def test_legitimate_sinhala_railway_question_is_not_declined_as_out_of_scope(monkeypatch):
    """The English-only embedding distance cannot judge Sinhala/Tamil (this one
    measures ~1.87); a question with railway vocabulary must still reach Gemini."""
    fake = FakeGemini("සිංහල පිළිතුර")
    monkeypatch.setattr(main, "gemini_model", fake)
    body = chat("ගමන් බඩු කොච්චර ගෙනියන්න පුළුවන්ද?")
    assert body["language"] == "si" and body["intent"] != "out_of_scope"
    assert fake.calls == 1 and body["reply"] == "සිංහල පිළිතුර"


def test_non_railway_sinhala_and_tamil_questions_still_get_the_service_notice(monkeypatch):
    fake = FakeGemini("must not be used")
    monkeypatch.setattr(main, "gemini_model", fake)
    assert chat("ලන්ඩන් හි කාලගුණය කුමක්ද?")["reply"] == main.OUT_OF_SCOPE_REPLIES["si"]
    assert chat("லண்டனில் வானிலை என்ன?")["reply"] == main.OUT_OF_SCOPE_REPLIES["ta"]
    assert fake.calls == 0


# ------------------------------------------------ language-aware fallback ---

def _assert_no_english_template(reply):
    assert "Here's what I found" not in reply and "Here's what is available" not in reply
    assert "per seat" not in reply and "##" not in reply


@pytest.mark.parametrize("message,code,expected_words", [
    (SI_Q, "si", ["කොළඹ කොටුව - මහනුවර", "පළමු පන්තිය", "දෙවන පන්තිය", "LKR 2500", "LKR 1200", "ආසනයකට"]),
    (TA_Q, "ta", ["கொழும்பு கோட்டை - கண்டி", "முதல் வகுப்பு", "இரண்டாம் வகுப்பு", "LKR 2500", "LKR 1200", "இருக்கைக்கு"]),
])
def test_gemini_failure_falls_back_in_the_passengers_language(monkeypatch, message, code, expected_words):
    broken = BrokenGemini()
    monkeypatch.setattr(main, "gemini_model", broken)

    reply = chat(message)["reply"]

    assert broken.calls == 1, "the error path must still have tried Gemini first"
    _assert_no_english_template(reply)
    for word in expected_words:
        assert word in reply, f"{word!r} missing from fallback: {reply!r}"


def test_english_fallback_is_unchanged(monkeypatch):
    monkeypatch.setattr(main, "gemini_model", BrokenGemini())
    reply = chat(EN_Q)["reply"]
    assert reply.startswith("Here's what I found:")
    assert "First Class: LKR 2500 per seat" in reply


def test_fallback_without_gemini_configured_is_also_localized(monkeypatch):
    monkeypatch.setattr(main, "gemini_model", None)
    reply = chat(SI_Q)["reply"]
    _assert_no_english_template(reply)
    assert "LKR 1200" in reply


def test_empty_gemini_response_falls_back_instead_of_showing_nothing(monkeypatch):
    monkeypatch.setattr(main, "gemini_model", FakeGemini("   "))
    reply = chat(SI_Q)["reply"]
    assert reply.strip() and "LKR 1200" in reply
    _assert_no_english_template(reply)


def test_group_fare_fallback_is_localized_and_multiplied_in_code(monkeypatch):
    monkeypatch.setattr(main, "gemini_model", BrokenGemini())
    reply = chat("කොළඹ ඉඳන් මහනුවරට 2 passengers ticket එක කීයද?")["reply"]
    assert "LKR 1200 × 2 = LKR 2400" in reply and "LKR 2500 × 2 = LKR 5000" in reply
    _assert_no_english_template(reply)
    assert "passengers" not in reply


def test_class_filtered_fallback_is_localized(monkeypatch):
    monkeypatch.setattr(main, "gemini_model", BrokenGemini())
    reply = chat("කොළඹ ඉඳන් මහනුවරට first class ticket එක කීයද?")["reply"]
    assert "පළමු පන්තිය" in reply and "LKR 2500" in reply
    assert "LKR 1200" not in reply  # only the class that was asked about
    _assert_no_english_template(reply)


def test_policy_fallback_in_sinhala_and_tamil_says_it_is_english_only_not_silently_english(monkeypatch):
    monkeypatch.setattr(main, "gemini_model", BrokenGemini())
    si = chat("How much luggage can I carry? ඒක සිංහලෙන් කියන්න")  # Sinhala present -> si
    assert si["language"] == "si" and si["intent"] == "policy_query"
    assert main.FALLBACK_STRINGS["si"]["english_only_notice"] in si["reply"]
    assert "25kg" in si["reply"]  # the fact is still there, grounded in policies.md
    assert "Here's what I found" not in si["reply"]

    ta = chat("How much luggage can I carry? தமிழில் சொல்லுங்கள்")
    assert ta["language"] == "ta"
    assert main.FALLBACK_STRINGS["ta"]["english_only_notice"] in ta["reply"]


# ------------------------------------------ prompt/grounding rules present ---

def test_grounding_rules_forbid_changing_facts_or_leaking_internals(monkeypatch):
    fake = FakeGemini(EN_ANSWER)
    monkeypatch.setattr(main, "gemini_model", fake)
    chat(EN_Q)
    for rule in (
        "never invent or change a fare, train number, time, delay or route",
        "currency amounts (e.g. LKR 2500) exactly as given",
        "do not output JSON",
        "Do not mention the knowledge base, agents",
    ):
        assert rule in fake.prompt
    assert "Answer in English." in fake.prompt  # English behaviour intact


def test_system_prompt_states_the_language_rules():
    text = main.SYSTEM_PROMPT
    assert "Answer completely in Sinhala" in text
    assert "train IDs, booking references" in text and "never change a fare" in text
