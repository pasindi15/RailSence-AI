"""
M2 Admin Dashboard — API router.

Integration (main.py), two lines:

    from admin.admin_router import router as admin_router
    app.include_router(admin_router)

Then serve the UI (also two lines, put near your existing "/" mount):

    from fastapi.staticfiles import StaticFiles
    app.mount("/admin", StaticFiles(directory="admin_ui", html=True), name="admin_ui")

(Adjust the StaticFiles `directory=` path to wherever you place the ui/admin
folder from this package — see the top-level README.md for the exact layout.)

All routes are prefixed with /admin/api so they never collide with your
existing passenger-facing routes (/predict-delay, /incident-report, etc).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import admin_db
from .admin_auth import check_login, create_admin_token, require_admin

router = APIRouter(prefix="/admin/api", tags=["admin"])

ROOT_DIR = Path(__file__).resolve().parent.parent
ML_DIR = ROOT_DIR / "ml"


# ============================================================================
# AUTH
# ============================================================================

class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginRequest):
    if not check_login(body.username, body.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_admin_token(body.username)
    return {"token": token, "expires_in_seconds": 8 * 3600}


@router.get("/me")
def me(identity: dict = Depends(require_admin)):
    return {"username": identity.get("sub")}


# ============================================================================
# 1. SYSTEM HEALTH & CONFIG
# ============================================================================

@router.get("/health/status")
def health_status(identity: dict = Depends(require_admin)):
    supabase_configured = admin_db.supabase_configured()
    supabase_ok = admin_db.supabase_reachable() if supabase_configured else False

    upstash_configured = bool(os.getenv("UPSTASH_REDIS_URL") and os.getenv("UPSTASH_REDIS_TOKEN"))

    hub_base = os.getenv("HUB_BASE_URL", "http://localhost:8000")
    hub_reachable = False
    try:
        resp = httpx.get(f"{hub_base}/health", timeout=2.0)
        hub_reachable = resp.status_code < 500
    except Exception:
        hub_reachable = False

    anthropic_configured = bool(os.getenv("ANTHROPIC_API_KEY"))

    return {
        "supabase": {"configured": supabase_configured, "reachable": supabase_ok},
        "upstash": {"configured": upstash_configured},
        "hub": {"base_url": hub_base, "reachable": hub_reachable},
        "anthropic": {"configured": anthropic_configured},
        "checked_at": time.time(),
    }


@router.get("/health/data-sources")
def health_data_sources(identity: dict = Depends(require_admin)):
    """Which dashboard cards are currently live vs. falling back."""
    supabase_ok = admin_db.supabase_reachable()
    csv_exists = admin_db.CSV_FALLBACK_PATH.exists()

    eval_dir = ROOT_DIR / "evaluation"
    ml_metrics = (eval_dir / "ml" / "delay_model_metrics.json").exists()
    nlp_metrics = (eval_dir / "nlp" / "classification_metrics.json").exists()
    rag_metrics = (eval_dir / "rag" / "retrieval_metrics.json").exists()

    return {
        "operations_history": "supabase" if supabase_ok else ("csv_fallback" if csv_exists else "unavailable"),
        "audit_events": "supabase" if supabase_ok else "local_jsonl_fallback",
        "operational_events": "supabase" if supabase_ok else "in_memory_fallback",
        "model_metrics": "local_json" if ml_metrics else "unavailable",
        "nlp_metrics": "local_json" if nlp_metrics else "unavailable",
        "rag_metrics": "local_json" if rag_metrics else "unavailable",
    }


@router.get("/health/config")
def health_config(identity: dict = Depends(require_admin)):
    """Masked view of the important env vars actually in use."""
    def mask(v: Optional[str]) -> str:
        if not v:
            return "(not set)"
        if len(v) <= 8:
            return "*" * len(v)
        return v[:4] + "…" + v[-2:]

    keys = [
        "SUPABASE_URL", "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_KEY", "UPSTASH_REDIS_URL",
        "UPSTASH_REDIS_TOKEN", "ANTHROPIC_API_KEY", "HUB_BASE_URL",
        "HUB_AUTH_TOKEN", "JWT_TOKEN", "OPERATIONS_AGENT_URL",
    ]
    return {k: mask(os.getenv(k)) for k in keys}


# ============================================================================
# 2. DATA MANAGEMENT (operations_history CRUD)
# ============================================================================

class OperationsRecord(BaseModel):
    record_id: Optional[str] = None
    route: str
    station: str
    train_id: str
    scheduled_time: str
    actual_time: Optional[str] = None
    weather: Optional[str] = None
    day_type: Optional[str] = None
    incident_type: Optional[str] = "none"
    incident_note: Optional[str] = None
    delay_minutes: float = Field(ge=0, le=600)


@router.get("/data/operations")
def list_operations(
    limit: int = 50,
    offset: int = 0,
    route: Optional[str] = None,
    incident_type: Optional[str] = None,
    identity: dict = Depends(require_admin),
):
    filters = {}
    if route:
        filters["route"] = route
    if incident_type:
        filters["incident_type"] = incident_type

    result = admin_db.fetch_table(
        "operations_history", limit=limit, offset=offset,
        order_by="scheduled_time", filters=filters,
    )
    if result["source"] == "unavailable":
        result = admin_db.fetch_operations_history_csv_fallback(limit=limit, offset=offset)
    return result


@router.post("/data/operations")
def create_operation(record: OperationsRecord, identity: dict = Depends(require_admin)):
    row = record.model_dump(exclude_none=True)
    result = admin_db.insert_row("operations_history", row)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.put("/data/operations/{record_id}")
def update_operation(record_id: str, patch: dict, identity: dict = Depends(require_admin)):
    patch.pop("record_id", None)
    result = admin_db.update_row("operations_history", "record_id", record_id, patch)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/data/operations/{record_id}")
def delete_operation(record_id: str, identity: dict = Depends(require_admin)):
    result = admin_db.delete_row("operations_history", "record_id", record_id)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/data/operations/import-csv")
async def import_operations_csv(file: UploadFile = File(...), identity: dict = Depends(require_admin)):
    import csv as _csv
    import io

    content = (await file.read()).decode("utf-8")
    reader = _csv.DictReader(io.StringIO(content))
    inserted, failed = 0, []
    for i, row in enumerate(reader):
        clean = {k: v for k, v in row.items() if v not in (None, "")}
        result = admin_db.insert_row("operations_history", clean)
        if result["ok"]:
            inserted += 1
        else:
            failed.append({"row": i, "error": result["error"]})
    return {"inserted": inserted, "failed_count": len(failed), "failures": failed[:20]}


@router.get("/data/quality-check")
def data_quality_check(identity: dict = Depends(require_admin)):
    result = admin_db.fetch_table("operations_history", limit=5000, order_by="scheduled_time")
    rows = result["rows"]
    if not rows:
        return {"checked_rows": 0, "issues": [], "source": result["source"]}

    seen_ids = set()
    duplicates, missing_fields, out_of_range = [], [], []
    required = ["route", "station", "train_id", "scheduled_time", "delay_minutes"]

    for row in rows:
        rid = row.get("record_id")
        if rid in seen_ids:
            duplicates.append(rid)
        seen_ids.add(rid)

        missing = [f for f in required if not row.get(f) and row.get(f) != 0]
        if missing:
            missing_fields.append({"record_id": rid, "missing": missing})

        delay = row.get("delay_minutes")
        try:
            if delay is not None and (float(delay) < 0 or float(delay) > 300):
                out_of_range.append({"record_id": rid, "delay_minutes": delay})
        except (TypeError, ValueError):
            pass

    return {
        "checked_rows": len(rows),
        "source": result["source"],
        "duplicate_ids": duplicates[:50],
        "duplicate_count": len(duplicates),
        "missing_field_rows": missing_fields[:50],
        "missing_field_count": len(missing_fields),
        "out_of_range_rows": out_of_range[:50],
        "out_of_range_count": len(out_of_range),
    }


# ============================================================================
# 3. INCIDENT REVIEW QUEUE
# ============================================================================

class IncidentCorrection(BaseModel):
    classified_type: Optional[str] = None
    summary: Optional[str] = None
    review_status: Optional[str] = None  # "approved" | "rejected" | "corrected"


@router.get("/incidents")
def list_incidents(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    identity: dict = Depends(require_admin),
):
    filters = {"review_status": status} if status else None
    result = admin_db.fetch_table(
        "incident_reports", limit=limit, offset=offset,
        order_by="received_at", filters=filters,
    )
    return result


@router.post("/incidents/{incident_id}/review")
def review_incident(incident_id: str, correction: IncidentCorrection, identity: dict = Depends(require_admin)):
    patch = correction.model_dump(exclude_none=True)
    patch["reviewed_by"] = identity.get("sub")
    patch["reviewed_at"] = time.time()
    result = admin_db.update_row("incident_reports", "incident_id", incident_id, patch)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/incidents/{incident_id}")
def delete_incident(incident_id: str, identity: dict = Depends(require_admin)):
    result = admin_db.delete_row("incident_reports", "incident_id", incident_id)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ============================================================================
# 4. MODEL OPERATIONS
# ============================================================================

@router.get("/model/metrics-history")
def model_metrics_history(identity: dict = Depends(require_admin)):
    runs = admin_db.get_training_runs()
    current_metrics_path = ROOT_DIR / "evaluation" / "ml" / "delay_model_metrics.json"
    current = None
    if current_metrics_path.exists():
        import json
        current = json.loads(current_metrics_path.read_text(encoding="utf-8"))
    return {"runs": runs, "current_metrics": current}


@router.get("/model/feature-importances")
def model_feature_importances(identity: dict = Depends(require_admin)):
    path = ROOT_DIR / "ml" / "feature_importances.json"
    if not path.exists():
        return {"available": False, "features": []}
    import json
    return {"available": True, "features": json.loads(path.read_text(encoding="utf-8"))}


@router.post("/model/retrain")
def retrain_model(identity: dict = Depends(require_admin)):
    """Backs up the current model, retrains, and logs the resulting metrics."""
    import json
    import shutil

    pkl_path = ML_DIR / "delay_model.pkl"
    versions_dir = ROOT_DIR / "ml" / "model_versions"
    versions_dir.mkdir(parents=True, exist_ok=True)

    if pkl_path.exists():
        backup_name = f"delay_model_{int(time.time())}.pkl"
        shutil.copy2(pkl_path, versions_dir / backup_name)

    train_script = ML_DIR / "train_delay_model.py"
    if not train_script.exists():
        raise HTTPException(status_code=500, detail=f"train_delay_model.py not found at {train_script}")

    proc = subprocess.run(
        [sys.executable, str(train_script)],
        cwd=str(ML_DIR),
        capture_output=True, text=True, timeout=600,
    )

    metrics_path = ROOT_DIR / "evaluation" / "ml" / "delay_model_metrics.json"
    metrics = None
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    run_record = {
        "triggered_by": identity.get("sub"),
        "returncode": proc.returncode,
        "metrics": metrics,
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
    }
    admin_db.log_training_run(run_record)

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail={"message": "Training script failed", **run_record})
    return run_record


@router.get("/model/versions")
def model_versions(identity: dict = Depends(require_admin)):
    return {"versions": admin_db.list_model_versions()}


@router.post("/model/rollback/{filename}")
def rollback_model(filename: str, identity: dict = Depends(require_admin)):
    import shutil

    versions_dir = ROOT_DIR / "ml" / "model_versions"
    src = versions_dir / filename
    if not src.exists() or not filename.startswith("delay_model_"):
        raise HTTPException(status_code=404, detail="Model version not found")

    current_pkl = ML_DIR / "delay_model.pkl"
    if current_pkl.exists():
        shutil.copy2(current_pkl, versions_dir / f"delay_model_{int(time.time())}_pre_rollback.pkl")
    shutil.copy2(src, current_pkl)

    admin_db.log_training_run({
        "triggered_by": identity.get("sub"),
        "action": "rollback",
        "restored_from": filename,
    })
    return {"ok": True, "restored_from": filename}


# ============================================================================
# 5. HUB & EVENT CONTROL
# ============================================================================

@router.get("/hub/status")
def hub_status(identity: dict = Depends(require_admin)):
    hub_base = os.getenv("HUB_BASE_URL", "http://localhost:8000")
    reachable = False
    detail = None
    try:
        resp = httpx.get(f"{hub_base}/health", timeout=2.0)
        reachable = resp.status_code < 500
        detail = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
    except Exception as exc:
        detail = str(exc)
    return {"hub_base_url": hub_base, "reachable": reachable, "detail": detail}


@router.get("/hub/events")
def hub_events(limit: int = 50, identity: dict = Depends(require_admin)):
    result = admin_db.fetch_table("operational_events", limit=limit, order_by="created_at")
    return result


@router.post("/hub/test-alert")
def trigger_test_alert(identity: dict = Depends(require_admin)):
    """Publishes a synthetic delay_alert so you can demo the Hub round-trip on demand."""
    event = {
        "event_type": "delay_alert",
        "route": "Colombo Fort - Kandy",
        "train_id": "TEST-ADMIN",
        "predicted_delay_minutes": 12.0,
        "triggered_by": identity.get("sub"),
        "source": "admin_test_alert",
        "created_at": time.time(),
    }

    published_to = []

    upstash_url = os.getenv("UPSTASH_REDIS_URL")
    upstash_token = os.getenv("UPSTASH_REDIS_TOKEN")
    if upstash_url and upstash_token:
        try:
            httpx.post(
                f"{upstash_url}/publish/delay_alert",
                headers={"Authorization": f"Bearer {upstash_token}"},
                json=event, timeout=3.0,
            )
            published_to.append("upstash")
        except Exception:
            pass

    hub_base = os.getenv("HUB_BASE_URL", "http://localhost:8000")
    try:
        httpx.post(f"{hub_base}/events", json=event, timeout=3.0)
        published_to.append("hub")
    except Exception:
        pass

    admin_db.insert_row("operational_events", event)
    return {"event": event, "published_to": published_to}


@router.get("/hub/threshold")
def get_alert_threshold(identity: dict = Depends(require_admin)):
    value = admin_db.get_config("delay_alert_threshold_minutes", default=5)
    return {"delay_alert_threshold_minutes": value}


class ThresholdUpdate(BaseModel):
    delay_alert_threshold_minutes: float = Field(ge=0, le=180)


@router.put("/hub/threshold")
def set_alert_threshold(body: ThresholdUpdate, identity: dict = Depends(require_admin)):
    result = admin_db.set_config("delay_alert_threshold_minutes", body.delay_alert_threshold_minutes)
    return result


# ============================================================================
# 6. AUDIT & ACCESS CONTROL
# ============================================================================

@router.get("/audit/events")
def audit_events(limit: int = 100, offset: int = 0, identity: dict = Depends(require_admin)):
    result = admin_db.fetch_table("audit_events", limit=limit, offset=offset, order_by="created_at")
    if result["source"] == "unavailable":
        # local jsonl fallback
        import json
        log_path = ROOT_DIR / "data" / "audit_log.jsonl"
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            rows = [json.loads(l) for l in lines[-limit:]]
            return {"rows": list(reversed(rows)), "count": len(lines), "source": "jsonl_fallback"}
    return result


@router.get("/audit/summary")
def audit_summary(identity: dict = Depends(require_admin)):
    result = admin_db.fetch_table("audit_events", limit=1000, order_by="created_at")
    rows = result["rows"]
    by_type: dict[str, int] = {}
    for row in rows:
        key = row.get("intent") or row.get("event_type") or row.get("action") or "unknown"
        by_type[key] = by_type.get(key, 0) + 1
    return {"total_sampled": len(rows), "by_type": by_type, "source": result["source"]}
