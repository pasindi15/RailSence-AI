"""
M2 Admin Dashboard & Operations RBAC API Router.

Prefix: /admin/api

Endpoints:
    Auth:
        POST /login             -> Authenticates officer, returns JWT token & user profile
        POST /logout            -> Audits officer logout
        GET  /me                -> Returns current officer identity, role, permissions

    Officers & Access (Admin Only):
        GET    /officers                   -> List officers (paginated, filtered, searched)
        POST   /officers                   -> Create officer (hashed password, audited)
        GET    /officers/{id}              -> Officer details
        PUT    /officers/{id}              -> Update officer (role change & lockout guards)
        POST   /officers/{id}/reset-password -> Reset temporary password
        POST   /officers/{id}/status       -> Toggle active/inactive with lockout guard
        GET    /officers/audit             -> Security audit trail
        GET    /roles/matrix               -> RBAC capability matrix

    M2 Admin Console Features (Admin Only):
        System Health & Config (/health/*)
        Data Management (/data/*)
        Incident Reports Queue (/incident-reports/*)
        Model Operations (/model/*)
        Hub & Event Control (/hub/*)
        General Audit Logs (/audit/*)
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Body, Depends, File, HTTPException, Header, Query, Request, UploadFile, status
from pydantic import BaseModel, EmailStr, Field

from . import admin_db
from .admin_auth import (
    ROLE_ADMIN,
    ROLE_OPERATIONS_ENGINEER,
    ROLE_PERMISSIONS,
    ROLE_DISPLAY_NAMES,
    create_officer_token,
    get_current_officer,
    get_permissions_for_role,
    hash_password,
    require_admin,
    require_authenticated_officer,
    require_role,
    verify_password,
)

router = APIRouter(prefix="/admin/api", tags=["admin"])

ROOT_DIR = Path(__file__).resolve().parent.parent
ML_DIR = ROOT_DIR / "ml"


# ============================================================================
# Schemas
# ============================================================================

class LoginRequest(BaseModel):
    email: Optional[str] = None
    username: Optional[str] = None
    password: str


class OfficerCreateRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field(default=ROLE_OPERATIONS_ENGINEER)
    status: str = Field(default="active")


class OfficerUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=255)
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    status: Optional[str] = None


class OfficerPasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


class OfficerStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(active|inactive)$")


# ============================================================================
# AUTH ENDPOINTS
# ============================================================================

@router.post("/login")
def login(body: LoginRequest, request: Request):
    """Authenticate officer via email (or username) and password. Issues JWT."""
    admin_db.seed_initial_admin_if_needed()

    login_identifier = (body.email or body.username or "").strip()
    if not login_identifier or not body.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required.",
        )

    officer = admin_db.get_officer_by_email(login_identifier)

    # If user used a username instead of an email, try adding @railsense.lk
    if not officer and "@" not in login_identifier:
        officer = admin_db.get_officer_by_email(f"{login_identifier}@railsense.lk")

    client_ip = request.client.host if request.client else "127.0.0.1"

    if not officer:
        admin_db.record_officer_audit(
            action="UNAUTHORIZED_ACCESS_ATTEMPT",
            actor={"name": "Unknown", "email": login_identifier, "role": "anonymous"},
            details={"reason": "User not found", "attempted_identifier": login_identifier},
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    # Check active status first
    if officer.get("status") == "inactive":
        admin_db.record_officer_audit(
            action="UNAUTHORIZED_ACCESS_ATTEMPT",
            actor={"id": officer.get("id"), "name": officer.get("full_name"), "email": officer.get("email"), "role": officer.get("role")},
            details={"reason": "Account is inactive"},
            target={"id": officer.get("id"), "email": officer.get("email")},
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account inactive. Please contact an administrator.",
        )

    # Verify password hash
    password_hash = officer.get("password_hash", "")
    if not verify_password(body.password, password_hash):
        admin_db.record_officer_audit(
            action="UNAUTHORIZED_ACCESS_ATTEMPT",
            actor={"id": officer.get("id"), "name": officer.get("full_name"), "email": officer.get("email"), "role": officer.get("role")},
            details={"reason": "Password mismatch"},
            target={"id": officer.get("id"), "email": officer.get("email")},
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    # Update last_login_at
    now_iso = datetime.now(timezone.utc).isoformat()
    admin_db.update_officer(officer["id"], {"last_login_at": now_iso})

    # Record successful login in audit log
    admin_db.record_officer_audit(
        action="LOGIN",
        actor={"id": officer["id"], "name": officer["full_name"], "email": officer["email"], "role": officer["role"]},
        details={"status": "success"},
        target={"id": officer["id"], "email": officer["email"]},
        ip_address=client_ip,
    )

    token = create_officer_token(officer)
    role = officer.get("role", ROLE_OPERATIONS_ENGINEER)

    return {
        "token": token,
        "officer": {
            "id": officer["id"],
            "name": officer["full_name"],
            "email": officer["email"],
            "role": role,
            "role_display": ROLE_DISPLAY_NAMES.get(role, role.capitalize()),
            "status": officer["status"],
            "last_login_at": now_iso,
            "permissions": list(get_permissions_for_role(role)),
        },
        "expires_in_seconds": 8 * 3600,
    }


@router.post("/logout")
def logout(request: Request, current_officer: dict = Depends(get_current_officer)):
    """Logs out officer and records an audit log entry."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    admin_db.record_officer_audit(
        action="LOGOUT",
        actor=current_officer,
        details={"status": "officer_initiated_logout"},
        ip_address=client_ip,
    )
    return {"ok": True, "message": "Logged out successfully."}


