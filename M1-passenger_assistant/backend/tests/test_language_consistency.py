"""
System-wide language consistency: whatever the intent or agent, the passenger's
reply is in the language of the passenger's question (Sinhala -> Sinhala,
Tamil -> Tamil, English -> English).

Real: language detection, NER, intent classification, RAG index, /chat.
Faked: the Hub transport (records every envelope) and Gemini (records the prompt).
The knowledge base stays English - only the answer's language changes.
"""
import re
import string

import pytest
from fastapi.testclient import TestClient

import hub_client
import main
from i18n import MESSAGES, t
from nlu import ner_extractor
from nlu.intent_classifier import classify_intent
from nlu.lang_detect import detect_language

client = TestClient(main.app)

SI = re.compile(r"[඀-෿]")
TA = re.compile(r"[஀-௿]")
LANG_NAME = {"si": "Sinhala", "ta": "Tamil", "en": "English"}

# The 15 questions (5 intents x 3 languages) from the requirements.
QUESTIONS = {
    "si": {
        "fare": "කොළඹ ඉඳන් මහනුවරට ටිකට් එක කීයද?",
        "schedule": "කොළඹ කොටුවෙන් මහනුවරට යන දුම්රිය මොනවාද?",
        "delay": "කොළඹ කොටුවෙන් මහනුවරට යන දුම්රිය ප්‍රමාද වෙලාද?",
        "book_no_origin": "මට මහනුවරට ටිකට් එකක් වෙන්කරගන්න පුළුවන්ද?",
        "book_full": "මට කොළඹ කොටුවෙන් මහනුවරට ටිකට් එකක් වෙන්කරන්න ඕන.",
    },
    "en": {
        "fare": "What is the ticket fare from Colombo Fort to Kandy?",
        "schedule": "What trains run from Colombo Fort to Kandy?",
        "delay": "Is the train from Colombo Fort to Kandy delayed?",
        "book_no_origin": "Can I book a ticket to Kandy?",
        "book_full": "I want to book a ticket from Colombo Fort to Kandy.",
    },
    "ta": {
        "fare": "கொழும்பு கோட்டையிலிருந்து கண்டிக்கு ரயில் கட்டணம் எவ்வளவு?",
        "schedule": "கொழும்பு கோட்டையிலிருந்து கண்டிக்கு செல்லும் ரயில்கள் என்ன?",
        "delay": "கொழும்பு கோட்டையிலிருந்து கண்டிக்கு செல்லும் ரயில் தாமதமாகியுள்ளதா?",
        "book_no_origin": "கண்டிக்கு ஒரு டிக்கெட் முன்பதிவு செய்ய முடியுமா?",
        "book_full": "கொழும்பு கோட்டையிலிருந்து கண்டிக்கு ஒரு டிக்கெட் முன்பதிவு செய்ய வேண்டும்.",
    },
}
INTENT = {"fare": "fare_query", "schedule": "schedule_query", "delay": "delay_check",
          "book_no_origin": "booking_request", "book_full": "booking_request"}
CASES = [(lang, kind, q) for lang, qs in QUESTIONS.items() for kind, q in qs.items()]
IDS = [f"{lang}-{kind}" for lang, kind, _ in CASES]

# Canned Gemini answers per language (they contain the facts guards look for).
GEMINI_REPLY = {
    "si": "IC-8746 දුම්රිය මිනිත්තු 6.8 ක් ප්‍රමාද විය හැක (ඉතිහාස වාර්තාව; සජීවී තත්ත්වයක් නොවේ).",
    "ta": "IC-8746 ரயில் 6.8 நிமிடங்கள் தாமதமாகலாம் (வரலாற்றுப் பதிவு; நேரடி நிலை அல்ல).",
    "en": "IC-8746 may be about 6.8 minutes late.",
}


