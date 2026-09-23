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
from typing import Generator, Any

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
_engine_kwargs: dict[str, Any] = {"echo": False}

if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
else:
    _connect_args["connect_timeout"] = 5
    _connect_args["keepalives"] = 1
    _connect_args["keepalives_idle"] = 30
    _connect_args["keepalives_interval"] = 10
    _connect_args["keepalives_count"] = 5
    _engine_kwargs["pool_pre_ping"] = False
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20
    _engine_kwargs["pool_recycle"] = 1800

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    **_engine_kwargs,
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

    # Ensure PostgreSQL custom enum types contain all latest values
    if engine.dialect.name == "postgresql":
        enum_statements = [
            "ALTER TYPE investigation_label ADD VALUE IF NOT EXISTS 'FALSE_POSITIVE'",
            "ALTER TYPE booking_status ADD VALUE IF NOT EXISTS 'HELD'",
            "ALTER TYPE booking_status ADD VALUE IF NOT EXISTS 'PENDING_FRAUD_REVIEW'",
            "ALTER TYPE booking_status ADD VALUE IF NOT EXISTS 'EXPIRED'",
            "ALTER TYPE booking_status ADD VALUE IF NOT EXISTS 'REJECTED'",
            "ALTER TYPE idempotency_status ADD VALUE IF NOT EXISTS 'COMPLETED'",
            "ALTER TYPE idempotency_status ADD VALUE IF NOT EXISTS 'CONFIRMED'",
            "ALTER TYPE waiting_list_status ADD VALUE IF NOT EXISTS 'ALLOCATED'",
        ]
        try:
            import sqlalchemy as sa
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                for stmt in enum_statements:
                    try:
                        conn.execute(sa.text(stmt))
                    except Exception:
                        pass
        except Exception:
            pass

    try:
        with engine.connect() as conn:
            import sqlalchemy as sa
            insp = sa.inspect(conn)
            table_names = insp.get_table_names()
            if "trains" in table_names:
                cols = [c["name"] for c in insp.get_columns("trains")]
                if "maintenance_status" not in cols:
                    conn.execute(sa.text("ALTER TABLE trains ADD COLUMN maintenance_status VARCHAR(100)"))
                if "route" not in cols:
                    conn.execute(sa.text("ALTER TABLE trains ADD COLUMN route VARCHAR(500)"))
                if "origin_station" not in cols:
                    conn.execute(sa.text("ALTER TABLE trains ADD COLUMN origin_station VARCHAR(200)"))
                if "destination_station" not in cols:
                    conn.execute(sa.text("ALTER TABLE trains ADD COLUMN destination_station VARCHAR(200)"))
                if "train_type" not in cols:
                    conn.execute(sa.text("ALTER TABLE trains ADD COLUMN train_type VARCHAR(100)"))
            if "train_schedules" in table_names:
                cols = [c["name"] for c in insp.get_columns("train_schedules")]
                if "service_status" not in cols:
                    conn.execute(sa.text("ALTER TABLE train_schedules ADD COLUMN service_status VARCHAR(50) DEFAULT 'SCHEDULED'"))
                if "service_id" not in cols:
                    conn.execute(sa.text("ALTER TABLE train_schedules ADD COLUMN service_id VARCHAR(100)"))
                if "arrival_date" not in cols:
                    conn.execute(sa.text("ALTER TABLE train_schedules ADD COLUMN arrival_date DATE"))
                try:
                    conn.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_schedules_identity ON train_schedules (train_id, travel_date, from_station, to_station)"))
                except Exception:
                    pass
            if "bookings" in table_names:
                cols = [c["name"] for c in insp.get_columns("bookings")]
                if "ticket_token" not in cols:
                    conn.execute(sa.text("ALTER TABLE bookings ADD COLUMN ticket_token VARCHAR(128)"))
                if "hold_id" not in cols:
                    conn.execute(sa.text("ALTER TABLE bookings ADD COLUMN hold_id INTEGER"))
                if "passenger_phone" not in cols:
                    conn.execute(sa.text("ALTER TABLE bookings ADD COLUMN passenger_phone VARCHAR(32)"))
            if "passengers" in table_names:
                cols = [c["name"] for c in insp.get_columns("passengers")]
                if "phone" not in cols:
                    conn.execute(sa.text("ALTER TABLE passengers ADD COLUMN phone VARCHAR(32)"))
                if "dob" not in cols:
                    conn.execute(sa.text("ALTER TABLE passengers ADD COLUMN dob DATE"))
            if "audit_logs" in table_names:
                cols = [c["name"] for c in insp.get_columns("audit_logs")]
                if "correlation_id" not in cols:
                    conn.execute(sa.text("ALTER TABLE audit_logs ADD COLUMN correlation_id VARCHAR(64)"))
                if "duration_ms" not in cols:
                    conn.execute(sa.text("ALTER TABLE audit_logs ADD COLUMN duration_ms NUMERIC(10, 2)"))
                if "retry_count" not in cols:
                    conn.execute(sa.text("ALTER TABLE audit_logs ADD COLUMN retry_count INTEGER DEFAULT 0"))
            conn.commit()
    except Exception:
        pass

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
