"""
M2 Admin Dashboard — data access layer.

Follows the same graceful-degradation philosophy as the rest of M2:
- Primary storage in Supabase Postgres.
- If Supabase env vars are missing or network is unreachable, functions
  transparently fall back to local JSON/CSV stores so the system always functions.

Tables handled:
    officers              -- RBAC officers (id, full_name, email, password_hash, role, status, etc.)
    officer_audit_logs    -- security audit events (LOGIN, LOGOUT, OFFICER_CREATED, ROLE_CHANGED, etc.)
    incident_reports      -- reviewable queue for POST /incident-report submissions
    model_training_runs   -- history of retrain metrics
    admin_config          -- small key/value settings store (e.g. alert threshold)
    operations_history    -- historical trips
    audit_events          -- inter-agent audit trail
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Optional
import uuid

try:
    from supabase import create_client, Client  # supabase-py
except ImportError:  # pragma: no cover
    create_client = None
    Client = None

logger = logging.getLogger("railsense.admin_db")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
CSV_FALLBACK_PATH = ROOT_DIR / "data" / "operations_history.csv"
LOCAL_CONFIG_PATH = ROOT_DIR / "admin" / "local_admin_config.json"
LOCAL_OFFICERS_PATH = ROOT_DIR / "data" / "officers.json"
LOCAL_AUDIT_LOGS_PATH = ROOT_DIR / "data" / "officer_audit_logs.jsonl"
MODEL_VERSIONS_DIR = ROOT_DIR / "ml" / "model_versions"
TRAINING_LOG_PATH = ROOT_DIR / "admin" / "local_training_runs.json"

_client: Optional["Client"] = None
_client_checked = False


def _load_root_env() -> None:
    """Load the shared workspace root .env so the backend uses the real project creds."""
    root_dir = Path(__file__).resolve().parent.parent
    env_candidates = [
        root_dir / ".env",
        root_dir.parent / ".env",
    ]
    for env_path in env_candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_client() -> Optional["Client"]:
    """Lazily create and cache a Supabase client. Returns None if unconfigured."""
    global _client, _client_checked
    if _client_checked and _client is not None:
        return _client
    _client_checked = True

    if create_client is None:
        return None

    _load_root_env()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None

    try:
        _client = create_client(url, key)
    except Exception as exc:
        logger.warning("Failed to initialize Supabase client: %s", exc)
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
    """Generic paginated select(*) with optional equality filters."""
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
# Officers Repository (Supabase + Local JSON Fallback)
# ---------------------------------------------------------------------------

def _load_local_officers() -> list[dict[str, Any]]:
    if LOCAL_OFFICERS_PATH.exists():
        try:
            return json.loads(LOCAL_OFFICERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_local_officers(officers: list[dict[str, Any]]) -> None:
    LOCAL_OFFICERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_OFFICERS_PATH.write_text(json.dumps(officers, indent=2, default=str), encoding="utf-8")


def get_officer_by_email(email: str) -> Optional[dict[str, Any]]:
    clean_email = email.strip().lower()
    client = get_client()
    if client is not None:
        try:
            res = client.table("officers").select("*").eq("email", clean_email).limit(1).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
        except Exception as exc:
            logger.warning("Supabase get_officer_by_email error: %s", exc)

    # Local fallback
    for off in _load_local_officers():
        if off.get("email", "").lower() == clean_email:
            return off
    return None


def get_officer_by_id(officer_id: str) -> Optional[dict[str, Any]]:
    officer_id_str = str(officer_id).strip()
    client = get_client()
    if client is not None:
        try:
            res = client.table("officers").select("*").eq("id", officer_id_str).limit(1).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
        except Exception as exc:
            logger.warning("Supabase get_officer_by_id error: %s", exc)

    for off in _load_local_officers():
        if str(off.get("id")) == officer_id_str:
            return off
    return None


def list_officers(
    limit: int = 100,
    offset: int = 0,
    role: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> dict[str, Any]:
    client = get_client()
    if client is not None:
        try:
            query = client.table("officers").select(
                "id, full_name, email, role, status, created_at, updated_at, last_login_at, created_by",
                count="exact"
            )
            if role:
                query = query.eq("role", role)
            if status:
                query = query.eq("status", status)
            if search:
                query = query.or_(f"full_name.ilike.%{search}%,email.ilike.%{search}%")
            query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
            res = query.execute()
            return {"officers": res.data or [], "total": res.count or len(res.data or []), "source": "supabase"}
        except Exception as exc:
            logger.warning("Supabase list_officers error: %s", exc)

    # Local fallback
    local = _load_local_officers()
    filtered = []
    for o in local:
        if role and o.get("role") != role:
            continue
        if status and o.get("status") != status:
            continue
        if search:
            s = search.lower()
            if s not in o.get("full_name", "").lower() and s not in o.get("email", "").lower():
                continue
        filtered.append({k: v for k, v in o.items() if k != "password_hash"})

    total = len(filtered)
    page = filtered[offset: offset + limit]
    return {"officers": page, "total": total, "source": "local_fallback"}


def create_officer(officer: dict[str, Any]) -> dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        "id": officer.get("id") or str(uuid.uuid4()),
        "full_name": officer["full_name"].strip(),
        "email": officer["email"].strip().lower(),
        "password_hash": officer["password_hash"],
        "role": officer.get("role", "operations_engineer"),
        "status": officer.get("status", "active"),
        "created_at": officer.get("created_at") or now_iso,
        "updated_at": officer.get("updated_at") or now_iso,
        "last_login_at": officer.get("last_login_at"),
        "created_by": officer.get("created_by", "system"),
    }

    client = get_client()
    if client is not None:
        try:
            res = client.table("officers").insert(record).execute()
            if res.data:
                # Also mirror locally
                local = _load_local_officers()
                local = [o for o in local if o.get("email") != record["email"]]
                local.insert(0, res.data[0])
                _save_local_officers(local)
                return res.data[0]
        except Exception as exc:
            logger.warning("Supabase create_officer error: %s", exc)

    # Local fallback
    local = _load_local_officers()
    local = [o for o in local if o.get("email") != record["email"]]
    local.insert(0, record)
    _save_local_officers(local)
    return record


def update_officer(officer_id: str, patch: dict[str, Any]) -> Optional[dict[str, Any]]:
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    officer_id_str = str(officer_id).strip()

    client = get_client()
    if client is not None:
        try:
            res = client.table("officers").update(patch).eq("id", officer_id_str).execute()
            if res.data and len(res.data) > 0:
                updated = res.data[0]
                # Mirror locally
                local = _load_local_officers()
                for i, o in enumerate(local):
                    if str(o.get("id")) == officer_id_str:
                        local[i] = updated
                        break
                _save_local_officers(local)
                return updated
        except Exception as exc:
            logger.warning("Supabase update_officer error: %s", exc)

    # Local fallback
    local = _load_local_officers()
    for i, o in enumerate(local):
        if str(o.get("id")) == officer_id_str:
            local[i].update(patch)
            _save_local_officers(local)
            return local[i]
    return None


def count_active_admins() -> int:
    """Count active administrators to guard against accidental lockout."""
    client = get_client()
    if client is not None:
        try:
            res = client.table("officers").select("id", count="exact").eq("role", "admin").eq("status", "active").execute()
            if res.count is not None:
                return res.count
            return len(res.data or [])
        except Exception as exc:
            logger.warning("Supabase count_active_admins error: %s", exc)

    local = _load_local_officers()
    return sum(1 for o in local if o.get("role") == "admin" and o.get("status") == "active")


# ---------------------------------------------------------------------------
# Officer Security Audit Logging
# ---------------------------------------------------------------------------

def record_officer_audit(
    action: str,
    actor: dict[str, Any],
    details: dict[str, Any],
    target: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> None:
    """Record a security-sensitive event in Supabase and local JSONL."""
    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        "id": str(uuid.uuid4()),
        "timestamp": now_iso,
        "action": action.upper(),
        "actor_id": str(actor.get("id") or actor.get("sub") or "system"),
        "actor_name": actor.get("name") or actor.get("full_name") or "System",
        "actor_email": actor.get("email") or "system@railsense.lk",
        "actor_role": actor.get("role") or "system",
        "target_officer_id": str(target.get("id") or "") if target else None,
        "target_officer_email": target.get("email") if target else None,
        "details": details or {},
        "ip_address": ip_address or "127.0.0.1",
    }

    # Always write to local audit log jsonl
    try:
        LOCAL_AUDIT_LOGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOCAL_AUDIT_LOGS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:
        logger.warning("Failed writing to local audit jsonl: %s", exc)

    client = get_client()
    if client is not None:
        try:
            client.table("officer_audit_logs").insert(record).execute()
        except Exception as exc:
            logger.warning("Supabase record_officer_audit error: %s", exc)


def list_officer_audits(limit: int = 100, offset: int = 0, action: Optional[str] = None) -> dict[str, Any]:
    client = get_client()
    if client is not None:
        try:
            query = client.table("officer_audit_logs").select("*", count="exact")
            if action:
                query = query.eq("action", action.upper())
            query = query.order("timestamp", desc=True).range(offset, offset + limit - 1)
            res = query.execute()
            return {"rows": res.data or [], "count": res.count or len(res.data or []), "source": "supabase"}
        except Exception as exc:
            logger.warning("Supabase list_officer_audits error: %s", exc)

    # Local fallback
    if LOCAL_AUDIT_LOGS_PATH.exists():
        try:
            lines = LOCAL_AUDIT_LOGS_PATH.read_text(encoding="utf-8").strip().splitlines()
            records = [json.loads(l) for l in lines if l.strip()]
            if action:
                records = [r for r in records if r.get("action") == action.upper()]
            records = list(reversed(records))
            total = len(records)
            page = records[offset: offset + limit]
            return {"rows": page, "count": total, "source": "local_fallback"}
        except Exception:
            pass
    return {"rows": [], "count": 0, "source": "local_fallback"}


# ---------------------------------------------------------------------------
# Initial Admin Provisioning
# ---------------------------------------------------------------------------

def seed_initial_admin_if_needed() -> None:
    """Bootstraps the first administrator account if no admins exist."""
    from .admin_auth import hash_password

    if count_active_admins() > 0:
        return

    _load_root_env()
    email = os.getenv("ADMIN_INITIAL_EMAIL") or os.getenv("ADMIN_EMAIL", "admin@railsense.lk")
    password = os.getenv("ADMIN_INITIAL_PASSWORD") or os.getenv("ADMIN_PASSWORD", "OperationsAdmin2026!")

    existing = get_officer_by_email(email)
    if existing:
        if existing.get("role") != "admin" or existing.get("status") != "active":
            update_officer(existing["id"], {"role": "admin", "status": "active"})
        return

    admin_record = {
        "id": str(uuid.uuid4()),
        "full_name": "Chief Operations Administrator",
        "email": email.strip().lower(),
        "password_hash": hash_password(password),
        "role": "admin",
        "status": "active",
        "created_by": "bootstrap",
    }
    created = create_officer(admin_record)
    record_officer_audit(
        action="OFFICER_CREATED",
        actor={"name": "System Bootstrap", "email": "system@railsense.lk", "role": "system"},
        details={"note": "Initial administrator account provisioned during startup", "role": "admin"},
        target={"id": created.get("id"), "email": email},
    )
    logger.info("Provisioned initial administrator account: %s", email)


# ---------------------------------------------------------------------------
# Config & Training Runs
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
        except Exception:
            pass
    cfg = _read_local_config()
    cfg[key] = value
    _write_local_config(cfg)
    return {"ok": True, "source": "local_fallback"}


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