def in_language(reply: str, lang: str) -> bool:
    """Sinhala reply contains Sinhala script (and no Tamil); Tamil likewise; an
    English reply contains no Sinhala/Tamil script at all."""
    if lang == "si":
        return bool(SI.search(reply)) and not TA.search(reply)
    if lang == "ta":
        return bool(TA.search(reply)) and not SI.search(reply)
    return not SI.search(reply) and not TA.search(reply)


class SmartGemini:
    """Answers in whatever language the prompt says was detected; records prompts."""

    def __init__(self, replies=None):
        self.replies = replies or GEMINI_REPLY
        self.prompts = []

    def generate_content(self, prompt):
        self.prompts.append(prompt)
        lang = next(c for c, n in LANG_NAME.items() if f"Detected passenger language: {n} ({c})" in prompt)

        class _R:
            text = self.replies[lang]

        return _R()

    @property
    def calls(self):
        return len(self.prompts)


class BrokenGemini:
    calls = 0

    def generate_content(self, prompt):
        type(self).calls += 1
        raise RuntimeError("429 quota exceeded")


class HubSpy:
    """Records every envelope. `response` answers every call; `per_agent` maps a
    receiver agent name to its own response (like the real Hub routing)."""

    def __init__(self, response=None, per_agent=None):
        self.sent, self._response, self._per_agent = [], response, per_agent or {}

    async def __call__(self, message):
        self.sent.append(message)
        if message.receiver_agent in self._per_agent:
            return self._per_agent[message.receiver_agent]
        return self._response if self._response is not None else hub_client.send_to_hub_mock(message)

    def to(self, agent):
        return [m for m in self.sent if m.receiver_agent == agent]


def ops_ok(**extra):
    payload = dict(predicted_delay_minutes=6.8, model_version="historical-observation-v1",
                   retrieval_method="historical_record",
                   reason="Historical observation for IC-8746: 6.8 minutes on Colombo Fort - Kandy.",
                   similar_incident="weather at Kandy (historical delay 6.8 min).")
    payload.update(extra)
    return hub_client.HubResponse(status="ok", sender_agent="operations-agent", payload=payload)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(main, "supabase", None)
    monkeypatch.setattr(ner_extractor, "_llm_model", None)
    monkeypatch.setattr(main, "search_trains", lambda a, b: [{"train_id": "IC-8746", "train_name": "Intercity Express"}])
    hub = HubSpy()
    monkeypatch.setattr(main, "send_to_hub", hub)
    llm = SmartGemini()
    monkeypatch.setattr(main, "gemini_model", llm)
    return llm, hub


def chat(message):
    r = client.post("/chat", json={"message": message})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------- 1. language + intent + NER ---

@pytest.mark.parametrize("lang,kind,question", CASES, ids=IDS)
def test_detected_language_and_intent_for_all_fifteen_questions(lang, kind, question):
    assert detect_language(question) == lang
    assert classify_intent(question) == INTENT[kind]


@pytest.mark.parametrize("lang", ["si", "en", "ta"])
def test_booking_origin_and_destination_are_never_swapped_or_guessed(lang):
    e = ner_extractor.extract_entities(QUESTIONS[lang]["book_no_origin"])
    assert (e["from_station"], e["to_station"]) == (None, "Kandy")  # destination only; origin NOT guessed
    e = ner_extractor.extract_entities(QUESTIONS[lang]["book_full"])
    assert (e["from_station"], e["to_station"]) == ("Colombo Fort", "Kandy")
    e = ner_extractor.extract_entities(QUESTIONS[lang]["fare"])
    assert (e["from_station"], e["to_station"]) == ("Colombo Fort", "Kandy")


