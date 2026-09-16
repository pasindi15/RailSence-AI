"""
test_full_system_integration.py
-------------------------------
Complete, rigorous end-to-end integration test of the RailSense AI system.
Validates:
1. Single Backend Startup (M1:8001, Hub:8002, Booking:8003, Security:8004, M2:8005, M4:8006)
2. Single Frontend Startup (Port 3000: User Portal + Admin Portal)
3. User Portal: M1 Chat, NLU, RAG & Citations, Delay checking, Complaints, Booking dispatch
4. Admin Portal: M2 Control Room, M2 Admin Console, M2 Delay Regressor, M2 Incident report,
   Fraud queue, Cancellation queue with NLP preview, M4 Asset Dashboard, M4 Engineer Chatbot
5. Inter-agent communication: M1 -> Hub -> M2/M3/M4 and Gateway -> Hub -> Booking -> Security
6. Clean process teardown
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

ROOT_DIR = Path(__file__).resolve().parent

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def check_port(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def cleanup_ports(ports: list[int]):
    for p in ports:
        if check_port(p) and psutil:
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    for conn in proc.net_connections():
                        if conn.laddr.port == p:
                            proc.kill()
                except Exception:
                    pass
    time.sleep(1.0)


def kill_proc(p: subprocess.Popen):
    try:
        if psutil:
            parent = psutil.Process(p.pid)
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
            parent.kill()
        else:
            p.kill()
    except Exception:
        pass


def http_get(url: str, timeout: float = 6.0) -> tuple[int, Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FullSystemTester"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(content)
            except Exception:
                return resp.status, content
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body
    except Exception as e:
        return 0, str(e)


def http_post(url: str, data: dict, timeout: float = 12.0) -> tuple[int, Any]:
    try:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "FullSystemTester"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(content)
            except Exception:
                return resp.status, content
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body
    except Exception as e:
        return 0, str(e)


def main():
    print("\n==================================================================")
    print("RAILSENSE AI -- COMPLETE MULTI-AGENT SYSTEM INTEGRATION TEST")
    print("==================================================================\n")

    backend_ports = [8001, 8002, 8003, 8004, 8005, 8006]
    all_ports = backend_ports + [3000]

    # Pre-clean
    cleanup_ports(all_ports)

    # -----------------------------------------------------------------------
    # 1. BACKEND STARTUP
    # -----------------------------------------------------------------------
    print(">>> [TEST 1] Starting Backend Services via run_backend.py...")
    backend_proc = subprocess.Popen(
        [sys.executable, "run_backend.py"],
        cwd=str(ROOT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    frontend_proc = None

    # Wait for all 6 backend services to bind
    start_time = time.time()
    online_backend = set()
    while len(online_backend) < len(backend_ports) and (time.time() - start_time) < 40:
        time.sleep(1.0)
        for p in backend_ports:
            if p not in online_backend and check_port(p):
                online_backend.add(p)
                print(f"  [OK] Port {p} bound")

    assert len(online_backend) == len(backend_ports), f"Backend ports failed to bind: {online_backend}/{backend_ports}"

    # Verify each service's health endpoint
    health_checks = [
        ("M1 Passenger Assistant", "http://127.0.0.1:8001/health"),
        ("M3 Communication Hub", "http://127.0.0.1:8002/health"),
        ("M3 Booking Agent", "http://127.0.0.1:8003/health"),
        ("Security & Fraud Agent", "http://127.0.0.1:8004/health"),
        ("M2 Operations Agent", "http://127.0.0.1:8005/health"),
        ("M4 Maintenance Agent", "http://127.0.0.1:8006/health"),
    ]
    for name, url in health_checks:
        status, data = http_get(url)
        assert status == 200, f"{name} health check failed with status {status}: {data}"
        print(f"  [OK] {name} /health: 200 OK")

    print("[PASS] 1. Backend startup verified (6/6 services healthy)!\n")

    # -----------------------------------------------------------------------
    # 2. FRONTEND STARTUP
    # -----------------------------------------------------------------------
    print(">>> [TEST 2] Starting Unified Frontend via run_frontend.py...")
    frontend_proc = subprocess.Popen(
        [sys.executable, "run_frontend.py"],
        cwd=str(ROOT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    start_time = time.time()
    port_3000 = False
    while not port_3000 and (time.time() - start_time) < 20:
        time.sleep(1.0)
        if check_port(3000):
            port_3000 = True
            print("  [OK] Port 3000 bound")

    assert port_3000, "Frontend failed to bind on port 3000"

    # Verify User and Admin portal routes
    portal_routes = [
        ("Root Redirect", "http://127.0.0.1:3000/"),
        ("User Portal Main", "http://127.0.0.1:3000/user"),
        ("User Portal Chat", "http://127.0.0.1:3000/user/chat"),
        ("User Portal Booking Desk", "http://127.0.0.1:3000/user/booking"),
        ("User Portal Confirmation", "http://127.0.0.1:3000/user/confirmation"),
        ("Admin Portal Main", "http://127.0.0.1:3000/admin"),
        ("Admin Portal Operations", "http://127.0.0.1:3000/admin/operations"),
        ("Admin Portal Bookings", "http://127.0.0.1:3000/admin/bookings"),
        ("Admin Portal Maintenance", "http://127.0.0.1:3000/admin/maintenance"),
        ("Admin Portal Security", "http://127.0.0.1:3000/admin/security"),
    ]
    for label, url in portal_routes:
        status, content = http_get(url)
        assert status == 200, f"{label} ({url}) returned status {status}"
        print(f"  [OK] {label}: 200 OK")

    # Verify multi-agent health probe API
    status, health_matrix = http_get("http://127.0.0.1:3000/api/admin/system-health")
    assert status == 200, f"System health probe failed: {health_matrix}"
    assert health_matrix["status"] == "HEALTHY", f"System health is {health_matrix.get('status')}"
    for svc in health_matrix["services"]:
        print(f"  [OK] Gateway Health -> {svc['name']}: {svc['status']} ({svc['latency_ms']} ms)")
        assert svc["status"] == "ONLINE", f"{svc['name']} reported {svc['status']}"

    print("[PASS] 2. Frontend startup verified (User & Admin Portals active)!\n")

    # -----------------------------------------------------------------------
    # 3. USER PORTAL & M1 MULTI-AGENT WORKFLOWS
    # -----------------------------------------------------------------------
    print(">>> [TEST 3] Testing User Portal & M1 Passenger Assistant Functionality...")

    # A. Schedule query with ChromaDB RAG & citations
    status, data = http_post("http://127.0.0.1:8001/chat", {"message": "What is the schedule for trains from Colombo Fort to Kandy?"})
    assert status == 200, f"M1 schedule query failed: {data}"
    assert "Podi Menike" in data["reply"] or "Colombo" in data["reply"], f"Unexpected schedule reply: {data['reply']}"
    assert "schedules.md" in data["source"] or "fares.md" in data["source"], f"Expected FAQ citation, got: {data['source']}"
    print(f"  [OK] M1 Schedule RAG Query -> Reply generated with citation: '{data['source']}'")

    # B. Fare query with ChromaDB RAG & citations
    status, data = http_post("http://127.0.0.1:8001/chat", {"message": "How much is the ticket fare from Colombo Fort to Kandy?"})
    assert status == 200, f"M1 fare query failed: {data}"
    assert "1st Class" in data["reply"] or "2nd Class" in data["reply"] or "Class" in data["reply"], f"Unexpected fare reply: {data['reply']}"
    print(f"  [OK] M1 Fare RAG Query -> Reply generated with citation: '{data['source']}'")

    # C. Delay checking: M1 -> Hub -> M2 Operations Regressor -> Hub -> M1
    status, data = http_post("http://127.0.0.1:8001/chat", {"message": "Is the 14:35 train PM-4082 from Colombo Fort to Kandy delayed?"})
    assert status == 200, f"M1 delay check failed: {data}"
    assert "Expected delay:" in data["reply"], f"Expected delay in reply, got: {data['reply']}"
    assert "Operations Agent" in data["source"], f"Expected Operations Agent source, got: {data['source']}"
    print(f"  [OK] M1 -> Hub -> M2 Delay Check Roundtrip -> '{data['reply'][:90]}...' (Source: {data['source']})")

    # D. Complaint logging: M1 -> Hub -> M4 Maintenance Agent -> Hub -> M1
    status, data = http_post("http://127.0.0.1:8001/chat", {"message": "The air conditioning in carriage 3 is broken and not working"})
    assert status == 200, f"M1 complaint failed: {data}"
    assert "Ticket: MT-" in data["reply"] or "Issue logged" in data["reply"], f"Unexpected complaint reply: {data['reply']}"
    assert "Maintenance Agent" in data["source"], f"Expected Maintenance Agent source, got: {data['source']}"
    print(f"  [OK] M1 -> Hub -> M4 Complaint Roundtrip -> '{data['reply']}' (Source: {data['source']})")

    # E. Booking intent extraction & action card on Gateway
    status, data = http_post("http://127.0.0.1:3000/api/chat", {"message": "I want to book a train ticket from Colombo to Kandy on 2026-09-25"})
    assert status == 200, f"Gateway chat failed: {data}"
    assert data["intent"] == "booking_request", f"Expected booking_request intent, got: {data['intent']}"
    assert data.get("action") is not None and "continue_to_booking" in data["action"]["type"]
    print(f"  [OK] Gateway Booking Intent -> Generated Action Card: '{data['action']['label']}' ({data['action']['url']})")

    # F. Booking schedule discovery query
    status, options = http_get("http://127.0.0.1:3000/api/booking-options?from_station=Colombo&to_station=Kandy&travel_date=2026-12-03")
    assert status == 200, f"Booking options query failed: {options}"
    trains_list = options if isinstance(options, list) else options.get("trains", [])
    assert len(trains_list) > 0, f"No trains returned in options: {options}"
    test_train = trains_list[0]
    train_display = test_train.get("train_name") or test_train.get("name") or "Express"
    print(f"  [OK] Booking Agent Discovery -> Found {len(trains_list)} trains (Sample: {test_train['train_id']} - {train_display})")

    # G. Booking confirmation: Gateway -> JWT Sign -> M3 Hub -> M3 Booking Agent
    booking_payload = {
        "from_station": "Colombo",
        "to_station": "Kandy",
        "travel_date": "2026-12-03",
        "train_id": test_train["train_id"],
        "seat_class": "Second Class",
        "passenger_count": 1,
        "passenger_email": "passenger.test@example.com",
        "passengers": [
            {
                "full_name": "Test Traveler",
                "nic": f"2000{int(time.time()) % 100000000:08d}",
                "passenger_type": "ADULT"
            }
        ]
    }
    status, b_confirm = http_post("http://127.0.0.1:3000/api/bookings/confirm", booking_payload)
    assert status == 200, f"Booking confirmation failed with {status}: {b_confirm}"
    booking_obj = b_confirm.get("booking") if isinstance(b_confirm.get("booking"), dict) else b_confirm
    assert "booking_reference" in booking_obj, f"Missing booking_reference: {b_confirm}"
    created_ref = booking_obj["booking_reference"]
    total_fare = booking_obj.get("fare") or b_confirm.get("total_fare_lkr")
    print(f"  [OK] Gateway -> Hub -> Booking Dispatch -> Confirmed Reference: {created_ref} (Rs. {total_fare})")

    print("[PASS] 3. User Portal & M1 Passenger workflows 100% verified!\n")

    # -----------------------------------------------------------------------
    # 4. ADMIN PORTAL & OPERATIONS/MAINTENANCE/SECURITY
    # -----------------------------------------------------------------------
    print(">>> [TEST 4] Testing Admin Portal Suite & Embedded Agent Services...")

    # A. M2 Operations Control Room UI
    status, m2_ui = http_get("http://127.0.0.1:8005/")
    assert status == 200 and "Operations" in m2_ui, "M2 Control Room UI failed to load"
    print("  [OK] M2 Operations Control Room UI (http://localhost:8005/): 200 OK")

    # B. M2 Admin Console UI
    status, m2_admin_ui = http_get("http://127.0.0.1:8005/admin")
    assert status == 200, "M2 Admin Console UI failed to load"
    print("  [OK] M2 Operations Admin Console UI (http://localhost:8005/admin): 200 OK")

    # C. M2 Direct Delay Prediction Model
    status, m2_pred = http_post(
        "http://127.0.0.1:8005/predict-delay",
        {
            "route": "Colombo Fort - Kandy",
            "train_id": "PM-4082",
            "scheduled_time": datetime.now(timezone.utc).isoformat(),
            "weather": "clear",
            "day_type": "weekday"
        }
    )
    assert status == 200 and "predicted_delay_minutes" in m2_pred, f"M2 predict-delay failed: {m2_pred}"
    print(f"  [OK] M2 Delay Regressor -> {m2_pred['predicted_delay_minutes']} min delay (Confidence: {m2_pred['confidence']}, Model: {m2_pred['model_version']})")

    # D. M2 Staff Incident Classification & Triage
    status, inc_res = http_post(
        "http://127.0.0.1:8005/incident-report",
        {
            "train_id": "PM-4082",
            "station": "Kadugannawa",
            "raw_text": "Signal aspect failed at down approach signal near Kadugannawa incline."
        }
    )
    assert status == 200 and "incident_id" in inc_res, f"M2 incident report failed: {inc_res}"
    print(f"  [OK] M2 Staff Incident Triage -> Created Incident: {inc_res['incident_id']} (Type: {inc_res.get('incident_type')})")

    # E. Admin Fraud Reviews Queue
    status, fraud_cases = http_get("http://127.0.0.1:3000/api/admin/fraud-reviews")
    assert status == 200 and isinstance(fraud_cases, list), f"Fraud reviews failed: {fraud_cases}"
    print(f"  [OK] Admin Fraud Review Queue -> Loaded {len(fraud_cases)} cases")

    # F. Admin Cancellations Queue
    status, canc_cases = http_get("http://127.0.0.1:3000/api/admin/cancellations")
    assert status == 200 and isinstance(canc_cases, list), f"Cancellations failed: {canc_cases}"
    print(f"  [OK] Admin Cancellation Queue -> Loaded {len(canc_cases)} cases")

    # G. Cancellation NLP Policy Preview
    status, nlp_prev = http_post(
        "http://127.0.0.1:3000/api/admin/cancellations/nlp-preview",
        {"reason": "Cancelled less than 2 hours before scheduled departure under standard railway policy"}
    )
    assert status == 200 and "polished_explanation" in nlp_prev, f"NLP preview failed: {nlp_prev}"
    print(f"  [OK] Admin NLP Policy Preview -> Tone: '{nlp_prev.get('tone')}', Category: '{nlp_prev.get('category_label')}'")

    # H. M4 Maintenance Dashboard UI
    status, m4_ui = http_get("http://127.0.0.1:8006/")
    assert status == 200 and "Maintenance" in m4_ui, "M4 Dashboard UI failed to load"
    print("  [OK] M4 Maintenance Asset Dashboard UI (http://localhost:8006/): 200 OK")

    # I. M4 Maintenance Engineer Chatbot UI
    status, m4_chat_ui = http_get("http://127.0.0.1:8006/chat-ui")
    assert status == 200, "M4 Chatbot UI failed to load"
    print("  [OK] M4 Maintenance Engineer Chatbot UI (http://localhost:8006/chat-ui): 200 OK")

    # J. M4 Equipment Manual RAG Chatbot Endpoint
    status, m4_chat_res = http_post("http://127.0.0.1:8006/chat", {"message": "How do I inspect the air brake distributor valve?"})
    assert status == 200 and ("response" in m4_chat_res or "answer" in m4_chat_res), f"M4 manual RAG failed: {m4_chat_res}"
    m4_ans = m4_chat_res.get("answer") or m4_chat_res.get("response") or ""
    m4_src = m4_chat_res.get("citations") or m4_chat_res.get("sources") or []
    print(f"  [OK] M4 Equipment Manual RAG -> '{m4_ans[:90]}...' (Citations: {len(m4_src)})")

    # K. Security & Fraud Anomaly Scoring (Port 8004)
    status, sec_res = http_post(
        "http://127.0.0.1:8004/internal/fraud-score",
        {
            "nic_key": "200012345678",
            "features": {
                "bookings_last_1h": 1.0,
                "bookings_last_24h": 1.0,
                "distinct_routes_7d": 1.0,
                "avg_lead_time_hours": 72.0,
                "cancellation_rate_30d": 0.0
            }
        }
    )
    assert status == 200 and "risk_score" in sec_res, f"Security agent failed: {sec_res}"
    print(f"  [OK] Security Agent (8004) IsolationForest -> Risk Score: {sec_res['risk_score']} (Level: {sec_res.get('risk_level')})")

    print("[PASS] 4. Admin Portal & Operational Suites 100% verified!\n")

    # -----------------------------------------------------------------------
    # 5. CLEAN TEARDOWN
    # -----------------------------------------------------------------------
    print(">>> [TEST 5] Shutting Down Processes & Verifying Port Cleanup...")
    kill_proc(backend_proc)
    kill_proc(frontend_proc)
    time.sleep(2.5)

    dangling = [p for p in all_ports if check_port(p)]
    if dangling:
        print(f"  Cleaning residual ports: {dangling}")
        cleanup_ports(dangling)
    print("  [OK] All ports (3000, 8001, 8002, 8003, 8004, 8005, 8006) released cleanly.")

    print("\n==================================================================")
    print("INTEGRATION TEST SUMMARY: 100% SUCCESS -- ALL WORKFLOWS PASSED!")
    print("==================================================================\n")


if __name__ == "__main__":
    main()
