"""Incident map: approval workflow + verified-only feed.

Runs against an in-memory incident store (no Supabase), so it checks M2's own
rules: only admin-approved incidents reach /api/incidents/map-feed, the feed
never carries internal fields, and a store outage degrades instead of failing.

    python -m pytest M2-operations-agent/tests/test_incident_map.py -q
"""

import csv
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

M2_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(M2_DIR))

import incident_map  # noqa: E402
import main  # noqa: E402
from admin import admin_auth, admin_db  # noqa: E402

PUBLIC_FIELDS = {"id", "train_id", "station", "lat", "lon", "incident_type", "summary", "verified_at", "status"}


@pytest.fixture
def store(monkeypatch):
    rows: dict[str, dict] = {}

    def create(record):
        row = dict(record, review_status="pending")
        rows[row["incident_id"]] = row
        return {"row": row, "source": "supabase"}

    def update(incident_id, patch):
        rows[incident_id].update(patch)
        return {"row": rows[incident_id], "source": "supabase", "error": None}

    def listing(limit=25, offset=0, review_status=None, **_):
        found = [r for r in rows.values() if not review_status or r.get("review_status") == review_status]
        return {"rows": found[offset:offset + limit], "count": len(found), "source": "supabase"}

    monkeypatch.setattr(admin_db, "get_incident", lambda i: rows.get(i))
    monkeypatch.setattr(admin_db, "update_incident", update)
    monkeypatch.setattr(admin_db, "list_incidents", listing)
    monkeypatch.setattr(admin_db, "get_officer_by_id", lambda _i: None)
    monkeypatch.setattr(main, "_audit", lambda *a, **k: None)
    monkeypatch.setattr(main, "_index_incident_for_retrieval", lambda *a, **k: None)
    main.MAP_FEED.invalidate()
    rows["inc-1"] = {"incident_id": "inc-1", "train_id": "PM-4082", "station": "Kandy",
                     "raw_text": "INTERNAL raw staff note", "summary": "Signal failure near Kandy.",
                     "classified_type": "signal_fault", "nlp_method": "rule_based",
                     "review_status": "pending", "reviewed_by": None}
    rows["inc-2"] = dict(rows["inc-1"], incident_id="inc-2", station="Gampaha")
    yield rows
    main.MAP_FEED.invalidate()


def _headers(role):
    token = admin_auth.create_officer_token({"id": f"t-{role}", "email": f"{role}@railsense.lk",
                                             "full_name": role, "role": role})
    return {"Authorization": f"Bearer {token}"}


def _feed(client):
    main.MAP_FEED.invalidate()
    return client.get("/api/incidents/map-feed").json()


def test_every_corpus_station_has_coordinates():
    with (M2_DIR / "data" / "operations_history.csv").open(encoding="utf-8") as f:
        corpus = {row["station"] for row in csv.DictReader(f)}
    missing = corpus - set(incident_map.STATION_LOCATIONS)
    assert not missing, f"stations without coordinates: {sorted(missing)}"


@pytest.mark.parametrize("status", ["pending", "corrected", "approved", "rejected", None])
def test_only_verified_rows_are_public(status):
    assert incident_map.public_item({"incident_id": "x", "station": "Kandy", "review_status": status}) is None


def test_pending_incident_not_on_map(store):
    client = TestClient(main.app)
    assert _feed(client)["incidents"] == []


def test_review_requires_admin_capability(store):
    client = TestClient(main.app)
    assert client.post("/incidents/inc-1/approve").status_code == 401
    assert client.post("/incidents/inc-1/approve", headers=_headers("operations_engineer")).status_code == 403
    assert _feed(client)["incidents"] == []


def test_reject_never_reaches_map(store):
    client = TestClient(main.app)
    assert client.post("/incidents/inc-1/reject", headers=_headers("admin")).status_code == 200
    assert store["inc-1"]["review_status"] == "rejected"
    assert _feed(client)["incidents"] == []


