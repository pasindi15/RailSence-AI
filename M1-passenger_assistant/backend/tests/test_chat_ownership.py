"""Per-passenger chat history: each passenger sees only their own chats.

Before this was fixed, GET /chat ran an unfiltered select, so every passenger's
sidebar listed every conversation in the database, and knowing a session_id was
enough to read, rename, pin or delete somebody else's chat.

These tests run against an in-memory stand-in for Supabase rather than the real
project database: the ownership rules are pure logic, and the suite must not
write rows into (or depend on the state of) the team's live Supabase.
"""
import pytest
from fastapi.testclient import TestClient

import auth
import main
from main import app

client = TestClient(app)

KAVYA = {"user_id": "PSG-001", "username": "kavya", "full_name": "Kavya Perera"}
DILSHAN = {"user_id": "PSG-002", "username": "dilshan", "full_name": "Dilshan Silva"}


# ---------------------------------------------------------------------------
# Minimal in-memory Supabase stand-in
# ---------------------------------------------------------------------------
class _Query:
    """Supports exactly the chains main.py uses: select/insert/update/upsert/
    delete, .eq(), .order(), .limit(), .execute()."""

    def __init__(self, store, table):
        self._store, self._table = store, table
        self._op = None
        self._payload = None
        self._filters = []
        self._orders = []
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

    def upsert(self, payload):
        self._op, self._payload = "upsert", payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def order(self, column, desc=False):
        self._orders.append((column, desc))
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
            new.setdefault("id", f"{self._table}-{len(rows) + 1}")
            new.setdefault("created_at", f"2026-01-01T00:00:{len(rows):02d}Z")
            rows.append(new)
            return _Result([new])
        if self._op in ("update", "upsert"):
            hit = self._matching()
            for r in hit:
                r.update(self._payload)
            if self._op == "upsert" and not hit:
                rows.append(dict(self._payload))
                return _Result([rows[-1]])
            return _Result(hit)
        if self._op == "delete":
            hit = self._matching()
            self._store[self._table] = [r for r in rows if r not in hit]
            return _Result(hit)
        out = self._matching()
        # Supabase applies the first .order() as the primary key, so apply them
        # in reverse for a stable sort.
        for column, desc in reversed(self._orders):
            out = sorted(out, key=lambda r: (r.get(column) is None, r.get(column)), reverse=desc)
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
    """A fake Supabase seeded with two passengers and one chat each."""
    store = {
        # passenger_accounts, not passengers: `passengers` is M3's booking table.
        "passenger_accounts": [
            {**KAVYA, "password_hash": auth.hash_password("kavya2024"), "nic": "200012345678"},
            {**DILSHAN, "password_hash": auth.hash_password("dilshan2024"), "nic": "199887654321"},
        ],
        "chat_sessions": [
            {"session_id": "sess-kavya", "title": "TEST KAVYA 12345", "is_pinned": False,
             "user_id": "PSG-001", "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"},
            {"session_id": "sess-dilshan", "title": "TEST DILSHAN 99999", "is_pinned": False,
             "user_id": "PSG-002", "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"},
            # Pre-existing row from before the migration: owned by nobody.
            {"session_id": "sess-legacy", "title": "Legacy conversation", "is_pinned": False,
             "user_id": None, "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T00:00:00Z"},
        ],
        "chat_messages": [
            {"id": "m1", "session_id": "sess-kavya", "role": "user",
             "message": "TEST KAVYA 12345", "user_id": "PSG-001", "created_at": "2026-01-01T00:00:00Z"},
        ],
        "chat_summaries": [],
    }
    monkeypatch.setattr(main, "supabase", FakeSupabase(store))
    return store


def token_for(passenger):
    return {"Authorization": f"Bearer {auth.create_passenger_token(passenger)}"}


# ---------------------------------------------------------------------------
# Sidebar isolation
# ---------------------------------------------------------------------------
def test_kavya_sees_only_her_own_chats(db):
    r = client.get("/chat", headers=token_for(KAVYA))
    assert r.status_code == 200
    titles = [s["title"] for s in r.json()]
    assert titles == ["TEST KAVYA 12345"]


def test_dilshan_sees_only_his_own_chats(db):
    r = client.get("/chat", headers=token_for(DILSHAN))
    assert r.status_code == 200
    titles = [s["title"] for s in r.json()]
    assert titles == ["TEST DILSHAN 99999"]


def test_dilshan_cannot_see_kavyas_chat_in_the_sidebar(db):
    """The original bug, stated directly."""
    sessions = client.get("/chat", headers=token_for(DILSHAN)).json()
    assert all(s["session_id"] != "sess-kavya" for s in sessions)
    assert all("KAVYA" not in s["title"] for s in sessions)


def test_legacy_sessions_belong_to_nobody(db):
    """Pre-migration rows (user_id NULL) are kept, but shown to no one."""
    for who in (KAVYA, DILSHAN):
        sessions = client.get("/chat", headers=token_for(who)).json()
        assert all(s["session_id"] != "sess-legacy" for s in sessions)


# ---------------------------------------------------------------------------
# Direct session_id access
# ---------------------------------------------------------------------------
def test_dilshan_cannot_open_kavyas_session_by_id(db):
    r = client.get("/chat/sess-kavya/history", headers=token_for(DILSHAN))
    assert r.status_code == 404


def test_kavya_can_open_her_own_session(db):
    r = client.get("/chat/sess-kavya/history", headers=token_for(KAVYA))
    assert r.status_code == 200
    assert r.json()["messages"][0]["message"] == "TEST KAVYA 12345"


