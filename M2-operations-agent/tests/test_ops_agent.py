"""Operations Assistant: grounding, roles, clear refusals, history scoping.

Gemini is replaced by fakes and the data tools read fixtures, so these tests
are deterministic, offline, and never write to Supabase.

    python -m pytest M2-operations-agent/tests/test_ops_agent.py -q
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

M2_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(M2_DIR))

import main  # noqa: E402
import ops_agent  # noqa: E402
from admin import admin_auth, admin_db  # noqa: E402

DASHBOARD = {
    "generated_at": "2026-09-22T06:12:00+00:00",
    "data_source": {"history": "supabase", "offline": False},
    "overview": {"average_delay": 8.4, "on_time_rate": 43.8, "trips": 2999, "routes_monitored": 7},
    "routes": [{"route": "Colombo Fort - Trincomalee", "average_delay": 8.7, "incident_rate": 52.2, "status": "watch"}],
    "incident_mix": [{"type": "signal_fault", "count": 400}],
}
INCIDENTS = [
    {"incident_id": "aaaaaa11", "train_id": "PM-4082", "station": "Kandy", "classified_type": "signal_fault",
     "review_status": "pending", "summary": "Signal failure near Kandy.", "received_at": "2026-09-21T10:00:00+00:00"},
    {"incident_id": "bbbbbb22", "train_id": "IC-1048", "station": "Galle", "classified_type": "weather",
     "review_status": "rejected", "summary": "FAKE REJECTED REPORT", "received_at": "2026-09-21T11:00:00+00:00"},
]
ENGINEER_PERMS = set(admin_auth.get_permissions_for_role("operations_engineer"))
ADMIN_PERMS = set(admin_auth.get_permissions_for_role("admin"))


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "dashboard_data", lambda: DASHBOARD)
    monkeypatch.setattr(admin_db, "list_incidents",
                        lambda limit=25, offset=0, review_status=None, **_: {
                            "rows": [r for r in INCIDENTS if not review_status or r["review_status"] == review_status],
                            "count": 2, "source": "supabase"})
    monkeypatch.setattr(admin_db, "list_agent_audit_events", lambda **_: {
        "rows": [{"timestamp": "2026-09-21T19:00:00+00:00", "intent": "incident_approve"}],
        "count": 1, "source": "supabase", "offline": False})
    monkeypatch.setattr(admin_db, "get_officer_by_id", lambda _i: None)
    audits = []
    monkeypatch.setattr(main, "_audit", lambda action, request, details: audits.append((action, details)))
    monkeypatch.setattr(ops_agent, "LOCAL_HISTORY_PATH", tmp_path / "ops_agent_queries.jsonl")
    monkeypatch.setattr(main.OPS_HISTORY, "get_client", lambda: None)
    # No real LLM: default to "Gemini unavailable" (tests override per case).
    monkeypatch.setattr(main.OPS_AGENT, "_gemini", lambda q, trace, allowed, role: (None, None))
    return audits


def _headers(role, uid):
    token = admin_auth.create_officer_token({"id": uid, "email": f"{uid}@railsense.lk", "full_name": uid, "role": role})
    return {"Authorization": f"Bearer {token}"}


ADMIN_A = _headers("admin", "admin-a")
ADMIN_B = _headers("admin", "admin-b")
ENGINEER = _headers("operations_engineer", "eng-1")


def ask_engineer(q):
    return main.OPS_AGENT.ask(q, permissions=ENGINEER_PERMS, role="operations_engineer")


def ask_admin(q):
    return main.OPS_AGENT.ask(q, permissions=ADMIN_PERMS, role="admin")


# ------------------------------------------------------------------ access

def test_access_by_role(env):
    client = TestClient(main.app)
    assert client.post("/api/ops-agent/ask", json={"question": "hi there"}).status_code == 401
    viewer = _headers("viewer", "viewer-1")
    assert client.post("/api/ops-agent/ask", json={"question": "hi there"}, headers=viewer).status_code == 403
    for headers in (ADMIN_A, ENGINEER):
        assert client.post("/api/ops-agent/ask", json={"question": "Any pending incidents?"}, headers=headers).status_code == 200


def test_capabilities_per_role(env):
    client = TestClient(main.app)
    eng = client.get("/api/ops-agent/capabilities", headers=ENGINEER).json()
    adm = client.get("/api/ops-agent/capabilities", headers=ADMIN_A).json()
    assert set(eng["tools"]) == {"get_dashboard_kpis", "get_route_status", "predict_delay", "get_incident_queue"}
    assert set(adm["tools"]) >= set(eng["tools"]) | {"get_model_metrics", "get_audit_log", "check_system_health"}
    assert eng["restricted_topics"] and adm["restricted_topics"] == []
    assert "Is the Hub online?" not in eng["examples"]


# ---------------------------------------------------------------- grounding

def test_answer_is_grounded_and_cited(env):
    client = TestClient(main.app)
    r = client.post("/api/ops-agent/ask", json={"question": "What's the network average delay?"}, headers=ENGINEER).json()
    assert r["answer_type"] == "answer" and r["answer_method"] == "rule_based_fallback"
    assert "8.4" in r["answer"] and "43.8" in r["answer"]
    assert [s["tool"] for s in r["sources"]] == ["get_dashboard_kpis"]
    assert env and env[-1][0] == "ops_agent_query" and env[-1][1]["role"] == "operations_engineer"


def test_hallucinated_number_is_rejected(env, monkeypatch):
    def fake(question, trace, allowed, role):
        main.OPS_AGENT._execute("get_dashboard_kpis", {}, trace, allowed)
        return "The network averages **12.9 min** of delay.", None
    monkeypatch.setattr(main.OPS_AGENT, "_gemini", fake)
    r = ask_admin("What's the average delay?")
    assert r["answer_method"] == "template_after_guard"
    assert "12.9" not in r["answer"] and "8.4" in r["answer"]


def test_grounded_llm_answer_is_kept(env, monkeypatch):
    def fake(question, trace, allowed, role):
        main.OPS_AGENT._execute("get_dashboard_kpis", {}, trace, allowed)
        return "Across **2,999** trips the average delay is **8.4 min** (**43.8%** on time).", None
    monkeypatch.setattr(main.OPS_AGENT, "_gemini", fake)
    r = ask_admin("What's the average delay?")
    assert r["answer_method"] == "llm_tool_calling" and r["answer_type"] == "answer"


def test_free_text_without_tools_is_never_shown(env, monkeypatch):
    monkeypatch.setattr(main.OPS_AGENT, "_gemini",
                        lambda q, trace, allowed, role: ("Sorry, I think delays are about 7 minutes.", None))
    r = ask_admin("What's the average delay?")
    assert "7 minutes" not in r["answer"] and r["sources"]


def test_rejected_incidents_never_cited(env):
    r = ask_engineer("Any incidents in the queue?")
    assert "FAKE REJECTED" not in r["answer"] and "#bbbbbb" not in r["answer"]
    assert "#aaaaaa" in r["answer"]


# ----------------------------------------------------- role restrictions

@pytest.mark.parametrize("question", ["What were the last audit events?", "Is Supabase online?",
                                      "How accurate is the delay model?"])
def test_engineer_gets_restricted_message(env, question):
    r = ask_engineer(question)
    assert r["answer_type"] == "restricted"
    assert "only available to administrators" in r["answer"] and "Operations Engineer" in r["answer"]
    assert r["sources"] == [] and r["highlights"] == []


def test_admin_can_ask_the_same(env):
    r = ask_admin("What were the last audit events?")
    assert r["answer_type"] == "answer" and r["sources"][0]["tool"] == "get_audit_log"


def test_llm_restricted_signal(env, monkeypatch):
    monkeypatch.setattr(main.OPS_AGENT, "_gemini",
                        lambda q, trace, allowed, role: (None, {"kind": "report_restricted", "topic": "The audit log"}))
    r = ask_engineer("who approved incident 4821?")
    assert r["answer_type"] == "restricted" and "**The audit log**" in r["answer"]


def test_forbidden_tool_is_never_executed(env):
    trace = []
    result = main.OPS_AGENT._execute("get_audit_log", {}, trace,
                                     main.OPS_AGENT.allowed_tools(ENGINEER_PERMS))
    assert result == {"forbidden": True}


# ------------------------------------------------ not enough information

def test_prediction_without_details(env):
    for ask in (ask_engineer, ask_admin):
        r = ask("Predict a delay for me")
        assert r["answer_type"] == "insufficient_data"
        assert "don't have enough information" in r["answer"] and "train" in r["answer"]


def test_actions_are_explained_not_attempted(env):
    admin = ask_admin("Reset the password for officer Nimal")
    assert admin["answer_type"] == "insufficient_data" and "can't make changes" in admin["answer"]
    eng = ask_engineer("Reset the password for officer Nimal")
    assert eng["answer_type"] == "restricted"


def test_llm_insufficient_signal_drops_numbers(env, monkeypatch):
    monkeypatch.setattr(main.OPS_AGENT, "_gemini", lambda q, trace, allowed, role: (
        None, {"kind": "report_insufficient", "reason": "the train is missing", "missing": "train 9999 id"}))
    r = ask_engineer("will it be late?")
    assert r["answer_type"] == "insufficient_data" and "The train is missing." in r["answer"]
    assert "9999" not in r["answer"]  # model text with figures is never echoed


def test_unknown_route_is_insufficient(env, monkeypatch):
    def fake(question, trace, allowed, role):
        main.OPS_AGENT._execute("get_route_status", {"route_id": "Mars Express"}, trace, allowed)
        return "I don't recognise that route.", None
    monkeypatch.setattr(main.OPS_AGENT, "_gemini", fake)
    r = ask_engineer("How is the Mars Express line?")
    assert r["answer_type"] == "insufficient_data" and "don't have enough information" in r["answer"]


def test_out_of_scope(env):
    r = ask_engineer("Who won the cricket yesterday?")
    assert r["answer_type"] == "out_of_scope" and r["sources"] == []
    assert "outside what I can help with" in r["answer"]


def test_offline_data_degrades_plainly(env, monkeypatch):
    def down():
        raise RuntimeError("supabase down")
    monkeypatch.setattr(main, "dashboard_data", down)
    r = ask_engineer("What's the network average delay?")
    assert r["answer_type"] == "unavailable" and "can't reach the live operations data" in r["answer"]


def test_health_reports_outage_to_admin(env, monkeypatch):
    import admin.admin_router as router
    monkeypatch.setattr(router, "health_status", lambda identity=None: {
        "supabase": {"configured": True, "reachable": False},
        "hub": {"base_url": "http://localhost:8002", "reachable": False},
        "upstash": {"configured": False}, "checked_at": 0})
    r = ask_admin("Is Supabase online?")
    assert "unreachable" in r["answer"] and {h["value"] for h in r["highlights"]} >= {"down"}


# ----------------------------------------------------------------- history

def test_history_is_private_per_user(env):
    client = TestClient(main.app)
    client.post("/api/ops-agent/ask", json={"question": "Any pending incidents?"}, headers=ADMIN_A)
    client.post("/api/ops-agent/ask", json={"question": "What's the network average delay?"}, headers=ENGINEER)
    a = client.get("/api/ops-agent/history", headers=ADMIN_A).json()["rows"]
    e = client.get("/api/ops-agent/history", headers=ENGINEER).json()["rows"]
    assert [r["question"] for r in a] == ["Any pending incidents?"]
    assert [r["question"] for r in e] == ["What's the network average delay?"]
    assert a[0]["answer"] and a[0]["sources"] and a[0]["answer_type"] == "answer"
    assert client.get("/api/ops-agent/history?user_id=eng-1", headers=ADMIN_A).status_code == 403
    bad = client.post("/api/ops-agent/ask", json={"question": "hi", "session_user_id": "admin-b"}, headers=ADMIN_A)
    assert bad.status_code == 403


@pytest.mark.parametrize("answer,ok", [
    ("MAE is **2.315** min and R² 0.8551", True),
    ("R² is 85.5%", True),
    ("MAE is 3.1 min", False),
])
def test_number_guard(answer, ok):
    results = [{"mae_minutes": 2.315, "r2": 0.8551}]
    assert ops_agent.numbers_grounded(answer, results, "how accurate?")[0] is ok
