"""Best-effort Supabase persistence for maintenance runtime data."""

import os
from pathlib import Path
from typing import Any, Optional

from supabase import create_client

AGENT_DIR = Path(__file__).resolve().parent
_client = None


def _load_root_env() -> None:
    env_path = AGENT_DIR / ".env"
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
        "asset_id": details.get("asset_id"),
        "asset_type": details.get("asset_type"),
        "health_status": details.get("health_status"),
    }
    try:
        client.table("audit_events").insert(payload).execute()
        return True
    except Exception:
        return False


def insert_maintenance_event(event: dict[str, Any]) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.table("operational_events").insert(event).execute()
        return True
    except Exception:
        return False


def fetch_assets_history() -> Optional[list[dict]]:
    """Fetch asset maintenance records from Supabase."""
    client = get_client()
    if client is None:
        return None
    try:
        result = client.table("assets_history").select("*").limit(600).execute()
        return result.data or []
    except Exception:
        return None


def fetch_audit_count() -> Optional[int]:
    client = get_client()
    if client is None:
        return None
    try:
        result = (
            client.table("audit_events")
            .select("id", count="exact")
            .eq("agent_name", "maintenance-agent")
            .execute()
        )
        return result.count or 0
    except Exception:
        return None


def fetch_recent_events(limit: int = 20) -> list[dict]:
    client = get_client()
    if client is None:
        return []
    try:
        result = (
            client.table("operational_events")
            .select("*")
            .eq("sender_agent", "maintenance-agent")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


def match_manual_sections(query_vector: list[float], match_count: int = 3) -> list[dict]:
    """Call pgvector RPC to retrieve similar manual sections."""
    client = get_client()
    if client is None:
        return []
    try:
        result = client.rpc(
            "match_manual_sections",
            {"query_embedding": query_vector, "match_count": match_count},
        ).execute()
        return result.data or []
    except Exception:
        return []
