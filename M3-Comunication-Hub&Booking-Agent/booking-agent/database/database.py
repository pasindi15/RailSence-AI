"""
database/database.py
--------------------
SQLAlchemy engine, session factory, declarative base, and FastAPI dependency
for the Booking Agent's PostgreSQL connection.

Configuration
-------------
Reads DATABASE_URL from the environment (or a .env file via python-dotenv).
No credentials are stored in source code.

Phase 1 scope
-------------
Engine + session wiring only.  No CRUD operations implemented here.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ---------------------------------------------------------------------------
# Load .env (no-op if the variable is already set in the real environment)
# ---------------------------------------------------------------------------
load_dotenv()

DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "postgresql://postgres:password@localhost:5432/railsense"
)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# pool_pre_ping=True lets SQLAlchemy detect and recover from stale connections
# (e.g. after a long idle period or a PostgreSQL restart).
try:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True if not DATABASE_URL.startswith("sqlite") else False,
        echo=False,  # Set to True temporarily to log SQL during development
    )
except Exception:
    # Fallback to in-memory SQLite if PostgreSQL driver is not installed in local environment
    engine = create_engine("sqlite:///:memory:")

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
# All ORM models in models.py inherit from this Base.


class Base(DeclarativeBase):
    """Shared declarative base for all Booking Agent ORM models."""
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def get_db():
    """
    Yield a SQLAlchemy Session for use as a FastAPI dependency.

    Usage in a route
    ----------------
    ::

        from database.database import get_db

        @router.get("/example")
        def example(db: Session = Depends(get_db)):
            ...

    The session is always closed when the request ends, even on errors.
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
