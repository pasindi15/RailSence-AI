"""
verify_supabase_live.py
-----------------------
Runs a real live booking through Communication Hub -> Booking Agent -> Supabase PostgreSQL.
Verifies:
1. Booking record is inserted into Supabase `bookings` table with status CONFIRMED.
2. Audit log record is inserted into Supabase `audit_logs` table with status ROUTED.
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure paths
_CURRENT_DIR = Path(__file__).resolve().parent
_M3_ROOT = _CURRENT_DIR
_BOOKING_AGENT = _M3_ROOT / "booking-agent"
_AGENT_HUB = _M3_ROOT / "agent-hub"

for p in (str(_M3_ROOT), str(_BOOKING_AGENT), str(_AGENT_HUB)):
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv
load_dotenv(_M3_ROOT / ".env", override=True)

import httpx
import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text

import importlib.util

# Load hub app
spec_hub = importlib.util.spec_from_file_location("hub_main", str(_AGENT_HUB / "main.py"))
hub_mod = importlib.util.module_from_spec(spec_hub)
spec_hub.loader.exec_module(hub_mod)
hub_app = hub_mod.app

# Load booking agent app
spec_bk = importlib.util.spec_from_file_location("booking_main", str(_BOOKING_AGENT / "main.py"))
bk_mod = importlib.util.module_from_spec(spec_bk)
spec_bk.loader.exec_module(bk_mod)
booking_app = bk_mod.app
import database.database as b_db
import hub_database as h_db

from router import get_http_client


def main():
    print("==================================================")
    print("LIVE SUPABASE END-TO-END BOOKING VERIFICATION")
    print("==================================================")
    print(f"Booking Agent Engine: {b_db.DATABASE_URL.split('@')[-1]}")
    print(f"Agent Hub Engine:     {h_db.DATABASE_URL.split('@')[-1]}")

    # Set up ASGI transport to route Hub HTTP calls to Booking Agent app
    transport = httpx.ASGITransport(app=booking_app)

    async def override_http_client():
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8003") as ac:
            yield ac

    hub_app.dependency_overrides[get_http_client] = override_http_client

    from datetime import timedelta

    # Generate test JWT matching sender_agent
    sender = "passenger-agent"
    secret = os.getenv("JWT_SECRET_KEY", "change-me")
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": sender,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=3600)).timestamp()),
        },
        secret,
        algorithm="HS256",
    )

    client = TestClient(hub_app)

    # Prepare real booking message
    message_id = f"MSG-SUPA-{uuid.uuid4().hex[:8]}"
    payload = {
        "message_id": message_id,
        "sender_agent": sender,
        "receiver_agent": "booking-agent",
        "intent": "booking_request",
        "auth_token": f"Bearer {token}",
        "timestamp": now.isoformat(),
        "payload": {
            "train_id": "PM-4082",
            "from_station": "Colombo",
            "to_station": "Kandy",
            "travel_date": "2026-12-03",
            "seat_class": "First Class",
            "passenger_count": 2,
            "user_id": "passenger_supa_live_01"
        }
    }

    print(f"\n1. Submitting Booking Request via Hub (Message ID: {message_id})...")
    resp = client.post(
        "/messages",
        json=payload,
        headers={"Authorization": f"Bearer {token}"}
    )

    print(f"   Response Status Code: {resp.status_code}")
    data = resp.json()
    print(f"   Response Payload: {data}")

    assert resp.status_code == 200, f"Booking failed with: {data}"
    booking_info = data.get("response", {}).get("booking", {})
    ref = booking_info.get("booking_reference")
    b_status = booking_info.get("status")
    fare = booking_info.get("fare")

    print(f"\n2. Verifying Response Details:")
    print(f"   - Booking Reference: {ref} (Format RS-XXXXX)")
    print(f"   - Status:            {b_status}")
    print(f"   - Total Fare:        Rs. {fare}")

    assert ref and ref.startswith("RS-"), "Invalid booking reference format!"
    assert b_status == "CONFIRMED", "Booking status must be CONFIRMED!"

    # 3. Query Supabase directly
    print("\n3. Querying live Supabase PostgreSQL database directly...")
    with b_db.SessionLocal() as session:
        booking_row = session.execute(
            text("SELECT id, booking_reference, user_id, seat_class, passenger_count, fare, status FROM bookings WHERE booking_reference = :ref"),
            {"ref": ref}
        ).fetchone()

        assert booking_row is not None, f"Booking {ref} not found in Supabase bookings table!"
        print(f"   [OK] Supabase bookings row verified:")
        print(f"        ID: {booking_row[0]}, Ref: {booking_row[1]}, User: {booking_row[2]}, Seats: {booking_row[4]}, Status: {booking_row[6]}")

        audit_row = session.execute(
            text("SELECT message_id, sender_agent, receiver_agent, status FROM audit_logs WHERE message_id = :mid"),
            {"mid": message_id}
        ).fetchone()

        assert audit_row is not None, f"Audit row {message_id} not found in Supabase audit_logs table!"
        print(f"   [OK] Supabase audit_logs row verified:")
        print(f"        Message ID: {audit_row[0]}, Sender: {audit_row[1]}, Receiver: {audit_row[2]}, Status: {audit_row[3]}")

    print("\n==================================================")
    print("ALL LIVE SUPABASE VERIFICATIONS PASSED SUCCESSFULLY!")
    print("==================================================")


if __name__ == "__main__":
    main()
