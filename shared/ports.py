"""RailSense AI port registry (shared by the launchers and the gateway).

`railsense_ports.json` holds the default ports. `start.py` resolves them on each
laptop (freeing ports RailSense itself left behind, moving past ports another
program owns) and writes the result to `.railsense/ports.runtime.json`, which
every service and the browser config then follow. Nothing else should hard-code
a port.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS_FILE = ROOT / "railsense_ports.json"
RUNTIME_DIR = ROOT / ".railsense"
RUNTIME_FILE = RUNTIME_DIR / "ports.runtime.json"

# internal service key -> the env var names other services read to reach it
URL_ENV = {
    "m1": ["PASSENGER_AGENT_URL"],
    "hub": ["AGENT_HUB_URL", "HUB_BASE_URL", "HUB_URL"],
    "booking": ["BOOKING_AGENT_URL"],
    "security": ["SECURITY_AGENT_URL"],
    "m2": ["OPERATIONS_AGENT_URL"],
    "m4": ["MAINTENANCE_AGENT_URL"],
}


def defaults() -> dict:
    data = json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
    return {"public": dict(data["public"]), "internal": dict(data["internal"])}


def current() -> dict:
    """Ports in effect: the launcher's runtime file if present, else the defaults."""
    if RUNTIME_FILE.exists():
        try:
            data = json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))
            return {"public": dict(data["public"]), "internal": dict(data["internal"])}
        except (OSError, ValueError, KeyError):
            pass
    return defaults()


def write_runtime(ports: dict, pids: dict | None = None) -> None:
    RUNTIME_DIR.mkdir(exist_ok=True)
    payload = {**ports, "pids": pids or {}}
    RUNTIME_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def service_env(ports: dict) -> dict[str, str]:
    """Environment every RailSense process gets, so they all agree on addresses.

    Process environment beats each laptop's .env (load_dotenv never overrides),
    so a stale or missing .env entry can no longer point a service at the wrong port.
    """
    env = {}
    for key, names in URL_ENV.items():
        for name in names:
            env[name] = url(ports["internal"][key])
    env["RAILSENSE_ROOT"] = str(ROOT)  # marks processes as ours (see is_railsense)
    env["RAILSENSE_USER_PORT"] = str(ports["public"]["user"])
    env["RAILSENSE_ADMIN_PORT"] = str(ports["public"]["admin"])
    for key, port in ports["internal"].items():
        env[f"RAILSENSE_{key.upper()}_PORT"] = str(port)
    return env


# ---------------------------------------------------------------- port checks
def is_free(port: int) -> bool:
    """True only if nothing answers on the port and we can bind it ourselves."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return False
    for host in ("127.0.0.1", "0.0.0.0"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                return False
    return True


def owner_pid(port: int) -> int | None:
    """PID listening on a port (psutil if installed, else netstat / lsof)."""
    try:
        import psutil
        for c in psutil.net_connections(kind="tcp"):
            if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN and c.pid:
                return c.pid
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].rsplit(":", 1)[-1] == str(port):
                    return int(parts[4])
        else:
            out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                                 capture_output=True, text=True, timeout=10).stdout.split()
            if out:
                return int(out[0])
    except Exception:
        pass
    return None


def command_line(pid: int) -> str:
    try:
        import psutil
        return " ".join(psutil.Process(pid).cmdline())
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                                 capture_output=True, text=True, timeout=15).stdout
        else:
            out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                                 timeout=10).stdout
        return out.strip()
    except Exception:
        return ""


def is_railsense(pid: int, cmd: str) -> bool:
    """True only when the process provably belongs to THIS repository.

    Evidence: the launcher's RAILSENSE_ROOT marker in its environment, a working
    directory inside the repo, or the repo path in its command line. Anything we
    can't prove is treated as someone else's program and never stopped.
    """
    root = os.path.normcase(str(ROOT))
    if root in os.path.normcase(cmd):
        return True
    try:
        import psutil
        p = psutil.Process(pid)
        try:
            if os.path.normcase(p.environ().get("RAILSENSE_ROOT", "")) == root:
                return True
        except Exception:
            pass
        procs = [p] + p.parents()[:2]  # uvicorn --reload workers are children of the launcher process
        for q in procs:
            try:
                if os.path.normcase(q.cwd()).startswith(root):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def kill(pid: int) -> None:
    try:
        import psutil
        p = psutil.Process(pid)
        for child in p.children(recursive=True):
            child.kill()
        p.kill()
        return
    except Exception:
        pass
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        subprocess.run(["kill", "-9", str(pid)], capture_output=True)


def resolve(log=print) -> dict:
    """Default ports, made usable on this laptop.

    Busy port held by an earlier RailSense run -> stop it and reuse the port.
    Busy port held by any other program       -> leave it alone, use the next free port.
    """
    import time
    ports = defaults()
    taken: set[int] = set()
    for group in ("public", "internal"):
        for key, port in ports[group].items():
            p = port
            while True:
                if p not in taken and is_free(p):
                    break
                if p not in taken:
                    pid = owner_pid(p)
                    cmd = command_line(pid) if pid else ""
                    if pid and is_railsense(pid, cmd):
                        log(f"  port {p}: stopping an earlier RailSense process (pid {pid})")
                        kill(pid)
                        for _ in range(20):
                            time.sleep(0.25)
                            if is_free(p):
                                break
                        if is_free(p):
                            break
                    else:
                        log(f"  port {p}: in use by another program{f' (pid {pid})' if pid else ''}, looking for a free one")
                p += 1
            if p != port:
                log(f"  {group}.{key}: {port} -> {p}")
            ports[group][key] = p
            taken.add(p)
    return ports