def test_approve_publishes_allowlisted_marker(store):
    client = TestClient(main.app)
    resp = client.post("/incidents/inc-1/approve", headers=_headers("admin")).json()
    assert resp["mapped"] is True
    feed = _feed(client)
    assert len(feed["incidents"]) == 1
    item = feed["incidents"][0]
    assert set(item) == PUBLIC_FIELDS
    assert item["status"] == "VERIFIED" and item["station"] == "Kandy"
    assert (item["lat"], item["lon"]) == incident_map.STATION_LOCATIONS["Kandy"]
    assert item["verified_at"]
    assert "INTERNAL" not in str(feed)


def test_unknown_station_counted_not_guessed(store):
    client = TestClient(main.app)
    resp = client.post("/incidents/inc-2/approve", headers=_headers("admin")).json()
    assert resp["mapped"] is False
    feed = _feed(client)
    assert feed["incidents"] == [] and feed["unmapped"] == 1


def test_edit_takes_incident_off_map(store):
    client = TestClient(main.app)
    client.post("/incidents/inc-1/approve", headers=_headers("admin"))
    assert len(_feed(client)["incidents"]) == 1
    assert client.patch("/incidents/inc-1", json={"summary": "Updated text"}).status_code == 200
    assert store["inc-1"]["review_status"] == "corrected"
    assert _feed(client)["incidents"] == []


def test_patch_cannot_set_verified(store):
    client = TestClient(main.app)
    assert client.patch("/incidents/inc-1", json={"review_status": "verified"}).status_code == 422


def test_store_outage_serves_last_known(store, monkeypatch):
    client = TestClient(main.app)
    client.post("/incidents/inc-1/approve", headers=_headers("admin"))
    assert len(_feed(client)["incidents"]) == 1

    def boom(**_):
        raise RuntimeError("store down")
    monkeypatch.setattr(admin_db, "list_incidents", boom)
    feed = _feed(client)
    assert feed["stale"] is True and len(feed["incidents"]) == 1


def test_map_shows_only_incidents_verified_today():
    """Sri Lanka midnight is the cutoff; at 00:00 the previous day's markers drop off."""
    from datetime import datetime, timedelta
    tz = incident_map.LOCAL_TZ
    base = {"review_status": "verified", "station": "Kandy", "summary": "s", "classified_type": "weather"}
    rows = [
        dict(base, incident_id="yesterday", verified_at=datetime(2026, 9, 21, 23, 59, tzinfo=tz).isoformat()),
        dict(base, incident_id="today", verified_at=datetime(2026, 9, 22, 0, 1, tzinfo=tz).isoformat()),
    ]
    now = {"t": datetime(2026, 9, 22, 10, 0, tzinfo=tz)}
    feed = incident_map.MapFeed(lambda: {"rows": rows, "source": "supabase"}, clock=lambda: now["t"])

    first = feed.get()
    assert [i["id"] for i in first["incidents"]] == ["today"]
    assert first["day"] == "2026-09-22"

    # The next midnight passes: the cache must not keep serving yesterday's view.
    now["t"] = datetime(2026, 9, 23, 0, 0, 1, tzinfo=tz)
    assert feed.get()["incidents"] == []
    assert feed.get()["day"] == "2026-09-23"


def test_last_known_feed_also_drops_old_markers():
    from datetime import datetime
    tz = incident_map.LOCAL_TZ
    row = {"incident_id": "a", "review_status": "verified", "station": "Kandy", "summary": "s",
           "classified_type": "weather", "verified_at": datetime(2026, 9, 22, 9, 0, tzinfo=tz).isoformat()}
    state = {"ok": True, "t": datetime(2026, 9, 22, 10, 0, tzinfo=tz)}

    def fetch():
        if not state["ok"]:
            raise RuntimeError("store down")
        return {"rows": [row], "source": "supabase"}
    feed = incident_map.MapFeed(fetch, clock=lambda: state["t"])
    assert len(feed.get()["incidents"]) == 1
    state.update(ok=False, t=datetime(2026, 9, 23, 0, 5, tzinfo=tz))  # outage spanning midnight
    stale = feed.get()
    assert stale["stale"] is True and stale["incidents"] == []
