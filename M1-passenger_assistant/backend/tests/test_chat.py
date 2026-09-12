from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


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


def test_delay_check_routes_to_hub_stub():
    r = client.post("/chat", json={"message": "Is the 14:35 Colombo Fort to Kandy train delayed?"})
    body = r.json()
    assert body["intent"] == "delay_check"
    assert "Operations Agent" in body["source"]


def test_complaint_routes_to_maintenance_stub():
    r = client.post("/chat", json={"message": "The AC is broken in my compartment"})
    body = r.json()
    assert body["intent"] == "complaint"
    assert "Maintenance Agent" in body["source"]


def test_booking_request_routes_to_booking_stub_with_entities():
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


def test_fare_query_uses_rag_and_llm_composition():
    r = client.post("/chat", json={"message": "How much is a ticket to Kandy?"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "fare_query"
    # A Gemini-composed answer is prose, not the raw markdown dump
    # (raw fares.md content starts with a "#" heading and "Here's what I found:").
    assert not body["reply"].startswith("Here's what I found:")
    assert "##" not in body["reply"]
    assert "fares.md" in body["source"]