@pytest.mark.parametrize("text,origin,dest", [
    ("Kandy to Colombo Fort fare", "Kandy", "Colombo Fort"),          # direction follows the wording
    ("book from Kandy", "Kandy", None),                               # origin only -> destination NOT guessed
    ("from Galle to Badulla", "Galle", "Badulla"),
    ("ගාල්ලෙන් මහනුවරට යන්න ඕන", "Galle", "Kandy"),
    ("கொழும்பிலிருந்து யாழ்ப்பாணத்துக்கு டிக்கெட்", "Colombo Fort", "Jaffna"),
    ("Kandy train schedule", None, None),                             # unmarked single station: unassigned
])
def test_station_roles_come_from_direction_markers_not_from_dictionary_order(text, origin, dest):
    e = ner_extractor.extract_entities(text)
    assert (e["from_station"], e["to_station"]) == (origin, dest)


# --------------------------- 2. RAG intents: Gemini gets the language + context ---

@pytest.mark.parametrize("lang", ["si", "en", "ta"])
@pytest.mark.parametrize("kind,doc", [("fare", "fares.md"), ("schedule", "schedules.md")])
def test_rag_answers_reach_gemini_in_the_detected_language_and_are_returned_unchanged(lang, kind, doc, _isolate):
    llm, hub = _isolate
    body = chat(QUESTIONS[lang][kind])
    assert body["language"] == lang and body["intent"] == INTENT[kind]
    assert llm.calls == 1
    prompt = llm.prompts[0]
    assert f"Detected passenger language: {LANG_NAME[lang]} ({lang})" in prompt
    assert f"[{doc}]" in prompt                      # English RAG context, NOT translated
    assert "Here's what I found" not in body["reply"]
    assert body["reply"] == GEMINI_REPLY[lang] and in_language(body["reply"], lang)
    assert hub.sent == []


# ------------------------------------------ 3. schedule: fallback in the language ---

@pytest.mark.parametrize("lang,label", [("si", "පිටත්වීම"), ("ta", "புறப்பாடு")])
def test_schedule_fallback_is_not_forced_into_english(lang, label, monkeypatch):
    monkeypatch.setattr(main, "gemini_model", BrokenGemini())
    reply = chat(QUESTIONS[lang]["schedule"])["reply"]
    assert in_language(reply.replace("Podi Menike", "").replace("Udarata Menike", "").replace("Intercity Express", "")
                       .replace("Main Line", "").replace("Colombo Fort", "").replace("Kandy", ""), lang)
    assert label in reply
    assert "Podi Menike (1005)" in reply and "05:55" in reply and "08:47" in reply   # data copied, not invented
    assert "Colombo Fort" not in reply and "Kandy" not in reply                       # heading + places localized too
    assert "Here's what I found" not in reply and "departs" not in reply.lower()


def test_english_schedule_fallback_is_unchanged(monkeypatch):
    monkeypatch.setattr(main, "gemini_model", BrokenGemini())
    reply = chat(QUESTIONS["en"]["schedule"])["reply"]
    assert reply.startswith("Here's what I found:") and "departs 05:55" in reply


# ------------------------------------------------------------------ 4. booking ---

@pytest.mark.parametrize("lang", ["si", "en", "ta"])
def test_booking_with_missing_origin_asks_in_the_passengers_language(lang, _isolate):
    llm, hub = _isolate
    body = chat(QUESTIONS[lang]["book_no_origin"])
    assert body["intent"] == "booking_request"
    assert body["prefill"] == {"to_station": "Kandy"}        # origin absent, not guessed
    assert hub.sent == [] and llm.calls == 0                 # nothing to book yet -> ask, don't call
    assert in_language(body["reply"], lang)
    assert body["reply"] == t("booking_ask_origin", lang, destination=main._disp("Kandy", lang))
    assert body["action"]["label"] == t("label_continue_booking", lang)


def test_the_sinhala_clarifying_question_matches_the_required_wording():
    assert chat(QUESTIONS["si"]["book_no_origin"])["reply"] == "ඔබ කොතැනින් මහනුවරට යාමට ටිකට් වෙන්කරගන්නද?"
    assert chat(QUESTIONS["en"]["book_no_origin"])["reply"] == "Which station would you like to travel from to Kandy?"