@router.get("/me")
def me(current_officer: dict = Depends(get_current_officer)):
    """Returns current officer profile and capability set."""
    role = current_officer.get("role", ROLE_OPERATIONS_ENGINEER)
    return {
        "id": current_officer.get("sub"),
        "name": current_officer.get("name"),
        "email": current_officer.get("email"),
        "role": role,
        "role_display": ROLE_DISPLAY_NAMES.get(role, role.capitalize()),
        "status": current_officer.get("status", "active"),
        "permissions": list(get_permissions_for_role(role)),
        "can_access_admin_console": role == ROLE_ADMIN,
        "can_access_control_room": True,
        "can_access_prediction": True,
    }


# ============================================================================
# OFFICER & ACCESS MANAGEMENT (ADMIN ONLY)
# ============================================================================

@router.get("/officers")
def list_officers_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    role: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    admin: dict = Depends(require_admin),
):
    """List all officers with optional role, status, and text search filters."""
    result = admin_db.list_officers(limit=limit, offset=offset, role=role, status=status, search=search)
    return result


@router.post("/officers", status_code=status.HTTP_201_CREATED)
def create_officer_endpoint(
    body: OfficerCreateRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    """Create a new officer account with bcrypt hashed password. Audited."""
    clean_email = body.email.strip().lower()
    existing = admin_db.get_officer_by_email(clean_email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An officer with email '{clean_email}' already exists.",
        )

    if body.role not in ROLE_PERMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{body.role}'. Supported roles: {list(ROLE_PERMISSIONS.keys())}",
        )

    hashed_pw = hash_password(body.password)
    officer_record = {
        "full_name": body.full_name.strip(),
        "email": clean_email,
        "password_hash": hashed_pw,
        "role": body.role,
        "status": body.status,
        "created_by": admin.get("email") or admin.get("name") or "Administrator",
    }

    created = admin_db.create_officer(officer_record)

    client_ip = request.client.host if request.client else "127.0.0.1"
    admin_db.record_officer_audit(
        action="OFFICER_CREATED",
        actor=admin,
        details={"name": body.full_name, "email": clean_email, "role": body.role, "status": body.status},
        target={"id": created.get("id"), "email": clean_email},
        ip_address=client_ip,
    )

    # Exclude password hash from response
    safe_officer = {k: v for k, v in created.items() if k != "password_hash"}
    return safe_officer


@router.get("/officers/audit")
def list_officer_audits_endpoint(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None),
    admin: dict = Depends(require_admin),
):
    """Returns security audit logs (LOGIN, LOGOUT, OFFICER_CREATED, ROLE_CHANGED, etc.)."""
    return admin_db.list_officer_audits(limit=limit, offset=offset, action=action)


@router.get("/officers/{officer_id}")
def get_officer_endpoint(officer_id: str, admin: dict = Depends(require_admin)):
    officer = admin_db.get_officer_by_id(officer_id)
    if not officer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Officer not found.")
    return {k: v for k, v in officer.items() if k != "password_hash"}


