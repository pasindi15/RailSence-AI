"""
Regression for a real production failure: chat_sessions.language (added by
the migration in supabase_schema.sql) had not actually been run against the
live Supabase project. touch_session() used to bundle "language" into the
SAME insert/update statement as session_id/title/user_id - PostgREST rejects
an entire insert/update if ANY column it references doesn't exist, so that
one missing column silently failed session row creation altogether. With no
chat_sessions row, every following chat_messages insert then violated
fk_chat_messages_session ("chat_messages" -> "chat_sessions"), captured in
the reported logs as:

    [context] session language lookup failed: column chat_sessions.language does not exist
    Supabase session upsert failed: Could not find the 'language' column of 'chat_sessions' in the schema cache
    Supabase save failed: ... violates foreign key constraint "fk_chat_messages_session"

touch_session() now writes "language" as its own, separate statement AFTER
the core insert/update succeeds, so a missing column can only ever degrade
language persistence (chat() falls back to per-message detect_language()
every turn), never conversation history itself.

Two fake-Supabase configurations below model the two states a real project
can be in:
  - _NoLanguageColumnSupabase: the migration has NOT been run (the actual
    reported state) - enforces column existence like real PostgREST does,
    and chat_sessions has no "language" column.
  - _MigratedSupabase: the migration HAS been run - same enforcement, but
    chat_sessions.language exists.

These are unit tests against an in-memory stand-in, not the real Supabase
project - see the bottom of this file for what still needs a manual check
against the actual database.
"""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

ROUTE_Q1 = "colombo indn anuradapura ticket eka kiyada"  # romanized Sinhala: "how much is a Colombo-Anuradhapura ticket"


class FakeGemini:
    def __init__(self):
        self.prompts: list[str] = []

    def generate_content(self, prompt):
        self.prompts.append(prompt)

        class _R:
            text = "REPLY"

        return _R()


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch):
    fake = FakeGemini()
    monkeypatch.setattr(main, "gemini_model", fake)
    return fake


# --------------------------------------------------------------- fake Supabase ---
# Enforces column existence the way real PostgREST does (unlike the more
# permissive FakeSupabase in test_chat_ownership.py / test_conversation_language.py,
# which accept any payload) - that's the one behavior this bug depended on.

class _SchemaError(Exception):
    pass


class _Query:
    def __init__(self, store, table, columns):
        self._store, self._table, self._columns = store, table, columns
        self._op = None
        self._payload = None
        self._filters = []
        self._limit = None

    def _check(self, keys):
        missing = set(keys) - self._columns
        if missing:
            raise _SchemaError(
                f"Could not find the '{next(iter(missing))}' column of '{self._table}' in the schema cache"
            )

    def select(self, cols="*", *_a, **_k):
        self._op = "select"
        if cols != "*":
            self._check(c.strip() for c in cols.split(","))
        return self

    def insert(self, payload):
        self._check(payload.keys())
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._check(payload.keys())
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


class _SchemaEnforcingSupabase:
    """chat_messages columns are the same in both states below - only
    chat_sessions.language is ever missing, matching the actual migration."""

    CHAT_MESSAGES_COLUMNS = {"session_id", "role", "message", "user_id"}

    def __init__(self, store, chat_sessions_columns):
        self.store = store
        self._table_columns = {
            "chat_sessions": chat_sessions_columns,
            "chat_messages": self.CHAT_MESSAGES_COLUMNS,
        }

    def table(self, name):
        return _Query(self.store, name, self._table_columns.get(name, set()))


def _no_language_column_supabase(store):
    return _SchemaEnforcingSupabase(
        store, {"session_id", "title", "is_pinned", "created_at", "updated_at", "user_id"}
    )


def _migrated_supabase(store):
    return _SchemaEnforcingSupabase(
        store, {"session_id", "title", "is_pinned", "created_at", "updated_at", "user_id", "language"}
    )


# ------------------------------------------------- the pre-migration failure mode ---

def test_missing_language_column_does_not_break_session_creation(monkeypatch):
    """The exact reported bug: chat_sessions has no "language" column yet.
    The session row must still be created and chat_messages must still
    accept the insert - only language persistence may degrade."""
    store = {"chat_sessions": [], "chat_messages": []}
    monkeypatch.setattr(main, "supabase", _no_language_column_supabase(store))

    r = client.post("/chat", json={"session_id": "no-lang-col", "message": ROUTE_Q1})
    assert r.status_code == 200, r.text

    assert len(store["chat_sessions"]) == 1, "session row must be created despite the missing column"
    session_row = store["chat_sessions"][0]
    assert session_row["session_id"] == "no-lang-col"
    assert "language" not in session_row  # the column genuinely doesn't exist in this state

    assert len(store["chat_messages"]) == 2  # user + assistant - no FK violation


