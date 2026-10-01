"""
Persistent conversation language: once a session's first meaningful message
establishes Sinhala/English/Tamil, later follow-ups keep that language
regardless of what a short reply itself looks like ("දෙන්නෙකුට?", "For 2
people?") - see resolve_session_language() in main.py.

Two test styles, matching what each part of the feature touches:
 - /chat/quick (Choo) exercises the in-process language store
   (_quick_messages[session_id]["language"]) with zero database - used for
   the required scenarios from the spec (3 languages, explicit switch, new
   session isolation) and the conversation-context combination.
 - A minimal in-memory Supabase stand-in (same pattern as
   tests/test_chat_ownership.py's FakeSupabase, duplicated here rather than
   imported so this file has no cross-file coupling) exercises the real
   touch_session()/chat_sessions.language INSERT/UPDATE path: establishing
   the language on the row's first INSERT, never rewriting an unchanged one,
   and detecting+persisting a legacy NULL-language row's language on next use.

Gemini is faked (no network/quota); RAG, NLU and language detection are real.
"""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

SI_Q1 = "කොළඹ සිට මහනුවරට ටිකට් එක කීයද?"
SI_Q2 = "දෙන්නෙකුට කීයද?"
EN_Q1 = "How much is a ticket from Colombo to Kandy?"
EN_Q2 = "What about for 2 people?"
TA_Q1 = "கொழும்பிலிருந்து கண்டிக்கு டிக்கெட் எவ்வளவு?"
TA_Q2 = "2 பேருக்கு எவ்வளவு?"


class FakeGemini:
    def generate_content(self, prompt):
        class _R:
            text = "REPLY"

        return _R()


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch):
    monkeypatch.setattr(main, "gemini_model", FakeGemini())


def ask(session_id, message):
    r = client.post("/chat/quick", json={"session_id": session_id, "message": message})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------- required scenarios ---

@pytest.mark.parametrize("q1,q2,language,from_st,to_st", [
    (SI_Q1, SI_Q2, "si", "Colombo Fort", "Kandy"),
    (EN_Q1, EN_Q2, "en", "Colombo Fort", "Kandy"),
    (TA_Q1, TA_Q2, "ta", "Colombo Fort", "Kandy"),
])
def test_followup_keeps_established_language_and_route(q1, q2, language, from_st, to_st):
    sid = f"lang-required-{language}"
    b1 = ask(sid, q1)
    assert b1["language"] == language

    b2 = ask(sid, q2)
    assert b2["language"] == language, "a short follow-up must not switch languages"
    assert b2["entities"]["from_station"] == from_st
    assert b2["entities"]["to_station"] == to_st


def test_short_sinhala_followup_does_not_fall_back_to_english():
    """The exact failure mode this feature fixes: a short reply like
    "දෙන්නෙකුට?" has few Sinhala-script characters relative to any Latin/
    digit noise, and per-message detection could plausibly waver - the
    STORED session language must be used instead, not re-detected."""
    sid = "lang-si-no-flip"
    ask(sid, SI_Q1)
    body = ask(sid, SI_Q2)
    assert body["language"] == "si"


def test_new_session_does_not_inherit_another_sessions_language():
    ask("lang-sessA", EN_Q1)
    body = ask("lang-sessB", SI_Q1)
    assert body["language"] == "si"


# --------------------------------------------------------------- explicit switch ---

def test_explicit_switch_to_sinhala_then_stays_sinhala():
    sid = "lang-switch-si"
    b1 = ask(sid, EN_Q1)
    assert b1["language"] == "en"

    b2 = ask(sid, "සිංහලෙන් කියන්න.")
    assert b2["language"] == "si"

    b3 = ask(sid, EN_Q2)  # an English-worded follow-up must NOT flip it back
    assert b3["language"] == "si"
    assert b3["entities"]["from_station"] == "Colombo Fort"
    assert b3["entities"]["to_station"] == "Kandy"


def test_explicit_switch_to_tamil():
    sid = "lang-switch-ta"
    ask(sid, EN_Q1)
    body = ask(sid, "தமிழில் பதில் சொல்லுங்கள்")
    assert body["language"] == "ta"


def test_two_languages_named_together_is_ambiguous_not_a_switch():
    sid = "lang-ambiguous"
    ask(sid, EN_Q1)
    body = ask(sid, "Can you say it in Sinhala or Tamil?")
    assert body["language"] == "en"  # neither switch wins; stays on the established language


# --------------------------------------------------------------- Supabase-backed path ---

class _Query:
    """Supports exactly the chains main.py uses: select/insert/update/eq/limit/execute."""

    def __init__(self, store, table):
        self._store, self._table = store, table
        self._op = None
        self._payload = None
        self._filters = []
        self._limit = None

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matching(self):
        rows = self._store.setdefault(self._table, [])
        return [r for r in rows if all(r.get(c) == v for c, v in self._filters)]

    def execute(self):
        rows = self._store.setdefault(self._table, [])
        if self._op == "insert":
            new = dict(self._payload)
            rows.append(new)
            return _Result([new])
        if self._op == "update":
            hit = self._matching()
            for r in hit:
                r.update(self._payload)
            return _Result(hit)
        out = self._matching()
        if self._limit is not None:
            out = out[: self._limit]
        return _Result(out)


class _Result:
    def __init__(self, data):
        self.data = data


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Query(self.store, name)


@pytest.fixture
def db(monkeypatch):
    store = {"chat_sessions": [], "chat_messages": []}
    monkeypatch.setattr(main, "supabase", FakeSupabase(store))
    return store


def real_ask(session_id, message):
    r = client.post("/chat", json={"session_id": session_id, "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def test_new_session_insert_stamps_language_alongside_owner(db):
    body = real_ask("real-lang-new", EN_Q1)
    assert body["language"] == "en"

    row = next(s for s in db["chat_sessions"] if s["session_id"] == "real-lang-new")
    assert row["language"] == "en"
    assert "user_id" in row  # the pre-existing owner-stamping behavior must be unaffected


def test_unchanged_language_is_never_rewritten(db):
    real_ask("real-lang-stable", EN_Q1)
    row = next(s for s in db["chat_sessions"] if s["session_id"] == "real-lang-stable")
    row["language"] = "SENTINEL"  # would be clobbered back to "en" if the code
    # rewrote the column on every turn instead of only on an actual change

    real_ask("real-lang-stable", EN_Q2)
    assert row["language"] == "SENTINEL"


def test_legacy_null_language_row_is_detected_and_persisted(db):
    db["chat_sessions"].append({
        "session_id": "real-lang-legacy", "title": "Legacy", "is_pinned": False,
        "user_id": None, "language": None,
        "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T00:00:00Z",
    })

    body = real_ask("real-lang-legacy", EN_Q1)
    assert body["language"] == "en"

    row = next(s for s in db["chat_sessions"] if s["session_id"] == "real-lang-legacy")
    assert row["language"] == "en"
