"""
database/database.py
--------------------
SQLAlchemy engine, session factory, declarative base, and FastAPI dependency
for the Booking Agent's database connection (PostgreSQL/Supabase or SQLite fallback).

Configuration
-------------
Reads DATABASE_URL from the environment (or a .env file via python-dotenv).
Supports Supabase PostgreSQL connection strings directly.
No credentials are stored in source code.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ---------------------------------------------------------------------------
# Load .env from multiple candidate locations
# ---------------------------------------------------------------------------
_CURRENT_DIR = Path(__file__).resolve().parent
_BOOKING_AGENT_DIR = _CURRENT_DIR.parent
_M3_ROOT = _BOOKING_AGENT_DIR.parent
_WORKSPACE_ROOT = _M3_ROOT.parent

for candidate in (
    _BOOKING_AGENT_DIR / ".env",
    _M3_ROOT / ".env",
    _WORKSPACE_ROOT / ".env",
):
    if candidate.is_file():
        load_dotenv(dotenv_path=candidate, override=False)
load_dotenv()

import sys

# ---------------------------------------------------------------------------
# Utility helpers for environment and safe logging
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Resolve and sanitize DATABASE_URL
# ---------------------------------------------------------------------------
raw_db_url = os.getenv("DATABASE_URL")
if is_test_environment() and os.getenv("USE_LIVE_DB") != "1":
    DATABASE_URL = "sqlite:///./railsense_booking.db"
    print("[Booking Agent Database] Active Backend: SQLite (offline test environment)")
elif raw_db_url and raw_db_url.strip():
    DATABASE_URL = sanitize_db_url(raw_db_url)
    print(f"[Booking Agent Database] Active Backend: PostgreSQL/Supabase ({mask_connection_url(DATABASE_URL)})")
else:
    raise RuntimeError(
        "DATABASE_URL is not configured in .env or environment. "
        "A Supabase PostgreSQL connection string is required for application runtime. "
        "(SQLite fallback is strictly restricted to automated test environments)."
    )

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True if not DATABASE_URL.startswith("sqlite") else False,
    echo=False,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)

# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    """Shared declarative base for all Booking Agent ORM models."""
    pass


# ---------------------------------------------------------------------------
# Database setup and seed utility
# ---------------------------------------------------------------------------
def init_db(seed: bool = False) -> None:
    """
    Create all tables in the configured database (PostgreSQL/Supabase or SQLite)
    and optionally seed standard test/development train data.
    """
    # Import models so all tables are registered on Base.metadata
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    if seed:
        from .seed import seed_test_train_data
        with SessionLocal() as db:
            seed_test_train_data(db)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
def get_db() -> Generator[Session, None, None]:
    """
    Yield a SQLAlchemy Session for use as a FastAPI dependency.
    The session is always closed when the request ends, even on errors.
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    do_seed = "--no-seed" not in sys.argv
    print(f"Initializing database: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")
    init_db(seed=do_seed)
    print("Database tables initialized and seeded successfully.")
