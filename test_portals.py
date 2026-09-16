"""
test_portals.py
---------------
Verification test suite for RailSense AI User Portal and Admin Portal separation.
Tests FastAPI routes, redirections, HTML content assertions, chat endpoints, and health check.
"""

import sys
from pathlib import Path
from starlette.testclient import TestClient

# Ensure frontend directory is importable
frontend_dir = Path(__file__).resolve().parent / "frontend"
sys.path.insert(0, str(frontend_dir))

from serve import app

client = TestClient(app)

def test_portal_routes():
    print("\n==========================================")
    print("Testing RailSense AI Portal Routing Architecture")
    print("==========================================")

    # 1. Root redirect
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 302, f"Expected 302 redirect for '/', got {res.status_code}"
    assert res.headers["location"] == "/user", f"Expected redirect to /user, got {res.headers['location']}"
    print("[PASS] GET / -> 302 Redirect to /user")

    # 2. User Portal routes
    for path in ["/user", "/user/chat", "/user/booking", "/user/confirmation"]:
        res = client.get(path)
        assert res.status_code == 200, f"Expected 200 for {path}, got {res.status_code}"
        assert "Passenger Assistant" in res.text, f"Missing User Portal title in {path}"
        assert "M1 Passenger Assistant" in res.text, f"Missing M1 mention in {path}"
        assert "Train Ticket Reservation" in res.text, f"Missing Train Ticket Reservation in {path}"
        print(f"[PASS] GET {path} -> 200 OK (User Portal)")

    # 3. Legacy booking redirect
    res = client.get("/booking", follow_redirects=False)
    assert res.status_code == 302, f"Expected 302 redirect for /booking, got {res.status_code}"
    assert res.headers["location"] == "/user/booking", f"Expected redirect to /user/booking"
    print("[PASS] GET /booking -> 302 Redirect to /user/booking")

    # 4. Admin Portal routes
    for path in ["/admin", "/admin/operations", "/admin/bookings", "/admin/maintenance", "/admin/security"]:
        res = client.get(path)
        assert res.status_code == 200, f"Expected 200 for {path}, got {res.status_code}"
        assert "Operations & Administrative Portal" in res.text, f"Missing Admin Portal title in {path}"
        assert "M2" in res.text, f"Missing M2 mention in {path}"
        assert "M4" in res.text, f"Missing M4 mention in {path}"
        assert "Fraud Review" in res.text, f"Missing Fraud Review mention in {path}"
        print(f"[PASS] GET {path} -> 200 OK (Admin Portal)")

    # 5. Legacy cancellations redirect
    res = client.get("/admin/cancellations", follow_redirects=False)
    assert res.status_code == 302, f"Expected 302 redirect for /admin/cancellations, got {res.status_code}"
    assert res.headers["location"] == "/admin/bookings", f"Expected redirect to /admin/bookings"
    print("[PASS] GET /admin/cancellations -> 302 Redirect to /admin/bookings")

    # 6. Admin System Health API
    res = client.get("/api/admin/system-health")
    assert res.status_code == 200, f"Expected 200 for system-health, got {res.status_code}"
    health_data = res.json()
    assert "status" in health_data, "Missing status in health data"
    assert "services" in health_data, "Missing services in health data"
    agent_ids = [s["id"] for s in health_data["services"]]
    for expected_agent in ["m1_passenger", "m2_operations", "m3_hub", "m3_booking", "security_agent", "m4_maintenance"]:
        assert expected_agent in agent_ids, f"Missing {expected_agent} in health check services"
    print(f"[PASS] GET /api/admin/system-health -> 200 OK (Probed {len(agent_ids)} multi-agent services)")

    # 7. Passenger Chat Intent & Action Card
    res = client.post("/api/chat", json={"message": "I want to book a train from Colombo to Kandy on tomorrow"})
    assert res.status_code == 200, f"Expected 200 for /api/chat, got {res.status_code}"
    chat_data = res.json()
    assert chat_data["intent"] == "booking_request", f"Expected booking_request intent, got {chat_data.get('intent')}"
    assert "action" in chat_data and chat_data["action"] is not None
    assert "/booking" in chat_data["action"]["url"] or "/user/booking" in chat_data["action"]["url"]
    print("[PASS] POST /api/chat (Booking Intent) -> 200 OK with Action Card")

    # 8. Passenger Cancellation Intent Card
    res = client.post("/api/chat", json={"message": "Please cancel my booking REF-992384 because my trip was cancelled"})
    assert res.status_code == 200, f"Expected 200 for cancellation chat, got {res.status_code}"
    canc_data = res.json()
    assert canc_data["intent"] == "cancel_booking", f"Expected cancel_booking intent, got {canc_data.get('intent')}"
    print("[PASS] POST /api/chat (Cancellation Intent) -> 200 OK with Cancellation Card")

    # 9. General Chat Fallback
    res = client.post("/api/chat", json={"message": "What is RailSense AI?"})
    assert res.status_code == 200, f"Expected 200 for general chat, got {res.status_code}"
    print("[PASS] POST /api/chat (General Inquiry Fallback) -> 200 OK")

    print("\n==========================================")
    print("ALL PORTAL VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("==========================================\n")

if __name__ == "__main__":
    test_portal_routes()
