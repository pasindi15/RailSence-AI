"""Read-only access to the canonical Supabase train registry.

This module contains no agent business logic. M1 and M2 use it to resolve the
same train identity before applying their existing local workflows.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

ROOT_DIR = Path(__file__).resolve().parents[1]
_client: Client | None = None


class TrainRepositoryUnavailable(RuntimeError):
    """Raised when the canonical train database cannot be reached/configured."""


def _load_root_env() -> None:
    load_dotenv(ROOT_DIR / ".env", override=False)


def get_client() -> Client:
    global _client
    if _client is not None:
        return _client
    _load_root_env()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    if not url or not key:
        raise TrainRepositoryUnavailable("Canonical train database is not configured")
    try:
        _client = create_client(url, key)
    except Exception as exc:
        raise TrainRepositoryUnavailable("Canonical train database client could not be created") from exc
    return _client


def get_train(train_id: str) -> dict[str, Any] | None:
    """Return the canonical train row for an exact public train_id."""
    clean_id = (train_id or "").strip().upper()
    if not clean_id:
        return None
    try:
        response = (
            get_client()
            .table("trains")
            .select("*")
            .eq("train_id", clean_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise TrainRepositoryUnavailable("Canonical train lookup failed") from exc
    return response.data[0] if response.data else None


def search_trains(
    origin: str | None = None,
    destination: str | None = None,
) -> list[dict[str, Any]]:
    """Search canonical train identities by optional origin/destination."""
    try:
        query = get_client().table("trains").select("*").eq("active", True)
        if origin:
            query = query.ilike("origin_station", f"%{origin.strip()}%")
        if destination:
            query = query.ilike("destination_station", f"%{destination.strip()}%")
        response = query.order("train_id").execute()
    except Exception as exc:
        raise TrainRepositoryUnavailable("Canonical train search failed") from exc
    return response.data or []


def get_train_schedule(train_id: str) -> list[dict[str, Any]]:
    """Return date-specific schedules linked to a canonical train row."""
    train = get_train(train_id)
    if train is None:
        return []
    try:
        response = (
            get_client()
            .table("train_schedules")
            .select("*")
            .eq("train_id", train["id"])
            .order("travel_date")
            .execute()
        )
    except Exception as exc:
        raise TrainRepositoryUnavailable("Canonical train schedule lookup failed") from exc
    return response.data or []