@router.put("/officers/{officer_id}")
def update_officer_endpoint(
    officer_id: str,
    body: OfficerUpdateRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    """Update officer details, role, or status with lockout prevention guards."""
    officer = admin_db.get_officer_by_id(officer_id)
    if not officer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Officer not found.")

    patch: dict[str, Any] = {}
    client_ip = request.client.host if request.client else "127.0.0.1"

    if body.full_name:
        patch["full_name"] = body.full_name.strip()

    if body.email:
        clean_email = body.email.strip().lower()
        if clean_email != officer.get("email"):
            existing = admin_db.get_officer_by_email(clean_email)
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use.")
            patch["email"] = clean_email

    # Lockout guard: deactivating last active admin
    if body.status:
        if body.status not in ("active", "inactive"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status value.")
        if officer.get("role") == ROLE_ADMIN and officer.get("status") == "active" and body.status == "inactive":
            if admin_db.count_active_admins() <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot deactivate the last active Administrator account. Another active admin must exist first.",
                )
        patch["status"] = body.status

    # Lockout guard: demoting last active admin
    if body.role and body.role != officer.get("role"):
        if body.role not in ROLE_PERMISSIONS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role specified.")
        if officer.get("role") == ROLE_ADMIN and body.role != ROLE_ADMIN:
            if admin_db.count_active_admins() <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot change role of the last active Administrator. Another active admin must exist first.",
                )
        patch["role"] = body.role

    if not patch:
        return {k: v for k, v in officer.items() if k != "password_hash"}

    updated = admin_db.update_officer(officer_id, patch)
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update officer.")

    # Audit specific actions
    if "role" in patch and patch["role"] != officer.get("role"):
        admin_db.record_officer_audit(
            action="ROLE_CHANGED",
            actor=admin,
            details={"old_role": officer.get("role"), "new_role": patch["role"], "officer_name": officer.get("full_name")},
            target={"id": officer_id, "email": officer.get("email")},
            ip_address=client_ip,
        )

    if "status" in patch and patch["status"] != officer.get("status"):
        action = "OFFICER_DEACTIVATED" if patch["status"] == "inactive" else "OFFICER_ACTIVATED"
        admin_db.record_officer_audit(
            action=action,
            actor=admin,
            details={"old_status": officer.get("status"), "new_status": patch["status"], "officer_name": officer.get("full_name")},
            target={"id": officer_id, "email": officer.get("email")},
            ip_address=client_ip,
        )

    admin_db.record_officer_audit(
        action="OFFICER_UPDATED",
        actor=admin,
        details={"updated_fields": list(patch.keys())},
        target={"id": officer_id, "email": officer.get("email")},
        ip_address=client_ip,
    )

    return {k: v for k, v in updated.items() if k != "password_hash"}