@pytest.mark.parametrize("lang", ["si", "en", "ta"])
def test_booking_with_both_stations_calls_the_booking_agent_with_language(lang, monkeypatch, _isolate):
    _, hub = _isolate
    monkeypatch.setattr(main, "send_to_hub", HubSpy(hub_client.HubResponse(status="error", error_kind="rejected")))
    spy = main.send_to_hub
    body = chat(QUESTIONS[lang]["book_full"])
    sent = spy.to("booking-agent")[0]
    assert sent.payload["from_station"] == "Colombo Fort" and sent.payload["to_station"] == "Kandy"
    assert sent.payload["language"] == lang
    assert in_language(body["reply"], lang) and body["action"]["type"] == "continue_to_booking"
    if lang == "en":
        assert body["reply"].startswith("I found your booking request from **Colombo Fort** to **Kandy**")


@pytest.mark.parametrize("lang,question,ref_word", [
    ("si", "RS-12345 වෙන්කිරීම අවලංගු කරන්න", "RS-12345"),
    ("ta", "RS-12345 முன்பதிவு ரத்து", "RS-12345"),
    ("en", "Cancel my booking RS-12345", "RS-12345"),
])
def test_cancellation_card_text_and_label_follow_the_language(lang, question, ref_word):
    body = chat(question)
    assert body["intent"] == "cancel_booking" and ref_word in body["reply"]
    assert in_language(body["reply"].replace("RS-12345", ""), lang)
    assert body["action"]["label"] == t("label_send_cancellation", lang)
    assert body["action"]["reason"]  # API value for the Booking Agent is untouched


@pytest.mark.parametrize("lang", ["si", "ta", "en"])
def test_cancellation_without_a_reference_asks_for_it_in_the_language(lang):
    q = {"si": "මගේ ටිකට් එක අවලංගු කරන්න", "ta": "என் டிக்கெட்டை ரத்து செய்ய வேண்டும்", "en": "cancel my ticket please"}[lang]
    body = chat(q)
    assert body["intent"] == "cancel_booking" and in_language(body["reply"], lang)
    assert "Reference Required" not in body["reply"]


# ----------------------------------------------------- 5. delay / Operations ---

@pytest.mark.parametrize("lang", ["si", "ta"])
def test_operations_result_is_written_by_gemini_in_the_passengers_language(lang, monkeypatch, _isolate):
    llm, _ = _isolate
    spy = HubSpy(ops_ok())
    monkeypatch.setattr(main, "send_to_hub", spy)

    body = chat(QUESTIONS[lang]["delay"])

    op = spy.to("operations-agent")[0]
    assert op.payload["language"] == lang and op.payload["train_id"] == "IC-8746"   # language travels with the request
    assert body["delay_minutes"] == 6.8 and "Operations Agent" in body["source"]
    assert body["reply"] == GEMINI_REPLY[lang] and in_language(body["reply"], lang)
    prompt = llm.prompts[0]
    assert f"Detected passenger language: {LANG_NAME[lang]} ({lang})" in prompt
    assert "delay_minutes: 6.8" in prompt and "NOT a live status" in prompt        # facts + honesty about history
    assert "IC-8746" in prompt


def test_english_operations_reply_is_the_unchanged_deterministic_text(monkeypatch, _isolate):
    llm, _ = _isolate
    monkeypatch.setattr(main, "send_to_hub", HubSpy(ops_ok()))
    body = chat(QUESTIONS["en"]["delay"])
    assert body["reply"].startswith("Expected delay: 6.8 minutes (based on this train's recorded history, not a live status).")
    assert llm.calls == 0


@pytest.mark.parametrize("lang,headline", [("si", "අපේක්ෂිත ප්‍රමාදය: මිනිත්තු 6.8"), ("ta", "எதிர்பார்க்கப்படும் தாமதம்: 6.8 நிமிடங்கள்")])
def test_operations_reply_falls_back_to_a_localized_template_if_gemini_fails(lang, headline, monkeypatch):
    monkeypatch.setattr(main, "gemini_model", BrokenGemini())
    monkeypatch.setattr(main, "send_to_hub", HubSpy(ops_ok()))
    reply = chat(QUESTIONS[lang]["delay"])["reply"]
    assert reply.startswith(headline) and "6.8" in reply
    assert "Expected delay" not in reply
    # Operations' English free text (explanation / incident notes) is not pasted into a Sinhala/Tamil reply
    assert "Historical" not in reply and "Kandy" not in reply and in_language(reply, lang)


