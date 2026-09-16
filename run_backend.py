"""
run_backend.py
--------------
RailSense AI — Unified Multi-Agent Backend Orchestrator.

Starts all FastAPI backend services together in a single command:
1. M3 Communication Hub  -> Port 8002
2. Security & Fraud Agent -> Port 8004
3. M3 Booking Agent      -> Port 8003
4. M2 Operations Agent   -> Port 8005
5. M4 Maintenance Agent  -> Port 8006
6. M1 Passenger Assistant -> Port 8001

Features:
- Starts all processes with their proper working directories.
- Preserves all existing ports and inter-agent communication paths.
- Streams stdout/stderr with clean colored agent prefix tags.
- Verifies real-time /health liveness and prints a readiness matrix.
- Cleanly shuts down all processes and their child trees on Ctrl+C.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None

ROOT_DIR = Path(__file__).resolve().parent

# Color codes for terminal output
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
RED = "\033[91m"
GRAY = "\033[90m"

SERVICES = [
    {
        "id": "m3_hub",
        "name": "M3 Communication Hub",
        "port": 8002,
        "color": BLUE,
        "cwd": ROOT_DIR / "M3-Comunication-Hub&Booking-Agent" / "agent-hub",
        "cmd": [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8002"],
        "health_url": "http://127.0.0.1:8002/health",
    },
    {
        "id": "security_agent",
        "name": "Security & Fraud Agent",
        "port": 8004,
        "color": YELLOW,
        "cwd": ROOT_DIR / "security-agent",
        "cmd": [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8004"],
        "health_url": "http://127.0.0.1:8004/health",
    },
    {
        "id": "m3_booking",
        "name": "M3 Booking Agent",
        "port": 8003,
        "color": GREEN,
        "cwd": ROOT_DIR / "M3-Comunication-Hub&Booking-Agent" / "booking-agent",
        "cmd": [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8003"],
        "health_url": "http://127.0.0.1:8003/health",
    },
    {
        "id": "m2_operations",
        "name": "M2 Operations Agent",
        "port": 8005,
        "color": CYAN,
        "cwd": ROOT_DIR / "M2-operations-agent",
        "cmd": [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8005"],
        "health_url": "http://127.0.0.1:8005/health",
    },
    {
        "id": "m4_maintenance",
        "name": "M4 Maintenance Agent",
        "port": 8006,
        "color": MAGENTA,
        "cwd": ROOT_DIR / "M4-maintenance-agent",
        "cmd": [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8006"],
        "health_url": "http://127.0.0.1:8006/health",
    },
    {
        "id": "m1_passenger",
        "name": "M1 Passenger Assistant",
        "port": 8001,
        "color": BLUE,
        "cwd": ROOT_DIR / "M1-passenger_assistant" / "backend",
        "cmd": [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8001"],
        "health_url": "http://127.0.0.1:8001/health",
    },
]

processes: list[tuple[dict[str, Any], subprocess.Popen]] = []
running = True


def log_stream(svc: dict[str, Any], proc: subprocess.Popen):
    """Read lines from process stdout and display with service prefix."""
    prefix = f"{svc['color']}[{svc['name']} :{svc['port']}]{RESET} "
    try:
        if proc.stdout:
            for line in iter(proc.stdout.readline, ""):
                if not running:
                    break
                if line:
                    sys.stdout.write(f"{prefix}{line}")
                    sys.stdout.flush()
    except Exception:
        pass


def kill_proc_tree(proc: subprocess.Popen):
    """Safely terminate a process and all its children."""
    pid = proc.pid
    if psutil:
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except Exception:
                    pass
            parent.terminate()
            gone, alive = psutil.wait_procs(children + [parent], timeout=3)
            for p in alive:
                try:
                    p.kill()
                except Exception:
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    else:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def stop_all_services(signum=None, frame=None):
    """Stop all running services cleanly."""
    global running
    if not running:
        return
    running = False
    print(f"\n{YELLOW}{BOLD}[ORCHESTRATOR] Shutting down all RailSense AI backend services...{RESET}")
    for svc, proc in reversed(processes):
        print(f"{GRAY}  Stopping {svc['name']} (PID {proc.pid})...{RESET}")
        kill_proc_tree(proc)
    print(f"{GREEN}{BOLD}[ORCHESTRATOR] All backend services stopped cleanly.{RESET}\n")
    sys.exit(0)


def check_liveness():
    """Probe all service health endpoints and report status."""
    print(f"\n{BOLD}{CYAN}Probing Multi-Agent Liveness Status...{RESET}")
    max_wait = 20
    start_time = time.time()
    pending = list(SERVICES)
    verified = []

    while pending and (time.time() - start_time) < max_wait:
        time.sleep(1.0)
        for svc in list(pending):
            try:
                req = urllib.request.Request(svc["health_url"], headers={"User-Agent": "RailSense-Orchestrator"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status in (200, 204):
                        verified.append(svc)
                        pending.remove(svc)
                        print(f"  {GREEN}[ONLINE]{RESET} {BOLD}{svc['name']}{RESET} listening on http://127.0.0.1:{svc['port']}")
            except Exception:
                pass

    if pending:
        for svc in pending:
            print(f"  {YELLOW}[INITIALIZING]{RESET} {svc['name']} on port {svc['port']} (still loading models)")

    print(f"\n{GREEN}{BOLD}===================================================================={RESET}")
    print(f"{GREEN}{BOLD} RailSense AI Multi-Agent Backend is RUNNING ({len(verified)}/{len(SERVICES)} verified){RESET}")
    print(f"{GREEN}{BOLD}===================================================================={RESET}")
    print(f"  M1 Passenger Assistant: http://127.0.0.1:8001/health")
    print(f"  M3 Communication Hub:   http://127.0.0.1:8002/health")
    print(f"  M3 Booking Agent:       http://127.0.0.1:8003/health")
    print(f"  Security & Fraud Agent: http://127.0.0.1:8004/health")
    print(f"  M2 Operations Agent:    http://127.0.0.1:8005/health")
    print(f"  M4 Maintenance Agent:   http://127.0.0.1:8006/health")
    print(f"{GRAY}Press Ctrl+C to terminate all backend services.{RESET}\n")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    signal.signal(signal.SIGINT, stop_all_services)
    signal.signal(signal.SIGTERM, stop_all_services)

    print(f"{BOLD}{CYAN}===================================================================={RESET}")
    print(f"{BOLD}{CYAN} RailSense AI — Unified Multi-Agent Backend Orchestrator{RESET}")
    print(f"{BOLD}{CYAN} Starting all 6 backend services...{RESET}")
    print(f"{BOLD}{CYAN}===================================================================={RESET}\n")

    for svc in SERVICES:
        print(f"Starting {svc['color']}{svc['name']}{RESET} on port {BOLD}{svc['port']}{RESET} (cwd: {svc['cwd'].name})...")
        proc = subprocess.Popen(
            svc["cmd"],
            cwd=str(svc["cwd"]),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        processes.append((svc, proc))

        t = threading.Thread(target=log_stream, args=(svc, proc), daemon=True)
        t.start()
        time.sleep(0.6)  # Staggered startup to avoid port bind contention

    # Health check in separate thread so logs keep flowing
    checker_thread = threading.Thread(target=check_liveness, daemon=True)
    checker_thread.start()

    try:
        while running:
            # Check if any process terminated unexpectedly
            for svc, proc in processes:
                code = proc.poll()
                if code is not None and running:
                    print(f"\n{RED}[ERROR] {svc['name']} exited unexpectedly with code {code}{RESET}")
            time.sleep(1.0)
    except KeyboardInterrupt:
        stop_all_services()


if __name__ == "__main__":
    main()
