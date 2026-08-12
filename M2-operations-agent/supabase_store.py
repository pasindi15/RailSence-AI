"""Best-effort Supabase persistence for operations runtime data."""

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
        "agent_name": "operations-agent",
        "metadata": {"client": client_ip, **details},
        "route": details.get("route"),
        "train_id": details.get("train_id"),
        "predicted_delay_minutes": details.get("delay"),
        "model_version": details.get("model"),
        "classified_type": details.get("classified_type"),
        "sender_agent": details.get("sender_agent"),
    }
    try:
        client.table("audit_events").insert(payload).execute()
        return True
    except Exception:
        return False


def insert_event(event: dict[str, Any], destinations: list[str]) -> bool:
    client = get_client()
    if client is None:
        return False
    payload = {
        "event_type": event.get("event_type", "delay_alert"),
        "sender_agent": event.get("sender_agent", "operations-agent"),
        "route": event.get("route"),
        "train_id": event.get("train_id"),
        "severity": "critical" if float(event.get("predicted_delay_minutes", 0)) >= 15 else "warning",
        "payload": event,
        "published_destinations": destinations,
    }
    try:
        client.table("operational_events").insert(payload).execute()
        return True
    except Exception:
        return False


def fetch_history() -> list[dict] | None:
    client = get_client()
    if client is None:
        return None
    try:
        rows: list[dict] = []
        page_size = 1000
        for start in range(0, 10000, page_size):
            response = client.table("operations_history").select("*").range(start, start + page_size - 1).execute()
            page = response.data or []
            rows.extend(page)
            if len(page) < page_size:
                break
        return rows
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


def fetch_recent_events(limit: int = 50) -> list[dict] | None:
    client = get_client()
    if client is None:
        return None
    try:
        response = client.table("operational_events").select("*").order("created_at", desc=True).limit(limit).execute()
        return response.data or []
    except Exception:
        return None


def fetch_entities(entity_type: str) -> list[dict] | None:
    client = get_client()
    if client is None:
        return None
    try:
        response = client.table("operation_entities").select("id,data").eq("entity_type", entity_type).order("updated_at", desc=True).execute()
        return [{"id": row["id"], **(row.get("data") or {})} for row in (response.data or [])]
    except Exception:
        return None


def insert_entity(entity_type: str, entity: dict[str, Any]) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        entity_id = str(entity["id"])
        data = {key: value for key, value in entity.items() if key != "id"}
        client.table("operation_entities").upsert({"id": entity_id, "entity_type": entity_type, "data": data}).execute()
        return True
    except Exception:
        return False


def update_entity(entity_type: str, entity_id: str, changes: dict[str, Any]) -> dict | None:
    client = get_client()
    if client is None:
        return None
    try:
        response = client.table("operation_entities").select("id,data").eq("entity_type", entity_type).eq("id", entity_id).limit(1).execute()
        if not response.data:
            return None
        data = {**(response.data[0].get("data") or {}), **changes}
        client.table("operation_entities").update({"data": data}).eq("entity_type", entity_type).eq("id", entity_id).execute()
        return {"id": entity_id, **data}
    except Exception:
        return None


def delete_entity(entity_type: str, entity_id: str) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        response = client.table("operation_entities").delete().eq("entity_type", entity_type).eq("id", entity_id).execute()
        return bool(response.data)
    except Exception:
        return False
