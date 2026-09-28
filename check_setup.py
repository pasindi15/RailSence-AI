"""RailSense AI — "why doesn't it work on my laptop?" checker.

    python check_setup.py

Checks what differs between teammates' laptops: Python version, each agent's
Python packages, the shared .env keys (names only — values are never printed),
Node.js for the M1 chat app, and the ports. start.py runs a brief version of
this automatically before launching.
"""

from __future__ import annotations

import importlib.metadata as md
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OK, BAD, WARN = "\033[92m✓\033[0m", "\033[91m✗\033[0m", "\033[93m!\033[0m"

REQUIREMENTS = {
    "M1 Passenger Assistant": ROOT / "M1-passenger_assistant" / "backend" / "requirements.txt",
    "M2 Operations Agent": ROOT / "M2-operations-agent" / "requirements.txt",
    "M3 Communication Hub": ROOT / "M3-Comunication-Hub&Booking-Agent" / "agent-hub" / "requirements.txt",
    "M3 Booking Agent": ROOT / "M3-Comunication-Hub&Booking-Agent" / "booking-agent" / "requirements.txt",
    "M4 Maintenance Agent": ROOT / "M4-maintenance-agent" / "requirements.txt",
}
# (key, why, required?) — every teammate needs the SAME values for the shared database
ENV_KEYS = [
    ("SUPABASE_URL", "shared database (all agents)", True),
    ("SUPABASE_SECRET_KEY", "shared database (all agents)", True),
    ("DATABASE_URL", "Hub audit log + Booking agent (Postgres)", True),
    ("NIC_HMAC_SECRET", "NIC hashing for bookings — must be IDENTICAL on every laptop, or duplicate/fraud "
                        "checks disagree on the shared database", True),
    ("JWT_SECRET_KEY", "signed messages between the gateway and the Hub", True),
    ("GEMINI_API_KEY", "LLM answers in the M2 Operations Assistant (rule-based fallback without it)", False),
    ("OPENROUTER_API_KEY", "LLM-written replies in M1 chat (needs the `openai` package too); without it M1 "
                           "answers with the raw FAQ text", False),
    ("SUPABASE_PUBLISHABLE_KEY", "browser-side Supabase features", False),
]


def env_keys(path: Path) -> dict[str, bool]:
    keys = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)", line)
            if m:
                keys[m.group(1)] = bool(m.group(2).strip().strip('"').strip("'"))
    return keys


def missing_packages(req: Path) -> list[str]:
    missing = []
    for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        name = re.split(r"[<>=!~;\[ ]", line, maxsplit=1)[0].strip()
        if not name:
            continue
        try:
            md.version(name)
        except md.PackageNotFoundError:
            missing.append(line)
    return missing


def run(brief: bool = False) -> int:
    problems = 0
    say = (lambda *a: None) if brief else print

    v = sys.version_info
    if v < (3, 10):
        print(f"  {BAD} Python {v.major}.{v.minor}: RailSense needs Python 3.10 or newer")
        problems += 1
    else:
        say(f"  {OK} Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")

    for label, req in REQUIREMENTS.items():
        if not req.exists():
            continue
        miss = missing_packages(req)
        if miss:
            problems += 1
            print(f"  {BAD} {label}: {len(miss)} package(s) missing — run: "
                  f"python -m pip install -r \"{req.relative_to(ROOT)}\"")
            if not brief:
                print("      missing: " + ", ".join(miss[:12]) + (" …" if len(miss) > 12 else ""))
        else:
            say(f"  {OK} {label}: packages installed")

    env_path = ROOT / ".env"
    if not env_path.exists():
        problems += 1
        print(f"  {BAD} No .env in the project root. Copy .env.example to .env and ask the team leader for the "
              "shared values (send them privately — never commit .env).")
    else:
        keys = env_keys(env_path)
        for key, why, required in ENV_KEYS:
            present = keys.get(key) or (key == "SUPABASE_SECRET_KEY" and keys.get("SUPABASE_SERVICE_ROLE_KEY"))
            if present:
                say(f"  {OK} .env {key}")
            elif required:
                problems += 1
                print(f"  {BAD} .env is missing {key} — {why}")
            else:
                print(f"  {WARN} .env has no {key} — {why}")

    npm = shutil.which("npm") or shutil.which("npm.cmd")
    dist = ROOT / "M1-passenger_assistant" / "frontend" / "dist" / "index.html"
    if npm:
        say(f"  {OK} Node.js/npm found (the launcher builds the M1 chat app)")
    elif dist.exists():
        print(f"  {WARN} Node.js/npm not found — using the existing M1 chat build; install Node.js to rebuild it")
    else:
        problems += 1
        print(f"  {BAD} Node.js/npm not found and the M1 chat app is not built — install Node.js LTS "
              "(https://nodejs.org) so /user/chat works")

    try:
        import psutil  # noqa: F401
        say(f"  {OK} psutil installed (precise port clean-up)")
    except ImportError:
        print(f"  {WARN} psutil not installed — ports still work, clean-up is less precise: python -m pip install psutil")

    if not brief:
        sys.path.insert(0, str(ROOT))
        from shared import ports as P
        d = P.defaults()
        print("\n  Ports (from railsense_ports.json):")
        for group in ("public", "internal"):
            for key, port in d[group].items():
                state = "free" if P.is_free(port) else "in use"
                print(f"    {group:8} {key:9} {port:5}  {state}")
        print("  (Busy ports are fine: start.py frees RailSense's own and skips other programs'.)")

    if problems:
        print(f"\n  {problems} problem(s) found. Fix the ✗ items above, then run: python start.py")
    elif not brief:
        print(f"\n  {OK} This laptop is ready. Run: python start.py")
    return problems


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        import os
        os.system("")
    sys.exit(1 if run() else 0)
