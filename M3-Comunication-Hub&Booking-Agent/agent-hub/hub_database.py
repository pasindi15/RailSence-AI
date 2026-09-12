"""
agent-hub/hub_database.py
-------------------------
Database connection and session factory for the Central Agent Communication Hub.
Phase 2: Audit log persistence.

Architectural rules:
- Reads DATABASE_URL from environment / config.
- Supports PostgreSQL for production/staging and SQLite for testing/development.
- Provides get_db() FastAPI dependency with automatic cleanup.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Path resolution to access models and shared packages
_CURRENT_DIR = Path(__file__).resolve().parent
_MEMBER_C_ROOT = _CURRENT_DIR.parent
_BOOKING_AGENT_DIR = _MEMBER_C_ROOT / "booking-agent"
_WORKSPACE_ROOT = _MEMBER_C_ROOT.parent

for p in (str(_CURRENT_DIR), str(_MEMBER_C_ROOT), str(_BOOKING_AGENT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

for candidate in (
    _CURRENT_DIR / ".env",
    _MEMBER_C_ROOT / ".env",
    _WORKSPACE_ROOT / ".env",
):
    if candidate.is_file():
        load_dotenv(dotenv_path=candidate, override=False)
load_dotenv()

from database.models import AuditLog, AuditStatus, Base  # noqa: E402


def is_test_environment() -> bool:
    """Check if running inside pytest or explicit automated test environment."""
    return (
        "PYTEST_CURRENT_TEST" in os.environ
        or os.getenv("TESTING", "").lower() in ("1", "true")
        or any("pytest" in arg.lower() for arg in sys.argv)
    )


def mask_connection_url(url: str) -> str:
    """Mask database credentials for safe logging without printing secrets."""
    if "@" in url and "://" in url:
        prefix, rest = url.split("://", 1)
        _, host_port_db = rest.rsplit("@", 1)
        return f"{prefix}://***:***@{host_port_db}"
    return url


def sanitize_db_url(url: str) -> str:
    """Sanitize database URL by mapping postgres:// to postgresql:// and safely percent-encoding passwords."""
    import urllib.parse
    cleaned = url.strip()
    if cleaned.startswith("postgres://"):
        cleaned = "postgresql://" + cleaned[len("postgres://"):]
    if "://" in cleaned and "@" in cleaned:
        scheme, rest = cleaned.split("://", 1)
        at_idx = rest.rfind("@")
        userinfo = rest[:at_idx]
        host_db = rest[at_idx + 1:]
        if ":" in userinfo:
            user, password = userinfo.split(":", 1)
            unquoted_pw = urllib.parse.unquote(password)
            encoded_pw = urllib.parse.quote(unquoted_pw, safe="")
            return f"{scheme}://{user}:{encoded_pw}@{host_db}"
    return cleaned


raw_db_url = os.getenv("DATABASE_URL")
if is_test_environment() and os.getenv("USE_LIVE_DB") != "1":
    DATABASE_URL = "sqlite:///./railsense_hub_audit.db"
    print("[Hub Database] Active Backend: SQLite (offline test environment)")
elif raw_db_url and raw_db_url.strip():
    DATABASE_URL = sanitize_db_url(raw_db_url)
    print(f"[Hub Database] Active Backend: PostgreSQL/Supabase ({mask_connection_url(DATABASE_URL)})")
else:
    raise RuntimeError(
        "DATABASE_URL is not configured in .env or environment. "
        "A Supabase PostgreSQL connection string is required for application runtime. "
        "(SQLite fallback is strictly restricted to automated test environments)."
    )

# Engine setup
_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True if not DATABASE_URL.startswith("sqlite") else False,
    echo=False,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


def init_db() -> None:
    """Create audit tables if they do not exist."""
    try:
        Base.metadata.create_all(bind=engine, tables=[AuditLog.__table__])
    except Exception:
        # Avoid crashing startup if remote database is not yet ready
        pass

# Initialize audit tables immediately for SQLite or local databases
init_db()


def get_db() -> Generator[Session, None, None]:
    """
    Yield an active SQLAlchemy database session for FastAPI dependencies.
    Ensures connection is closed cleanly after request handling.
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
