"""Best-effort Supabase persistence for maintenance agent runtime data.

Mirrors the pattern used in M2-operations-agent/supabase_store.py.
All functions return False / None on failure so the service stays demoable
when Supabase credentials are not configured.
"""

import os
from pathlib import Path
from typing import Any

from supabase import create_client

ROOT_DIR = Path(__file__).resolve().parents[1]
_client = None


def _load_root_env() -> None:
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_client():
    global _client
    if _client is not None:
        return _client
    _load_root_env()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    if not url or not key:
        return None
    try:
        _client = create_client(url, key)
    except Exception:
        return None
    return _client


def insert_audit(action: str, client_ip: str, details: dict[str, Any]) -> bool:
    client = get_client()
    if client is None:
        return False
    payload = {
        "action": action,
        "agent_name": "maintenance-agent",
        "metadata": {"client": client_ip, **details},
        "train_id": details.get("train_id"),
        "component": details.get("component"),
        "health": details.get("health"),
    }
    try:
        client.table("audit_events").insert(payload).execute()
        return True
    except Exception:
        return False


def insert_maintenance_event(event: dict[str, Any], destinations: list[str]) -> bool:
    client = get_client()
    if client is None:
        return False
    payload = {
        "event_type": event.get("event_type", "maintenance_alert"),
        "sender_agent": "maintenance-agent",
        "train_id": event.get("train_id"),
        "component": event.get("component"),
        "severity": "critical" if event.get("health") == "RED" else "warning",
        "payload": event,
        "published_destinations": destinations,
    }
    try:
        client.table("operational_events").insert(payload).execute()
        return True
    except Exception:
        return False


def insert_maintenance_log(log: dict[str, Any]) -> bool:
    """Persist an ingested sensor log record."""
    client = get_client()
    if client is None:
        return False
    try:
        client.table("maintenance_logs").insert(log).execute()
        return True
    except Exception:
        return False


def fetch_asset_history(train_id: str) -> list[dict] | None:
    """Retrieve recent maintenance logs for a given train."""
    client = get_client()
    if client is None:
        return None
    try:
        response = (
            client.table("maintenance_logs")
            .select("*")
            .eq("train_id", train_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        return response.data or []
    except Exception:
        return None


def fetch_recent_events(limit: int = 50) -> list[dict] | None:
    client = get_client()
    if client is None:
        return None
    try:
        response = (
            client.table("operational_events")
            .select("*")
            .eq("sender_agent", "maintenance-agent")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data or []
    except Exception:
        return None


def count_rows(table: str) -> int | None:
    client = get_client()
    if client is None:
        return None
    try:
        response = client.table(table).select("id", count="exact").limit(1).execute()
        return response.count or 0
    except Exception:
        return None