@pytest.mark.parametrize("bad_reply", [
    "මිනිත්තු 10 ක් ප්‍රමාදයි",          # right language, but the delay figure/train ID were changed
    "The train is about 6.8 minutes late IC-8746",   # right facts, wrong language
])
def test_a_gemini_reply_that_changes_facts_or_language_is_rejected(bad_reply, monkeypatch):
    class Wrong:
        def generate_content(self, prompt):
            class _R:
                text = bad_reply
            return _R()

    monkeypatch.setattr(main, "gemini_model", Wrong())
    monkeypatch.setattr(main, "send_to_hub", HubSpy(ops_ok()))
    reply = chat(QUESTIONS["si"]["delay"])["reply"]
    assert reply.startswith("අපේක්ෂිත ප්‍රමාදය: මිනිත්තු 6.8")       # localized template, grounded values


@pytest.mark.parametrize("lang", ["si", "ta", "en"])
def test_operations_unreachable_is_a_truthful_error_in_the_passengers_language(lang, monkeypatch):
    monkeypatch.setattr(main, "send_to_hub", HubSpy(hub_client.HubResponse(status="error", error_kind="unreachable")))
    reply = chat(QUESTIONS[lang]["delay"])["reply"]
    assert reply == main.DELAY_UNREACHABLE_REPLIES[lang] and in_language(reply, lang)
    assert "delay" not in reply.lower() or lang == "en"      # no invented delay data


@pytest.mark.parametrize("lang", ["si", "ta", "en"])
def test_operations_rejecting_the_request_is_reported_differently_from_unreachable(lang, monkeypatch):
    monkeypatch.setattr(main, "send_to_hub", HubSpy(hub_client.HubResponse(status="error", error_kind="rejected")))
    reply = chat(QUESTIONS[lang]["delay"])["reply"]
    assert reply == t("agent_rejected", lang) and in_language(reply, lang)


@pytest.mark.parametrize("lang,question", [("si", "දුම්රිය ප්‍රමාදද?"), ("ta", "ரயில் தாமதமா?"), ("en", "Is the train delayed?")])
def test_missing_train_id_keeps_the_sentinel_and_localizes_the_sentence(lang, question, monkeypatch):
    monkeypatch.setattr(main, "search_trains", lambda a, b: [])
    reply = chat(question)["reply"]
    assert reply.startswith("TRAIN_NOT_FOUND:") and in_language(reply.replace("PM-4082", ""), lang) or lang == "en"
    assert reply == f"TRAIN_NOT_FOUND: {t('delay_need_train_id', lang)}"


# ---------------------------------------- 6. other agents: complaint / status / info ---

@pytest.mark.parametrize("lang,question", [
    ("si", "මගේ මැදිරියේ ඒසී එක කැඩිලා"), ("ta", "என் பெட்டியில் ஏசி உடைந்த பிரச்சனை"), ("en", "The AC is broken in my compartment")])
def test_complaint_ticket_reply_is_in_the_language_and_keeps_the_ticket_id(lang, question, monkeypatch, _isolate):
    llm, _ = _isolate
    spy = HubSpy()
    monkeypatch.setattr(main, "send_to_hub", spy)
    ticket = None
    # SmartGemini's canned text does not contain the ticket, so the guard must fall back to the template
    body = chat(question)
    assert body["intent"] == "complaint" and "Maintenance Agent" in body["source"]
    assert spy.to("maintenance-agent")[0].payload["language"] == lang
    m = re.search(r"MT-[A-Z0-9]+", body["reply"])
    assert m, body["reply"]
    assert in_language(body["reply"].replace(m.group(0), ""), lang) or lang == "en"