@router.post("/officers/{officer_id}/reset-password")
def reset_password_endpoint(
    officer_id: str,
    body: OfficerPasswordResetRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    """Admin triggers password reset for an officer. Hashes with bcrypt and audits."""
    officer = admin_db.get_officer_by_id(officer_id)
    if not officer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Officer not found.")

    new_hash = hash_password(body.new_password)
    updated = admin_db.update_officer(officer_id, {"password_hash": new_hash})
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to reset password.")

    client_ip = request.client.host if request.client else "127.0.0.1"
    admin_db.record_officer_audit(
        action="PASSWORD_RESET",
        actor=admin,
        details={"target_officer": officer.get("email"), "reason": "Admin initiated reset"},
        target={"id": officer_id, "email": officer.get("email")},
        ip_address=client_ip,
    )

    return {"ok": True, "message": f"Password reset successfully for {officer.get('email')}."}


@router.post("/officers/{officer_id}/status")
def toggle_officer_status_endpoint(
    officer_id: str,
    body: OfficerStatusRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    """Toggle officer account status (active/inactive) with lockout guard."""
    officer = admin_db.get_officer_by_id(officer_id)
    if not officer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Officer not found.")

    if officer.get("role") == ROLE_ADMIN and officer.get("status") == "active" and body.status == "inactive":
        if admin_db.count_active_admins() <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate the last active Administrator account.",
            )

    updated = admin_db.update_officer(officer_id, {"status": body.status})
    client_ip = request.client.host if request.client else "127.0.0.1"

    action = "OFFICER_DEACTIVATED" if body.status == "inactive" else "OFFICER_ACTIVATED"
    admin_db.record_officer_audit(
        action=action,
        actor=admin,
        details={"old_status": officer.get("status"), "new_status": body.status},
        target={"id": officer_id, "email": officer.get("email")},
        ip_address=client_ip,
    )

    return {k: v for k, v in updated.items() if k != "password_hash"}


@router.get("/roles/matrix")
def get_roles_matrix_endpoint(current_officer: dict = Depends(get_current_officer)):
    """Returns RBAC roles, capability assignments, and descriptions for UI inspection."""
    return {
        "roles": [
            {
                "role": r,
                "display_name": ROLE_DISPLAY_NAMES.get(r, r.capitalize()),
                "permissions": list(perms),
                "is_current_officer_role": current_officer.get("role") == r,
            }
            for r, perms in ROLE_PERMISSIONS.items()
        ],
        "all_capabilities": sorted(list({p for perms in ROLE_PERMISSIONS.values() for p in perms})),
    }


# ============================================================================
# 1. SYSTEM HEALTH & CONFIG (ADMIN ONLY)
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
# 2. DATA MANAGEMENT (ADMIN ONLY)
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


@router.get("/data/records")
def list_operations_records(limit: int = 50, offset: int = 0, identity: dict = Depends(require_admin)):
    result = admin_db.fetch_table("operations_history", limit=limit, offset=offset, order_by="scheduled_time")
    if result["source"] == "unavailable":
        return admin_db.fetch_operations_history_csv_fallback(limit=limit, offset=offset)
    return result


@router.post("/data/records")
def create_operations_record(record: OperationsRecord, identity: dict = Depends(require_admin)):
    data = record.model_dump()
    if not data.get("record_id"):
        data["record_id"] = f"REC-{int(time.time() * 1000)}"
    result = admin_db.insert_row("operations_history", data)
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Insert failed"))
    return result["row"]


@router.put("/data/records/{record_id}")
def update_operations_record(record_id: str, patch: dict = Body(...), identity: dict = Depends(require_admin)):
    result = admin_db.update_row("operations_history", "record_id", record_id, patch)
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Update failed"))
    return result["row"]


@router.delete("/data/records/{record_id}")
def delete_operations_record(record_id: str, identity: dict = Depends(require_admin)):
    result = admin_db.delete_row("operations_history", "record_id", record_id)
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Delete failed"))
    return {"deleted": record_id}


@router.post("/data/upload-csv")
async def upload_csv(file: UploadFile = File(...), identity: dict = Depends(require_admin)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files accepted")
    content = await file.read()
    dest = ROOT_DIR / "data" / f"uploaded_{int(time.time())}_{file.filename}"
    dest.write_bytes(content)
    return {"filename": dest.name, "size_bytes": len(content), "saved_to": str(dest)}


# ============================================================================
# 3. INCIDENT REPORTS REVIEW QUEUE (ADMIN ONLY)
# ============================================================================

class IncidentReviewPatch(BaseModel):
    review_status: str = Field(pattern="^(pending|approved|rejected|corrected)$")
    corrected_type: Optional[str] = None
    note: Optional[str] = None


@router.get("/incidents/queue")
def list_incident_queue(status: Optional[str] = None, limit: int = 50, offset: int = 0, identity: dict = Depends(require_admin)):
    filters = {"review_status": status} if status else None
    result = admin_db.fetch_table("incident_reports", limit=limit, offset=offset, order_by="received_at", filters=filters)
    return result


@router.patch("/incidents/queue/{incident_id}")
def review_incident(incident_id: str, patch: IncidentReviewPatch, identity: dict = Depends(require_admin)):
    update_data = {
        "review_status": patch.review_status,
        "reviewed_by": identity.get("email") or identity.get("name") or "admin",
        "reviewed_at": time.time(),
    }
    if patch.corrected_type:
        update_data["classified_type"] = patch.corrected_type
    result = admin_db.update_row("incident_reports", "incident_id", incident_id, update_data)
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Review update failed"))
    return result["row"]


# ============================================================================
# 4. MODEL OPERATIONS (ADMIN ONLY)
# ============================================================================

@router.get("/model/metrics")
def model_metrics(identity: dict = Depends(require_admin)):
    eval_dir = ROOT_DIR / "evaluation"
    delay_path = eval_dir / "ml" / "delay_model_metrics.json"
    nlp_path = eval_dir / "nlp" / "classification_metrics.json"
    rag_path = eval_dir / "rag" / "retrieval_metrics.json"

    import json
    def read_json(p: Path) -> dict:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    return {
        "delay_model": read_json(delay_path),
        "nlp_classification": read_json(nlp_path),
        "rag_retrieval": read_json(rag_path),
    }


@router.post("/model/retrain")
def retrain_model(identity: dict = Depends(require_admin)):
    train_script = ML_DIR / "train.py"
    if not train_script.exists():
        raise HTTPException(status_code=404, detail="train.py not found")

    import json
    proc = subprocess.run(
        [sys.executable, str(train_script)],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )

    metrics_path = ROOT_DIR / "evaluation" / "ml" / "delay_model_metrics.json"
    metrics = None
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    run_record = {
        "triggered_by": identity.get("email") or identity.get("name") or "admin",
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
        "triggered_by": identity.get("email") or identity.get("name") or "admin",
        "action": "rollback",
        "restored_from": filename,
    })
    return {"ok": True, "restored_from": filename}


# ============================================================================
# 5. HUB & EVENT CONTROL (ADMIN ONLY)
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
    event = {
        "event_type": "delay_alert",
        "route": "Colombo Fort - Kandy",
        "train_id": "TEST-ADMIN",
        "predicted_delay_minutes": 12.0,
        "triggered_by": identity.get("email") or identity.get("name") or "admin",
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
# 6. GENERAL AUDIT TRAILS (ADMIN ONLY)
# ============================================================================

@router.get("/audit/events")
def audit_events(limit: int = 100, offset: int = 0, identity: dict = Depends(require_admin)):
    result = admin_db.fetch_table("audit_events", limit=limit, offset=offset, order_by="created_at")
    if result["source"] == "unavailable":
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