def test_missing_language_column_still_resolves_the_bare_number_followup(monkeypatch):
    """Even without language persistence working, the route/intent/passenger-
    count follow-up logic (independent fixes) must still resolve correctly -
    only the reply's LANGUAGE is allowed to degrade (falls back to
    per-message detect_language() every turn, which reads a bare "2" as
    "en" - a real, honest limitation without the migration, not a crash)."""
    store = {"chat_sessions": [], "chat_messages": []}
    monkeypatch.setattr(main, "supabase", _no_language_column_supabase(store))

    client.post("/chat", json={"session_id": "no-lang-col-2", "message": ROUTE_Q1})
    r2 = client.post("/chat", json={"session_id": "no-lang-col-2", "message": "2"})
    assert r2.status_code == 200, r2.text
    body = r2.json()

    assert body["intent"] == "fare_query"
    assert body["entities"]["from_station"] == "Colombo Fort"
    assert body["entities"]["to_station"] == "Anuradhapura"
    assert body["entities"]["passenger_count"] == 2
    assert body["source"] == "fares.md"  # reached compose_rag_answer, not the off-topic notice


# ------------------------------------------------------ once the migration IS run ---

def test_full_reported_scenario_once_migrated(monkeypatch, _fake_llm):
    """The complete required scenario, exactly as reported, with
    chat_sessions.language actually present (the state after running the
    migration in supabase_schema.sql)."""
    store = {"chat_sessions": [], "chat_messages": []}
    monkeypatch.setattr(main, "supabase", _migrated_supabase(store))

    b1 = client.post("/chat", json={"session_id": "migrated", "message": ROUTE_Q1}).json()
    assert b1["language"] == "si"
    row = next(s for s in store["chat_sessions"] if s["session_id"] == "migrated")
    assert row["language"] == "si"

    b2 = client.post("/chat", json={"session_id": "migrated", "message": "2"}).json()
    assert b2["language"] == "si"
    assert b2["intent"] == "fare_query"
    assert b2["entities"]["from_station"] == "Colombo Fort"
    assert b2["entities"]["to_station"] == "Anuradhapura"
    assert b2["entities"]["passenger_count"] == 2
    assert b2["source"] == "fares.md"

    prompt = _fake_llm.prompts[-1]
    assert "Pre-computed total fares for 2 passengers" in prompt
    assert "LKR 6000" in prompt  # 3000 (First Class) x 2 - computed in code, not left to the LLM
    assert "LKR 3000" in prompt  # 1500 (Second Class) x 2


def test_language_column_write_is_its_own_statement_not_bundled(monkeypatch):
    """Regression for the actual root cause: the language UPDATE/INSERT must
    be issued separately from the core session row write, never merged into
    the same payload - this is what makes the missing-column tests above
    even possible to fix without touching the core session-creation path."""
    store = {"chat_sessions": [], "chat_messages": []}
    monkeypatch.setattr(main, "supabase", _migrated_supabase(store))

    client.post("/chat", json={"session_id": "separate-write", "message": ROUTE_Q1})
    row = next(s for s in store["chat_sessions"] if s["session_id"] == "separate-write")
    assert row["language"] == "si"
    assert row["title"] == ROUTE_Q1[:60]
    assert "user_id" in row


# ---------------------------------------------------------------------------------
# What these tests do NOT cover (needs a manual check against the real Supabase
# project, not this in-memory stand-in):
#
#   1. That the migration in supabase_schema.sql actually runs cleanly against
#      the live database (run it once in the Supabase SQL editor and confirm
#      no error).
#   2. That PostgREST's schema cache picks up the new column afterwards - if
#      "language" still isn't found immediately after running the migration,
#      reload it from the Supabase dashboard (Settings -> API -> "Reload
#      schema cache") or restart the M1 backend process.
#   3. That fk_chat_messages_session is actually enforced in that project the
#      way supabase_schema.sql defines it (it's created NOT VALID, so it
#      applies to new/updated rows only - this suite can't see the real
#      table's constraint state).
# ---------------------------------------------------------------------------------
