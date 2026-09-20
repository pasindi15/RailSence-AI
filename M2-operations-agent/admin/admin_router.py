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
        GET  /health/status              -> source liveness, drives the offline banner
        GET  /model/metrics-history      -> current metrics + real retrain run log
        GET  /model/feature-importances  -> ml/feature_importances.json from the last run
        POST /model/retrain              -> runs ml/train_delay_model.py against live data
        GET  /model/versions             -> real timestamped backups with their metrics
        POST /model/rollback/{filename}  -> restore a prior .pkl
        GET  /audit/events               -> inter-agent audit trail (read-only, filtered)
        GET  /audit/summary              -> intent/agent distribution over that trail

Removed in the rubric-focused consolidation (see README section 4):
    /data/*            Data Management screen retired; the CSV import/export
                       path stays runnable from the CLI via
                       data/import_to_supabase.py and the ML training pipeline.
    /hub/status,
    /hub/events,
    /hub/test-alert,
    /hub/threshold     Hub & Upstash connectivity-probe screen retired. The
                       alert-publishing code in hub_client.py is untouched and
                       the >= 5.0 minute delay_alert broadcast still fires.
    /health/data-sources,
    /health/config     System Health & Config screen retired; /health/status
                       remains because the offline-mode banner reads it.
    /incidents/queue   Superseded by the consolidated Incident Management
                       screen backed by GET/PATCH/DELETE /incidents in main.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import logging
import subprocess
import sys
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request, status
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

logger = logging.getLogger("railsense.admin_router")
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


# ============================================================================
# 4. MODEL OPERATIONS — RETRAIN & ROLLBACK (ADMIN ONLY)
# ============================================================================

TRAIN_SCRIPT = ML_DIR / "train_delay_model.py"
IMPORTANCES_PATH = ML_DIR / "feature_importances.json"
ML_METRICS_PATH = ROOT_DIR / "evaluation" / "ml" / "delay_model_metrics.json"


def _read_json(path: Path) -> dict:
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@router.get("/model/metrics")
def model_metrics(identity: dict = Depends(require_admin)):
    """All three committed evaluation artifacts, as produced by the eval scripts."""
    eval_dir = ROOT_DIR / "evaluation"
    return {
        "delay_model": _read_json(eval_dir / "ml" / "delay_model_metrics.json"),
        "nlp_classification": _read_json(eval_dir / "nlp" / "classification_metrics.json"),
        "rag_retrieval": _read_json(eval_dir / "rag" / "retrieval_metrics.json"),
    }


@router.get("/model/metrics-history")
def model_metrics_history(identity: dict = Depends(require_admin)):
    """Current held-out metrics plus the real retrain/rollback run log."""
    runs = admin_db.get_training_runs()
    return {
        "current_metrics": _read_json(ML_METRICS_PATH) or None,
        "runs": runs,
        "run_count": len(runs),
        "model_present": (ML_DIR / "delay_model.pkl").exists(),
    }


@router.get("/model/feature-importances")
def model_feature_importances(identity: dict = Depends(require_admin)):
    """Feature importances written by the most recent training run.

    Read from disk on every request rather than from a cached copy, so the ML
    screen reflects a retrain without a service restart.
    """
    import json

    if not IMPORTANCES_PATH.exists():
        return {"available": False, "features": [], "generated_at": None}
    try:
        features = json.loads(IMPORTANCES_PATH.read_text(encoding="utf-8"))
    except ValueError:
        return {"available": False, "features": [], "generated_at": None}
    return {
        "available": True,
        "features": features,
        "generated_at": IMPORTANCES_PATH.stat().st_mtime,
    }


@router.post("/model/retrain")
def retrain_model(identity: dict = Depends(require_admin)):
    """Retrain the delay model against the live operations corpus.

    Runs ml/train_delay_model.py, which loads Supabase operations_history when
    reachable and the CSV otherwise, archives the outgoing delay_model.pkl to
    ml/model_versions/ with a metrics sidecar, then writes the new model,
    feature_importances.json and delay_model_metrics.json. The in-process
    predictor is reloaded afterwards so /predict-delay serves the new model
    without a restart.
    """
    if not TRAIN_SCRIPT.exists():
        raise HTTPException(status_code=404, detail="ml/train_delay_model.py not found")

    versions_before = {v["filename"] for v in admin_db.list_model_versions()}

    proc = subprocess.run(
        [sys.executable, str(TRAIN_SCRIPT)],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        timeout=600,
    )

    metrics = _read_json(ML_METRICS_PATH) or None
    versions_after = admin_db.list_model_versions()
    new_backups = [v["filename"] for v in versions_after if v["filename"] not in versions_before]

    reloaded = False
    if proc.returncode == 0:
        try:
            from ml import predict as delay_model

            reloaded = delay_model.reload_model()
        except Exception as exc:  # pragma: no cover - defensive
            proc_note = f"model reload failed: {exc}"
            logger.warning(proc_note)

    run_record = {
        "triggered_by": identity.get("email") or identity.get("name") or "admin",
        "action": "retrain",
        "returncode": proc.returncode,
        "metrics": metrics,
        "backup_created": new_backups[0] if new_backups else None,
        "model_reloaded": reloaded,
        "data_source": (metrics or {}).get("data_source"),
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
    }
    admin_db.log_training_run(run_record)

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail={"message": "Training script failed", **run_record})
    return run_record


@router.get("/model/versions")
def model_versions(identity: dict = Depends(require_admin)):
    """Real backup files on disk, with the metrics each one scored."""
    versions = admin_db.list_model_versions()
    current = ML_DIR / "delay_model.pkl"
    return {
        "versions": versions,
        "count": len(versions),
        "current": {
            "filename": current.name,
            "created_at": current.stat().st_mtime if current.exists() else None,
            "metrics": _read_json(ML_METRICS_PATH) or None,
        },
    }


@router.post("/model/rollback/{filename}")
def rollback_model(filename: str, identity: dict = Depends(require_admin)):
    """Restore a previous .pkl, archiving the current one first."""
    import shutil

    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid version filename")

    versions_dir = ML_DIR / "model_versions"
    src = versions_dir / filename
    if not src.exists() or not filename.startswith("delay_model_") or src.suffix != ".pkl":
        raise HTTPException(status_code=404, detail="Model version not found")

    current_pkl = ML_DIR / "delay_model.pkl"
    archived_as = None
    if current_pkl.exists():
        archived_as = f"delay_model_{int(time.time())}_pre_rollback.pkl"
        shutil.copy2(current_pkl, versions_dir / archived_as)
        if ML_METRICS_PATH.exists():
            shutil.copy2(ML_METRICS_PATH, (versions_dir / archived_as).with_suffix(".json"))

    shutil.copy2(src, current_pkl)

    # Restore that version's metrics alongside the model, so the console keeps
    # reporting the numbers that belong to the model actually being served.
    sidecar = src.with_suffix(".json")
    restored_metrics = None
    if sidecar.exists():
        shutil.copy2(sidecar, ML_METRICS_PATH)
        restored_metrics = _read_json(ML_METRICS_PATH) or None

    reloaded = False
    try:
        from ml import predict as delay_model

        reloaded = delay_model.reload_model()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Model reload after rollback failed: %s", exc)

    admin_db.log_training_run({
        "triggered_by": identity.get("email") or identity.get("name") or "admin",
        "action": "rollback",
        "restored_from": filename,
        "archived_as": archived_as,
        "metrics": restored_metrics,
        "model_reloaded": reloaded,
    })
    return {
        "ok": True,
        "restored_from": filename,
        "archived_as": archived_as,
        "metrics": restored_metrics,
        "model_reloaded": reloaded,
    }


# ============================================================================
# 5. AUDIT & AGENT COMMUNICATION LOG (ADMIN ONLY — STRICTLY READ-ONLY)
#
# Tamper-evident by construction: this section exposes reads only. There is
# deliberately no update or delete route for audit_events, so a row that was
# written can be inspected and filtered but never edited from the console.
# ============================================================================

@router.get("/audit/events")
def audit_events(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    agent: Optional[str] = Query(None, description="Match sender_agent or receiver_agent"),
    intent: Optional[str] = Query(None, description="Match the message intent / action"),
    date_from: Optional[str] = Query(None, description="ISO date, inclusive lower bound"),
    date_to: Optional[str] = Query(None, description="ISO date, inclusive upper bound"),
    identity: dict = Depends(require_admin),
):
    """Filtered, paginated read of the real inter-agent audit trail.

    Filtering is pushed down to Postgres when Supabase is reachable, so a large
    audit_events table is never pulled into the process to be filtered in
    Python. The data/audit_log.jsonl fallback applies the same predicates
    locally and reports `offline: true` so the UI can say so plainly.
    """
    result = admin_db.list_agent_audit_events(
        limit=limit,
        offset=offset,
        agent=agent,
        intent=intent,
        date_from=date_from,
        date_to=date_to,
    )
    return {
        "rows": result["rows"],
        "count": result["count"],
        "limit": limit,
        "offset": offset,
        "source": result["source"],
        "offline": result["offline"],
        "filters": {"agent": agent, "intent": intent, "date_from": date_from, "date_to": date_to},
    }


@router.get("/audit/summary")
def audit_summary(identity: dict = Depends(require_admin)):
    """Intent and sender distribution across the audit trail."""
    return admin_db.summarise_agent_audit_events(limit=1000)
