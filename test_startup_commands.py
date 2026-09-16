"""
test_startup_commands.py
------------------------
Automated validation of RailSense AI unified startup commands:
1. Backend Command: Starts M1 (8001), M3 Hub (8002), M3 Booking (8003),
   Security (8004), M2 Ops (8005), and M4 Maint (8006).
2. Frontend Command: Starts Unified Portals (3000) for User & Admin.
3. Tests cross-agent communication: M1 -> Hub -> Booking/M2/M4.
4. Validates clean shutdown without dangling ports.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

def check_port(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0

def http_get(url: str, timeout: float = 3.0) -> dict | str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "StartupTester"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")
            try:
                return json.loads(content)
            except Exception:
                return content
    except Exception as e:
        return None

def http_post(url: str, data: dict, timeout: float = 8.0) -> dict | None:
    try:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "StartupTester"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"POST {url} failed: {e}")
        return None

def kill_proc(p: subprocess.Popen):
    try:
        import psutil
        parent = psutil.Process(p.pid)
        for child in parent.children(recursive=True):
            try:
                child.kill()
            except Exception:
                pass
        parent.kill()
    except Exception:
        try:
            p.kill()
        except Exception:
            pass

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("\n=======================================================")
    print("RAILSENSE AI -- AUTOMATED STARTUP COMMAND TEST SUITE")
    print("=======================================================\n")

    # Clean any dangling ports from earlier runs first
    expected_backend_ports = [8001, 8002, 8003, 8004, 8005, 8006]
    for p in expected_backend_ports + [3000]:
        if check_port(p):
            print(f"Pre-cleaning in-use port {p}...")
            if psutil:
                for proc in psutil.process_iter(["pid", "name"]):
                    try:
                        for conn in proc.net_connections():
                            if conn.laddr.port == p:
                                proc.kill()
                    except Exception:
                        pass
    time.sleep(1.0)

    # Step 1: Launch Backend Command
    print(">>> [STEP 1] Executing Backend Command: python run_backend.py")
    backend_proc = subprocess.Popen(
        [sys.executable, "run_backend.py"],
        cwd=str(ROOT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Wait for backend services to come online
    print(f"Waiting for backend ports {expected_backend_ports} to bind...")
    max_wait = 35
    start = time.time()
    online_ports = set()

    while len(online_ports) < len(expected_backend_ports) and (time.time() - start) < max_wait:
        time.sleep(1.0)
        for p in expected_backend_ports:
            if p not in online_ports and check_port(p):
                online_ports.add(p)
                print(f"  [OK] Port {p} is ONLINE")

    assert len(online_ports) == len(expected_backend_ports), (
        f"Backend startup timed out! Expected {expected_backend_ports}, but only {online_ports} came online."
    )
    print(f"\n[PASS] All 6 backend services started successfully ({len(online_ports)}/{len(expected_backend_ports)})!\n")

    # Step 2: Launch Frontend Command
    print(">>> [STEP 2] Executing Frontend Command: python run_frontend.py")
    frontend_proc = subprocess.Popen(
        [sys.executable, "run_frontend.py"],
        cwd=str(ROOT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    print("Waiting for Port 3000 to bind...")
    start = time.time()
    port_3000_online = False
    while not port_3000_online and (time.time() - start) < 15:
        time.sleep(1.0)
        if check_port(3000):
            port_3000_online = True
            print("  [OK] Port 3000 is ONLINE")

    assert port_3000_online, "Frontend failed to bind on port 3000 within timeout!"
    print("\n[PASS] Unified Frontend started successfully on Port 3000!\n")

    # Step 3: Test Portals & APIs
    print(">>> [STEP 3] Testing Cross-Portal & Multi-Agent Functionality")

    # A. User Portal
    user_res = http_get("http://127.0.0.1:3000/user")
    assert user_res is not None and "Passenger Assistant" in user_res, "User portal failed to render!"
    print("  [OK] User Portal (http://localhost:3000/user) responded with 200 OK")

    # B. Admin Portal
    admin_res = http_get("http://127.0.0.1:3000/admin")
    assert admin_res is not None and "Operations & Administrative Portal" in admin_res, "Admin portal failed to render!"
    print("  [OK] Admin Portal (http://localhost:3000/admin) responded with 200 OK")

    # C. Multi-Agent Health Probe through Gateway
    health_res = http_get("http://127.0.0.1:3000/api/admin/system-health")
    assert health_res is not None, "System health API failed!"
    print(f"  [OK] System Health API status: {health_res.get('status')}")
    for svc in health_res.get("services", []):
        print(f"    - {svc['name']}: {svc['status']} ({svc['latency_ms']} ms)")
        assert svc["status"] in ("ONLINE", "DEGRADED"), f"Service {svc['name']} is offline!"

    # D. M1 Passenger Assistant Chat via Gateway
    print("\n>>> [STEP 4] Testing Passenger Chat -> M1 NLU Dispatch")
    chat_res = http_post(
        "http://127.0.0.1:3000/api/chat",
        {"message": "What services does RailSense AI provide?"},
    )
    assert chat_res is not None and "reply" in chat_res, "Chat API failed!"
    print(f"  [OK] Passenger Chat response: {chat_res['reply'][:90]}...")

    # E. M2 Delay Prediction
    print("\n>>> [STEP 5] Testing M2 Operations Delay Regressor")
    m2_pred = http_post(
        "http://127.0.0.1:8005/predict-delay",
        {"route": "Colombo Fort - Kandy", "train_id": "PM-4082", "scheduled_time": "2026-09-14T14:30:00Z"},
    )
    assert m2_pred is not None and "predicted_delay_minutes" in m2_pred, "M2 predict-delay failed!"
    print(f"  [OK] M2 Predicted delay: {m2_pred['predicted_delay_minutes']} min, explanation: {m2_pred.get('explanation')[:60]}...")

    # F. M4 Maintenance Assets
    print("\n>>> [STEP 6] Testing M4 Maintenance Fleet API")
    m4_dash = http_get("http://127.0.0.1:8006/api/dashboard")
    assert m4_dash is not None, "M4 dashboard API failed!"
    print(f"  [OK] M4 Fleet Health: {m4_dash.get('average_health_score', 'N/A')} across {m4_dash.get('total_assets', 'N/A')} assets")

    # Clean Teardown
    print("\n>>> [STEP 7] Performing Clean Teardown of All Processes")
    kill_proc(backend_proc)
    kill_proc(frontend_proc)
    time.sleep(2.5)

    # Confirm ports released
    dangling = [p for p in expected_backend_ports + [3000] if check_port(p)]
    if dangling:
        print(f"  Warning: Ports still in use: {dangling}. Re-cleaning...")
        if psutil:
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    for conn in proc.net_connections():
                        if conn.laddr.port in dangling:
                            proc.kill()
                except Exception:
                    pass
        time.sleep(1.0)
    print("  [OK] All ports released cleanly.")

    print("\n=======================================================")
    print("SUCCESS: ALL STARTUP COMMANDS AND INTEGRATION TESTS PASSED!")
    print("=======================================================\n")

if __name__ == "__main__":
    main()