@pytest.mark.parametrize("lang", ["si", "ta", "en"])
def test_complaint_when_maintenance_is_down_is_a_localized_error(lang, monkeypatch):
    monkeypatch.setattr(main, "send_to_hub", HubSpy(hub_client.HubResponse(status="error", error_kind="unreachable")))
    q = {"si": "මගේ මැදිරියේ ඒසී එක කැඩිලා", "ta": "என் பெட்டியில் ஏசி உடைந்த பிரச்சனை", "en": "The AC is broken in my compartment"}[lang]
    reply = chat(q)["reply"]
    assert reply == t("agent_unreachable", lang) and in_language(reply, lang)


@pytest.mark.parametrize("lang,question", [
    ("si", "PM-4082 දුම්රිය ධාවනය වෙනවාද?"), ("ta", "PM-4082 ரயில் இயங்குகிறதா?"), ("en", "Is PM-4082 train running?")])
def test_train_status_from_maintenance_is_localized(lang, question, monkeypatch):
    monkeypatch.setattr(main, "get_train", lambda tid: {"train_id": tid})
    monkeypatch.setattr(main, "gemini_model", BrokenGemini())     # force the deterministic localized template
    monkeypatch.setattr(main, "send_to_hub", HubSpy(hub_client.HubResponse(status="ok", payload={
        "train_id": "PM-4082", "under_maintenance": True, "reason": "brake inspection",
        "estimated_clear": "2026-12-04",
        "message": "Train PM-4082 is currently under maintenance and may not be in service. "
                   "Reason: brake inspection. Expected back in service by 2026-12-04. We apologise for the inconvenience."})))
    body = chat(question)
    assert body["intent"] == "train_status"
    assert "PM-4082" in body["reply"] and "brake inspection" in body["reply"] and "2026-12-04" in body["reply"]
    assert in_language(body["reply"].replace("brake inspection", "").replace("PM-4082", "").replace("2026-12-04", ""), lang)


@pytest.mark.parametrize("lang,question", [
    ("si", "PM-4082 දුම්රිය විස්තර"), ("ta", "PM-4082 ரயில் விவரங்கள்"), ("en", "PM-4082 train details")])
def test_train_info_from_the_registry_is_localized(lang, question, monkeypatch):
    monkeypatch.setattr(main, "get_train", lambda tid: {"train_id": tid, "train_name": "Podi Menike", "route": "Colombo Fort - Kandy",
                                                        "active": True, "maintenance_status": "OPERATIONAL"})
    monkeypatch.setattr(main, "get_train_schedule", lambda tid: [])
    monkeypatch.setattr(main, "gemini_model", BrokenGemini())
    reply = chat(question)["reply"]
    assert "PM-4082" in reply and "Podi Menike" in reply and "OPERATIONAL" in reply
    if lang == "en":
        assert reply == "Podi Menike (PM-4082) is active. Route: Colombo Fort - Kandy. Maintenance status: OPERATIONAL."
    else:
        assert in_language(reply.replace("Podi Menike", "").replace("PM-4082", "").replace("Colombo Fort - Kandy", "")
                           .replace("OPERATIONAL", ""), lang)


@pytest.mark.parametrize("lang", ["si", "ta", "en"])
def test_registry_down_and_unknown_train_are_localized(lang, monkeypatch):
    q = {"si": "PM-4082 දුම්රිය විස්තර", "ta": "PM-4082 ரயில் விவரங்கள்", "en": "PM-4082 train details"}[lang]
    monkeypatch.setattr(main, "get_train", lambda tid: None)
    reply = chat(q)["reply"]
    assert reply.startswith("TRAIN_NOT_FOUND:") and t("train_not_found_registry", lang, train_id="PM-4082") in reply

    def down(tid):
        raise main.TrainRepositoryUnavailable("down")

    monkeypatch.setattr(main, "get_train", down)
    reply = chat(q)["reply"]
    assert reply == t("registry_unavailable", lang) and in_language(reply, lang)


