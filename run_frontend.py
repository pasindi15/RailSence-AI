"""
run_frontend.py
---------------
RailSense AI — Unified Frontend Server Orchestrator.

Starts the unified frontend application on Port 3000:
- User Portal   -> http://localhost:3000/user
- Admin Portal  -> http://localhost:3000/admin

Features:
- Launches frontend/serve.py in proper working directory.
- Probes liveness for both portals and prints clean access links.
- Handles clean process termination on Ctrl+C.
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

try:
    import psutil
except ImportError:
    psutil = None

ROOT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT_DIR / "frontend"

# Terminal colors
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
GRAY = "\033[90m"
RED = "\033[91m"

proc: subprocess.Popen | None = None
running = True


def kill_proc_tree(p: subprocess.Popen):
    """Safely terminate frontend process tree."""
    pid = p.pid
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
            for ch in alive:
                try:
                    ch.kill()
                except Exception:
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    else:
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def stop_frontend(signum=None, frame=None):
    global running, proc
    if not running:
        return
    running = False
    print(f"\n{YELLOW}{BOLD}[ORCHESTRATOR] Shutting down RailSense Unified Frontend...{RESET}")
    if proc:
        kill_proc_tree(proc)
    print(f"{GREEN}{BOLD}[ORCHESTRATOR] Frontend stopped cleanly.{RESET}\n")
    sys.exit(0)


def check_liveness():
    """Probe /user and /admin endpoints until live."""
    print(f"{GRAY}Checking frontend server liveness...{RESET}")
    max_wait = 15
    start_time = time.time()
    online = False

    while (time.time() - start_time) < max_wait:
        time.sleep(1.0)
        try:
            req = urllib.request.Request("http://127.0.0.1:3000/user", headers={"User-Agent": "RailSense-Check"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    online = True
                    break
        except Exception:
            pass

    if online:
        print(f"\n{GREEN}{BOLD}===================================================================={RESET}")
        print(f"{GREEN}{BOLD} RailSense AI Unified Portals are ONLINE on Port 3000{RESET}")
        print(f"{GREEN}{BOLD}===================================================================={RESET}")
        print(f"  {CYAN}{BOLD}User Portal:{RESET}  http://localhost:3000/user")
        print(f"  {YELLOW}{BOLD}Admin Portal:{RESET} http://localhost:3001/admin")
        print(f"  {GRAY}Health API:   http://localhost:3000/api/admin/system-health{RESET}")
        print(f"{GREEN}{BOLD}===================================================================={RESET}")
        print(f"{GRAY}Press Ctrl+C to terminate frontend server.{RESET}\n")
    else:
        print(f"\n{YELLOW}[WAIT] Frontend server starting on http://localhost:3000...{RESET}\n")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    global proc
    signal.signal(signal.SIGINT, stop_frontend)
    signal.signal(signal.SIGTERM, stop_frontend)

    print(f"{BOLD}{CYAN}===================================================================={RESET}")
    print(f"{BOLD}{CYAN} RailSense AI — Unified Frontend Launcher{RESET}")
    print(f"{BOLD}{CYAN} Starting User Portal + Admin Portal on port 3000...{RESET}")
    print(f"{BOLD}{CYAN}===================================================================={RESET}\n")

    # serve.py without RAILSENSE_SIDE serves the user side (3000) and the admin side
    # (3001) from one process; ports and agent URLs come from railsense_ports.json.
    sys.path.insert(0, str(ROOT_DIR))
    from shared import ports as _ports
    cmd = [sys.executable, "serve.py"]
    proc = subprocess.Popen(
        cmd,
        cwd=str(FRONTEND_DIR),
        env={**os.environ, **_ports.service_env(_ports.defaults())},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def stream_logs():
        if proc.stdout:
            for line in iter(proc.stdout.readline, ""):
                if not running:
                    break
                if line:
                    sys.stdout.write(f"{CYAN}[FRONTEND :3000]{RESET} {line}")
                    sys.stdout.flush()

    t = threading.Thread(target=stream_logs, daemon=True)
    t.start()

    checker = threading.Thread(target=check_liveness, daemon=True)
    checker.start()

    try:
        while running:
            code = proc.poll()
            if code is not None and running:
                print(f"\n{RED}[ERROR] Frontend server exited with code {code}{RESET}")
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        stop_frontend()


if __name__ == "__main__":
    main()
