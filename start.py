"""RailSense AI — one launcher for every laptop (Windows, macOS, Linux).

    python start.py              start everything (user side + admin side + all agents)
    python start.py --stop       stop everything this launcher started
    python start.py --status     show which ports are in use and by whom
    python start.py --no-build   skip rebuilding the M1 chat app
    python start.py --no-reload  run the agents without auto-reload (lighter)

Browsers only ever use two ports:
    user side   http://localhost:3000/user    (passenger portal, booking, M1 chat, M2 delay popup)
    admin side  http://localhost:3001/admin   (officers: M2 control room, M3 queues, Hub, M4 maintenance)

Internal agent ports come from railsense_ports.json. If one is busy because an
earlier RailSense run left it behind, that process is stopped; if another
program owns it, the next free port is used. The ports actually chosen are
written to .railsense/ports.runtime.json and handed to every service, so all
agents, the gateway and the browser pages always agree — on every laptop.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from shared import ports as P  # noqa: E402

if sys.platform == "win32":
    os.system("")  # enable ANSI colours in the Windows console
C = {"reset": "\033[0m", "bold": "\033[1m", "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m",
     "blue": "\033[94m", "magenta": "\033[95m", "cyan": "\033[96m", "gray": "\033[90m"}

PYTHON = os.getenv("RAILSENSE_PYTHON") or sys.executable
M3 = ROOT / "M3-Comunication-Hub&Booking-Agent"
SERVICES = [  # key, label, working dir, colour, health path
    ("hub", "M3 Communication Hub", M3 / "agent-hub", "blue", "/health"),
    ("security", "Security & Fraud Agent", ROOT / "security-agent", "yellow", "/health"),
    ("booking", "M3 Booking Agent", M3 / "booking-agent", "green", "/health"),
    ("m2", "M2 Operations Agent", ROOT / "M2-operations-agent", "cyan", "/health"),
    ("m4", "M4 Maintenance Agent", ROOT / "M4-maintenance-agent", "magenta", "/health"),
    ("m1", "M1 Passenger Assistant", ROOT / "M1-passenger_assistant" / "backend", "blue", "/health"),
]
procs: list[tuple[str, subprocess.Popen]] = []


def say(msg, colour=None):
    print(f"{C[colour]}{msg}{C['reset']}" if colour else msg, flush=True)


# ------------------------------------------------------------------ helpers
def stream(tag: str, colour: str, proc: subprocess.Popen) -> None:
    prefix = f"{C[colour]}[{tag}]{C['reset']} "
    for line in iter(proc.stdout.readline, ""):
        if line:
            sys.stdout.write(prefix + line)
            sys.stdout.flush()


def spawn(tag: str, colour: str, cmd: list[str], cwd: Path, env: dict) -> subprocess.Popen:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=flags)
    threading.Thread(target=stream, args=(tag, colour, proc), daemon=True).start()
    procs.append((tag, proc))
    return proc


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "railsense-start"}),
                                    timeout=2) as r:
            return r.status < 500
    except Exception:
        return False


def build_m1(force: bool) -> None:
    app = ROOT / "M1-passenger_assistant" / "frontend"
    dist = app / "dist" / "index.html"
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    newest_src = max((p.stat().st_mtime for p in (app / "src").rglob("*") if p.is_file()), default=0)
    newest_src = max(newest_src, (app / "index.html").stat().st_mtime, (app / "vite.config.js").stat().st_mtime)
    if dist.exists() and dist.stat().st_mtime >= newest_src and not force:
        say("  M1 chat app: up to date", "gray")
        return
    if not npm:
        say("  M1 chat app: Node.js/npm not found — /user/chat will not work until you install Node.js "
            "and run `npm install && npm run build` in M1-passenger_assistant/frontend", "yellow")
        return
    if not (app / "node_modules").exists():
        say("  M1 chat app: installing packages (first run only)…", "gray")
        subprocess.run([npm, "install"], cwd=str(app), check=False)
    say("  M1 chat app: building…", "gray")
    r = subprocess.run([npm, "run", "build"], cwd=str(app))
    if r.returncode != 0:
        say("  M1 chat app: build failed (see above); the rest of RailSense still starts", "yellow")


def stop_all(*_):
    say("\nStopping RailSense AI…", "yellow")
    for tag, proc in procs:
        if proc.poll() is None:
            P.kill(proc.pid)
    try:
        P.RUNTIME_FILE.unlink()
    except OSError:
        pass
    say("All RailSense services stopped.", "green")
    sys.exit(0)


def stop_recorded() -> None:
    """--stop: end the services recorded by the last launch, plus any RailSense leftovers on our ports."""
    import json
    stopped = 0
    if P.RUNTIME_FILE.exists():
        data = json.loads(P.RUNTIME_FILE.read_text(encoding="utf-8"))
        for tag, pid in data.get("pids", {}).items():
            P.kill(pid)
            stopped += 1
        P.RUNTIME_FILE.unlink(missing_ok=True)
    ports = P.defaults()
    for port in [*ports["public"].values(), *ports["internal"].values(), 3002]:
        pid = None if P.is_free(port) else P.owner_pid(port)
        if pid and P.is_railsense(pid, P.command_line(pid)):
            P.kill(pid)
            stopped += 1
    say(f"Stopped {stopped} RailSense process(es).", "green")


def status() -> None:
    ports = P.current()
    for group in ("public", "internal"):
        for key, port in ports[group].items():
            pid = None if P.is_free(port) else P.owner_pid(port)
            who = "free" if pid is None and P.is_free(port) else (
                "RailSense" if pid and P.is_railsense(pid, P.command_line(pid)) else f"other program (pid {pid})")
            say(f"  {group:8} {key:9} {port:5}  {who}")


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description="Start RailSense AI")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--rebuild", action="store_true", help="force a rebuild of the M1 chat app")
    ap.add_argument("--no-reload", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.stop:
        return stop_recorded()
    if args.status:
        return status()

    say("RailSense AI — starting on this laptop", "bold")
    say("1/4 Checking setup", "cyan")
    try:
        import check_setup
        check_setup.run(brief=True)
    except Exception as exc:  # the check must never stop the launch
        say(f"  (setup check skipped: {exc})", "gray")

    say("2/4 Choosing ports", "cyan")
    ports = P.resolve(log=lambda m: say(m, "yellow"))
    env = {**os.environ, **P.service_env(ports), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}

    say("3/4 M1 chat app", "cyan")
    if not args.no_build:
        build_m1(args.rebuild)

    say("4/4 Starting services", "cyan")
    reload = [] if args.no_reload else ["--reload"]
    for key, label, cwd, colour, _ in SERVICES:
        port = ports["internal"][key]
        svc_env = {**env, "PORT": str(port), "APP_PORT": str(port)}
        if key == "security":
            svc_env["SECURITY_AGENT_PORT"] = str(port)
        if key == "m4":
            svc_env["MAINTENANCE_AGENT_PORT"] = str(port)
        # A service with its own venv (e.g. M1, which needs the exact chromadb
        # version its on-disk .chroma index was built with) must be run with
        # that venv's Python, never the interpreter that launched start.py -
        # otherwise it silently loads a different package version and RAG
        # retrieval fails with KeyError: '_type'.
        venv_python = cwd / "venv" / ("Scripts" if sys.platform == "win32" else "bin") / (
            "python.exe" if sys.platform == "win32" else "python")
        service_python = str(venv_python) if venv_python.exists() else PYTHON
        say(f"  [launcher] {label} -> {service_python}", "gray")
        spawn(f"{label} :{port}", colour, [service_python, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
                                           "--port", str(port), *reload], cwd, svc_env)
    for side in ("user", "admin"):
        port = ports["public"][side]
        spawn(f"Gateway {side} :{port}", "magenta" if side == "admin" else "green",
              [PYTHON, "serve.py"], ROOT / "frontend", {**env, "PORT": str(port), "RAILSENSE_SIDE": side})
    P.write_runtime(ports, {tag: p.pid for tag, p in procs})

    signal.signal(signal.SIGINT, stop_all)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop_all)

    checks = {label: P.url(ports["internal"][key]) + health for key, label, _, _, health in SERVICES}
    checks["User side"] = P.url(ports["public"]["user"]) + "/user"
    checks["Admin side"] = P.url(ports["public"]["admin"]) + "/admin"
    pending, deadline = dict(checks), time.time() + 120
    while pending and time.time() < deadline:
        time.sleep(2)
        for name, u in list(pending.items()):
            if healthy(u):
                pending.pop(name)
        for tag, proc in procs:
            if proc.poll() is not None and not getattr(proc, "_reported", False):
                proc._reported = True
                say(f"  ✗ {tag} exited (code {proc.returncode}) — see its log lines above", "red")

    say("\n" + "=" * 66, "green")
    for name in checks:
        ok = name not in pending
        say(f"  {'✓' if ok else '…'} {name:<26} {'ready' if ok else 'still starting / failed'}",
            "green" if ok else "yellow")
    say(f"\n  Passenger / user side : http://localhost:{ports['public']['user']}/user", "bold")
    say(f"  Officer / admin side  : http://localhost:{ports['public']['admin']}/admin", "bold")
    say("=" * 66 + "\n  Press Ctrl+C to stop everything.\n", "green")

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
