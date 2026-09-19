from fastapi.testclient import TestClient
import hub_client
from main import app

client = TestClient(app)


async def _mock_send_to_hub(message):
    """Routes through hub_client's offline stub instead of a real HTTP call -
    send_to_hub() now genuinely calls out to AGENT_HUB_URL by default, and
    these tests care about /chat's routing logic, not Hub availability."""
    return hub_client.send_to_hub_mock(message)


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


def test_delay_check_routes_to_hub_stub(monkeypatch):
    import main
    monkeypatch.setattr(main, "send_to_hub", _mock_send_to_hub)
    r = client.post("/chat", json={"message": "Is the 14:35 Colombo Fort to Kandy train delayed?"})
    body = r.json()
    assert body["intent"] == "delay_check"
    assert "Operations Agent" in body["source"]


def test_complaint_routes_to_maintenance_stub(monkeypatch):
    import main
    monkeypatch.setattr(main, "send_to_hub", _mock_send_to_hub)
    r = client.post("/chat", json={"message": "The AC is broken in my compartment"})
    body = r.json()
    assert body["intent"] == "complaint"
    assert "Maintenance Agent" in body["source"]


def test_booking_request_routes_to_booking_stub_with_entities(monkeypatch):
    import main
    monkeypatch.setattr(main, "send_to_hub", _mock_send_to_hub)
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


def test_fare_query_uses_rag_and_llm_composition(monkeypatch):
    import main

    class _FakeResponse:
        text = (
            "A one-way fare from Colombo Fort to Kandy ranges from LKR 130 "
            "(3rd class) up to LKR 1500 (1st class observation saloon)."
        )

    class _FakeGeminiModel:
        def generate_content(self, prompt):
            return _FakeResponse()

    monkeypatch.setattr(main, "gemini_model", _FakeGeminiModel())

    r = client.post("/chat", json={"message": "How much is a ticket to Kandy?"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "fare_query"
    # A Gemini-composed answer is prose, not the raw markdown dump
    # (raw fares.md content starts with a "#" heading and "Here's what I found:").
    assert not body["reply"].startswith("Here's what I found:")
    assert "##" not in body["reply"]
    assert "fares.md" in body["source"]


def test_cancel_booking():
    r = client.post("/chat", json={"message": "Cancel booking RS-84521 because I accidentally booked twice"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "cancel_booking"
    assert body["entities"]["booking_reference"] == "RS-84521"
    assert body["action"]["type"] == "cancellation_confirmation_card"
    assert body["action"]["booking_reference"] == "RS-84521"
    assert "booked twice" in body["action"]["reason"]
