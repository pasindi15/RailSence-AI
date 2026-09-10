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
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

# Path resolution to access models and shared packages
_CURRENT_DIR = os.path.dirname(__file__)
_MEMBER_C_ROOT = os.path.abspath(os.path.join(_CURRENT_DIR, ".."))
_BOOKING_AGENT_DIR = os.path.join(_MEMBER_C_ROOT, "booking-agent")

for p in (_CURRENT_DIR, _MEMBER_C_ROOT, _BOOKING_AGENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from database.models import AuditLog, AuditStatus, Base  # noqa: E402

DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///./railsense_hub_audit.db"

# Engine setup
_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

try:
    engine = create_engine(
        DATABASE_URL,
        connect_args=_connect_args,
        pool_pre_ping=True if not DATABASE_URL.startswith("sqlite") else False,
        echo=False,
    )
except Exception:
    engine = create_engine(
        "sqlite:///./railsense_hub_audit.db",
        connect_args={"check_same_thread": False},
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