def test_not_yours_is_404_not_403(db):
    """403 would confirm the session exists and is someone else's - exactly what
    an attacker enumerating ids wants to learn. It must be indistinguishable
    from an id that never existed."""
    real = client.get("/chat/sess-kavya/history", headers=token_for(DILSHAN))
    fake = client.get("/chat/sess-doesnotexist/history", headers=token_for(DILSHAN))
    assert real.status_code == fake.status_code == 404
    assert real.json() == fake.json()


# ---------------------------------------------------------------------------
# Mutations on someone else's chat
# ---------------------------------------------------------------------------
def test_dilshan_cannot_delete_kavyas_session(db):
    r = client.delete("/chat/sess-kavya", headers=token_for(DILSHAN))
    assert r.status_code == 404
    assert any(s["session_id"] == "sess-kavya" for s in db["chat_sessions"])
    assert any(m["session_id"] == "sess-kavya" for m in db["chat_messages"])


def test_dilshan_cannot_rename_kavyas_session(db):
    r = client.patch("/chat/sess-kavya/title", json={"title": "HACKED"}, headers=token_for(DILSHAN))
    assert r.status_code == 404
    row = next(s for s in db["chat_sessions"] if s["session_id"] == "sess-kavya")
    assert row["title"] == "TEST KAVYA 12345"


def test_dilshan_cannot_pin_kavyas_session(db):
    r = client.patch("/chat/sess-kavya/pin", json={"pinned": True}, headers=token_for(DILSHAN))
    assert r.status_code == 404
    row = next(s for s in db["chat_sessions"] if s["session_id"] == "sess-kavya")
    assert row["is_pinned"] is False


def test_kavya_can_rename_and_pin_her_own_session(db):
    assert client.patch("/chat/sess-kavya/title", json={"title": "Renamed"},
                        headers=token_for(KAVYA)).status_code == 200
    assert client.patch("/chat/sess-kavya/pin", json={"pinned": True},
                        headers=token_for(KAVYA)).status_code == 200
    row = next(s for s in db["chat_sessions"] if s["session_id"] == "sess-kavya")
    assert row["title"] == "Renamed" and row["is_pinned"] is True


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method,path", [
    ("get", "/chat"),
    ("get", "/chat/sess-kavya/history"),
    ("delete", "/chat/sess-kavya"),
])
def test_protected_endpoints_require_a_token(db, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_a_forged_token_is_rejected(db):
    """user_id is only ever taken from a signature this server verified, so
    re-signing the claims with a different secret must not be accepted."""
    import jwt
    forged = jwt.encode({"sub": "PSG-001", "exp": 9999999999}, "not-the-real-secret", algorithm="HS256")
    r = client.get("/chat", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_login_succeeds_and_returns_a_working_token(db):
    r = client.post("/auth/login", json={"username": "kavya", "password": "kavya2024"})
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "PSG-001"
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["user_id"] == "PSG-001"


def test_login_rejects_a_wrong_password(db):
    r = client.post("/auth/login", json={"username": "kavya", "password": "wrong"})
    assert r.status_code == 401


def test_login_does_not_reveal_whether_a_username_exists(db):
    unknown = client.post("/auth/login", json={"username": "nobody", "password": "x"})
    wrong = client.post("/auth/login", json={"username": "kavya", "password": "x"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


# ---------------------------------------------------------------------------
# POST /chat stays open, and stamps the owner when there is one
# ---------------------------------------------------------------------------
# "hello" takes the greeting short-circuit, so these exercise the save path
# without calling RAG or the LLM.
def test_anonymous_chat_still_works_and_is_owned_by_nobody(db):
    """The public homepage, the passenger portal, M2's hand-off and the
    integration scripts all POST /chat with no token."""
    r = client.post("/chat", json={"message": "hello", "session_id": "sess-anon"})
    assert r.status_code == 200
    assert r.json()["reply"]
    saved = [m for m in db["chat_messages"] if m["session_id"] == "sess-anon"]
    assert len(saved) == 2
    assert all(m["user_id"] is None for m in saved)
    session = next(s for s in db["chat_sessions"] if s["session_id"] == "sess-anon")
    assert session["user_id"] is None


def test_signed_in_chat_is_stamped_with_the_token_owner(db):
    r = client.post("/chat", json={"message": "hello", "session_id": "sess-new"}, headers=token_for(KAVYA))
    assert r.status_code == 200
    saved = [m for m in db["chat_messages"] if m["session_id"] == "sess-new"]
    assert saved and all(m["user_id"] == "PSG-001" for m in saved)
    session = next(s for s in db["chat_sessions"] if s["session_id"] == "sess-new")
    assert session["user_id"] == "PSG-001"


def test_a_user_id_in_the_request_body_is_ignored(db):
    """Identity comes from the token, never from the payload."""
    r = client.post("/chat", json={"message": "hello", "session_id": "sess-spoof", "user_id": "PSG-001"})
    assert r.status_code == 200
    session = next(s for s in db["chat_sessions"] if s["session_id"] == "sess-spoof")
    assert session["user_id"] is None


# ---------------------------------------------------------------------------
# Choo must stay exactly as it was
# ---------------------------------------------------------------------------
def test_choo_quick_chat_needs_no_token_and_saves_nothing(db):
    before_messages = len(db["chat_messages"])
    before_sessions = len(db["chat_sessions"])

    r = client.post("/chat/quick", json={"message": "hello", "session_id": "choo-abc"})
    assert r.status_code == 200
    assert r.json()["reply"]

    assert len(db["chat_messages"]) == before_messages
    assert len(db["chat_sessions"]) == before_sessions


def test_choo_sessions_never_reach_any_sidebar(db):
    client.post("/chat/quick", json={"message": "hello", "session_id": "choo-xyz"})
    for who in (KAVYA, DILSHAN):
        sessions = client.get("/chat", headers=token_for(who)).json()
        assert all(not s["session_id"].startswith("choo-") for s in sessions)