# ------------------------------------------- 7. RAG / LLM failure, fallbacks ---

@pytest.mark.parametrize("lang", ["si", "ta", "en"])
def test_rag_failure_message_is_localized_and_hides_the_internal_error(lang, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("chromadb exploded: internal detail")

    monkeypatch.setattr(main, "retrieve_faq_chunks", boom)
    reply = chat(QUESTIONS[lang]["fare"])["reply"]
    assert reply == t("rag_error", lang) and in_language(reply, lang)
    assert "chromadb" not in reply and "internal" not in reply


@pytest.mark.parametrize("lang", ["si", "ta", "en"])
def test_llm_failure_fare_answer_is_still_in_the_language(lang, monkeypatch):
    monkeypatch.setattr(main, "gemini_model", BrokenGemini())
    reply = chat(QUESTIONS[lang]["fare"])["reply"]
    assert "LKR 2500" in reply and "LKR 1200" in reply
    assert in_language(reply.replace("LKR", "").replace("Colombo Fort - Kandy", ""), lang) or lang == "en"
    if lang != "en":
        assert "Here's what I found" not in reply and "per seat" not in reply


# ---------------------------------- 8. language reaches every Hub payload ---

def test_every_hub_call_carries_the_detected_language(monkeypatch):
    spy = HubSpy(per_agent={
        "operations-agent": ops_ok(),
        "maintenance-agent": hub_client.HubResponse(status="ok", payload={
            "ticket_id": "MT-ABC123", "message": "Issue logged.", "train_id": "PM-4082",
            "under_maintenance": False, "found": True}),
        "booking-agent": hub_client.HubResponse(status="error", error_kind="rejected"),
    })
    monkeypatch.setattr(main, "send_to_hub", spy)
    monkeypatch.setattr(main, "get_train", lambda tid: {"train_id": tid})
    monkeypatch.setattr(main, "gemini_model", None)
    for q in (QUESTIONS["si"]["delay"], "PM-4082 දුම්රිය ධාවනය වෙනවාද?", QUESTIONS["si"]["book_full"], "මගේ මැදිරියේ ඒසී එක කැඩිලා"):
        chat(q)
    assert spy.sent, "no hub calls were made"
    assert {m.payload.get("language") for m in spy.sent} == {"si"}
    assert {m.receiver_agent for m in spy.sent} >= {"operations-agent", "booking-agent", "maintenance-agent"}


# --------------------------------------------------------- 9. the catalog ---

def test_every_catalog_message_exists_in_all_three_languages_with_the_same_placeholders():
    fmt = string.Formatter()
    for key, entry in MESSAGES.items():
        assert set(entry) >= {"en", "si", "ta"}, f"{key} is missing a language"
        holes = {lang: {f for _, f, _, _ in fmt.parse(text) if f} for lang, text in entry.items()}
        assert holes["si"] == holes["en"] == holes["ta"], f"{key}: placeholders differ {holes}"
        assert SI.search(entry["si"]) and not TA.search(entry["si"]), f"{key}: si text is not Sinhala"
        assert TA.search(entry["ta"]) and not SI.search(entry["ta"]), f"{key}: ta text is not Tamil"
        assert not (SI.search(entry["en"]) or TA.search(entry["en"])), f"{key}: en text has other scripts"


def test_unknown_language_or_key_falls_back_to_english_not_a_crash():
    assert t("agent_unreachable", "xx") == MESSAGES["agent_unreachable"]["en"]


def test_language_detector_uses_the_majority_script_for_mixed_text():
    assert detect_language("ticket එක කීයද") == "si"
    assert detect_language("Colombo to Kandy fare எவ்வளவு என்று சொல்லுங்கள்") == "ta"
    assert detect_language("What is the fare?") == "en"
    assert detect_language("") == "en"
