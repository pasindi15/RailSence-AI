"""
M2 Admin Dashboard — data access layer.

Follows the same graceful-degradation philosophy as the rest of M2:
- If Supabase env vars are missing or a call fails, functions return a
  clearly-flagged fallback result instead of raising, so the admin UI
  always renders something and tells the operator what data source is live.

Env vars used (same names as supabase_store.py):
    SUPABASE_URL
    SUPABASE_SECRET_KEY  or  SUPABASE_SERVICE_ROLE_KEY   (server-side writes)

New tables this package introduces (see admin_schema.sql):
    incident_reports      -- reviewable queue for POST /incident-report submissions
    model_training_runs   -- history of retrain metrics
    admin_config          -- small key/value settings store (e.g. alert threshold)
    admin_users           -- simple admin login table (username, password_hash)

Existing tables this package reads (created by supabase_phase5_schema.sql):
    operations_history
    audit_events
    operational_events
    incident_embeddings
"""

from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

try:
    from supabase import create_client, Client  # supabase-py
except ImportError:  # pragma: no cover
    create_client = None
    Client = None

# ---------------------------------------------------------------------------
# Paths — assumes this file lives at M2-operations-agent/admin/admin_db.py
# after you drop it in. Adjust ROOT_DIR if you place it elsewhere.
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
CSV_FALLBACK_PATH = ROOT_DIR / "data" / "operations_history.csv"
LOCAL_CONFIG_PATH = ROOT_DIR / "admin" / "local_admin_config.json"
MODEL_VERSIONS_DIR = ROOT_DIR / "ml" / "model_versions"
TRAINING_LOG_PATH = ROOT_DIR / "admin" / "local_training_runs.json"

_client: Optional["Client"] = None
_client_checked = False


def get_client() -> Optional["Client"]:
    """Lazily create and cache a Supabase client. Returns None if unconfigured."""
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True

    if create_client is None:
        return None

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None

    try:
        _client = create_client(url, key)
    except Exception:
        _client = None
    return _client


def supabase_configured() -> bool:
    return get_client() is not None


def supabase_reachable() -> bool:
    """Cheap connectivity probe — does a tiny read against operations_history."""
    client = get_client()
    if client is None:
        return False
    try:
        client.table("operations_history").select("record_id").limit(1).execute()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Generic table helpers
# ---------------------------------------------------------------------------

def fetch_table(
    table: str,
    limit: int = 50,
    offset: int = 0,
    order_by: Optional[str] = None,
    ascending: bool = False,
    filters: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Generic paginated select(*) with optional equality filters.

    Returns {"rows": [...], "count": int|None, "source": "supabase"|"unavailable"}
    """
    client = get_client()
    if client is None:
        return {"rows": [], "count": None, "source": "unavailable",
                 "error": "Supabase is not configured (SUPABASE_URL / SUPABASE_SECRET_KEY missing)."}

    try:
        query = client.table(table).select("*", count="exact")
        if filters:
            for key, value in filters.items():
                if value not in (None, ""):
                    query = query.eq(key, value)
        if order_by:
            query = query.order(order_by, desc=not ascending)
        query = query.range(offset, offset + limit - 1)
        result = query.execute()
        return {"rows": result.data or [], "count": getattr(result, "count", None), "source": "supabase"}
    except Exception as exc:
        return {"rows": [], "count": None, "source": "unavailable", "error": str(exc)}


def insert_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    client = get_client()
    if client is None:
        return {"ok": False, "error": "Supabase is not configured."}
    try:
        result = client.table(table).insert(row).execute()
        return {"ok": True, "row": (result.data or [None])[0]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def update_row(table: str, pk_field: str, pk_value: Any, patch: dict[str, Any]) -> dict[str, Any]:
    client = get_client()
    if client is None:
        return {"ok": False, "error": "Supabase is not configured."}
    try:
        result = client.table(table).update(patch).eq(pk_field, pk_value).execute()
        return {"ok": True, "row": (result.data or [None])[0]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def delete_row(table: str, pk_field: str, pk_value: Any) -> dict[str, Any]:
    client = get_client()
    if client is None:
        return {"ok": False, "error": "Supabase is not configured."}
    try:
        client.table(table).delete().eq(pk_field, pk_value).execute()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# operations_history — CSV fallback (read-only)
# ---------------------------------------------------------------------------

def fetch_operations_history_csv_fallback(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    if not CSV_FALLBACK_PATH.exists():
        return {"rows": [], "count": 0, "source": "unavailable",
                 "error": f"No CSV fallback found at {CSV_FALLBACK_PATH}"}
    with open(CSV_FALLBACK_PATH, newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    total = len(reader)
    page = reader[offset: offset + limit]
    return {"rows": page, "count": total, "source": "csv_fallback"}


# ---------------------------------------------------------------------------
# admin_config — small key/value store, with local JSON fallback
# ---------------------------------------------------------------------------

def _read_local_config() -> dict[str, Any]:
    if LOCAL_CONFIG_PATH.exists():
        try:
            return json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_local_config(cfg: dict[str, Any]) -> None:
    LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_config(key: str, default: Any = None) -> Any:
    client = get_client()
    if client is not None:
        try:
            result = client.table("admin_config").select("value").eq("key", key).limit(1).execute()
            if result.data:
                return result.data[0]["value"]
        except Exception:
            pass
    return _read_local_config().get(key, default)


def set_config(key: str, value: Any) -> dict[str, Any]:
    client = get_client()
    if client is not None:
        try:
            existing = client.table("admin_config").select("key").eq("key", key).limit(1).execute()
            if existing.data:
                client.table("admin_config").update({"value": value}).eq("key", key).execute()
            else:
                client.table("admin_config").insert({"key": key, "value": value}).execute()
            return {"ok": True, "source": "supabase"}
        except Exception as exc:
            pass  # fall through to local
    cfg = _read_local_config()
    cfg[key] = value
    _write_local_config(cfg)
    return {"ok": True, "source": "local_fallback"}


# ---------------------------------------------------------------------------
# Model version / training-run bookkeeping (local files — always available)
# ---------------------------------------------------------------------------

def log_training_run(run: dict[str, Any]) -> None:
    TRAINING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    runs = []
    if TRAINING_LOG_PATH.exists():
        try:
            runs = json.loads(TRAINING_LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            runs = []
    run["logged_at"] = time.time()
    runs.append(run)
    TRAINING_LOG_PATH.write_text(json.dumps(runs, indent=2), encoding="utf-8")


def get_training_runs() -> list[dict[str, Any]]:
    if not TRAINING_LOG_PATH.exists():
        return []
    try:
        return json.loads(TRAINING_LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def list_model_versions() -> list[dict[str, Any]]:
    if not MODEL_VERSIONS_DIR.exists():
        return []
    versions = []
    for f in sorted(MODEL_VERSIONS_DIR.glob("delay_model_*.pkl"), reverse=True):
        versions.append({
            "filename": f.name,
            "created_at": f.stat().st_mtime,
            "size_bytes": f.stat().st_size,
        })
    return versions
