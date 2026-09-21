"""RailSense AI — M2 Operations RBAC Authentication & Authorization Engine.

Enterprise Role-Based Access Control (RBAC):
- Password hashing & verification via bcrypt.
- Signed, expiring JWT access tokens (PyJWT).
- Fine-grained permission & capability matrix.
- FastAPI dependencies for endpoint protection (require_role, require_permission).
- Backward-compatible helper functions for existing routes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import secrets
from typing import Callable, Optional

import bcrypt
import jwt
from fastapi import Header, HTTPException, status

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or os.getenv("ADMIN_TOKEN_SECRET") or secrets.token_hex(32)
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
TOKEN_TTL_SECONDS = int(os.getenv("ADMIN_TOKEN_TTL_SECONDS", str(8 * 3600)))

# ---------------------------------------------------------------------------
# Roles & Extensible Capabilities Matrix
# ---------------------------------------------------------------------------
ROLE_ADMIN = "admin"
ROLE_OPERATIONS_ENGINEER = "operations_engineer"

# Future extensible roles
ROLE_OPERATIONS_MANAGER = "operations_manager"
ROLE_DISPATCHER = "dispatcher"
ROLE_MAINTENANCE_OFFICER = "maintenance_officer"
ROLE_SECURITY_OFFICER = "security_officer"
ROLE_ANALYST = "analyst"
ROLE_VIEWER = "viewer"

ROLE_DISPLAY_NAMES = {
    ROLE_ADMIN: "Administrator",
    ROLE_OPERATIONS_ENGINEER: "Operations Engineer",
    ROLE_OPERATIONS_MANAGER: "Operations Manager",
    ROLE_DISPATCHER: "Train Dispatcher",
    ROLE_MAINTENANCE_OFFICER: "Maintenance Officer",
    ROLE_SECURITY_OFFICER: "Security Officer",
    ROLE_ANALYST: "Operations Analyst",
    ROLE_VIEWER: "Observer / Viewer",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    ROLE_ADMIN: {
        "m2.control_room.view",
        "m2.control_room.action",
        "m2.prediction.view",
        "m2.prediction.run",
        "m2.admin_console.view",
        "m2.officers.view",
        "m2.officers.create",
        "m2.officers.edit",
        "m2.officers.deactivate",
        "m2.officers.role_change",
        "m2.officers.password_reset",
        "m2.system.config",
        "m2.audit.view",
        "m2.model.manage",
        "m2.data.manage",
        # Approve / reject incidents; only verified incidents reach the
        # public incident map, so this stays with administrators.
        "m2.incidents.review",
        "m2.assistant.use",
    },
    ROLE_OPERATIONS_ENGINEER: {
        "m2.control_room.view",
        "m2.control_room.action",
        "m2.prediction.view",
        "m2.prediction.run",
        # Operations Assistant: dashboard, routes, predictions, incident queue.
        "m2.assistant.use",
    },
    ROLE_OPERATIONS_MANAGER: {
        "m2.control_room.view",
        "m2.control_room.action",
        "m2.prediction.view",
        "m2.prediction.run",
        "m2.officers.view",
        "m2.audit.view",
        "m2.data.manage",
    },
    ROLE_DISPATCHER: {
        "m2.control_room.view",
        "m2.control_room.action",
        "m2.prediction.view",
    },
    ROLE_ANALYST: {
        "m2.control_room.view",
        "m2.prediction.view",
        "m2.prediction.run",
        "m2.audit.view",
    },
    ROLE_VIEWER: {
        "m2.control_room.view",
        "m2.prediction.view",
    },
}


def get_permissions_for_role(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(role: str, permission: str) -> bool:
    perms = get_permissions_for_role(role)
    return permission in perms or "*" in perms


# ---------------------------------------------------------------------------
# Password Hashing & Verification (bcrypt)
# ---------------------------------------------------------------------------
def hash_password(plain_password: str) -> str:
    """Hash a plaintext password with bcrypt and unique salt."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its bcrypt hash in constant time."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT Token Generation & Verification
# ---------------------------------------------------------------------------
def create_officer_token(officer: dict, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    """Generate a signed PyJWT token with claims for the officer."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=ttl_seconds)
    role = officer.get("role", ROLE_OPERATIONS_ENGINEER)
    permissions = list(get_permissions_for_role(role))

    payload = {
        "sub": str(officer.get("id", "")),
        "email": officer.get("email", ""),
        "name": officer.get("full_name") or officer.get("name", ""),
        "role": role,
        "permissions": permissions,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token


def verify_officer_token(token: str) -> dict:
    """Validate token signature and expiration. Returns payload dict or raises 401."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Backward compatibility for placeholder calls
def create_admin_token(username: str) -> str:
    return create_officer_token({
        "id": "admin-system",
        "email": f"{username}@railsense.lk" if "@" not in username else username,
        "full_name": username.capitalize(),
        "role": ROLE_ADMIN,
    })


def verify_admin_token(token: str) -> dict:
    return verify_officer_token(token)


def check_login(username_or_email: str, password: str) -> bool:
    from . import admin_db
    officer = admin_db.get_officer_by_email(username_or_email)
    if not officer:
        return False
    if officer.get("status") != "active":
        return False
    return verify_password(password, officer.get("password_hash", ""))


# ---------------------------------------------------------------------------
# FastAPI Authorization Dependencies
# ---------------------------------------------------------------------------
def get_current_officer(authorization: str = Header(default="")) -> dict:
    """Extract and verify the current logged-in officer from the Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    payload = verify_officer_token(token)

    # Optional: Verify user is still active in database
    from . import admin_db
    officer_id = payload.get("sub")
    if officer_id:
        db_officer = admin_db.get_officer_by_id(officer_id)
        if db_officer:
            if db_officer.get("status") == "inactive":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account inactive. Please contact an administrator.",
                )
            # Use most up-to-date role from database
            payload["role"] = db_officer.get("role", payload.get("role"))
            payload["name"] = db_officer.get("full_name", payload.get("name"))
            payload["status"] = db_officer.get("status", "active")

    return payload


def require_authenticated_officer(officer: dict = Header(default="")) -> dict:
    """Dependency: Any authenticated active officer."""
    return get_current_officer(officer)


def require_role(*allowed_roles: str) -> Callable:
    """Dependency factory: Restricts route to specified roles."""
    def _dependency(officer: dict = Header(default="")) -> dict:
        current = get_current_officer(officer)
        role = current.get("role", "")
        if role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access restricted. Your account does not have permission to access this feature.",
            )
        return current
    return _dependency


def require_permission(permission: str) -> Callable:
    """Dependency factory: Restricts route to officers possessing a specific capability."""
    # Reads the standard Authorization header (a parameter named `officer`
    # would make FastAPI look for an "officer" header, which no client sends).
    def _dependency(authorization: str = Header(default="")) -> dict:
        current = get_current_officer(authorization)
        role = current.get("role", "")
        if not has_permission(role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted. Required capability '{permission}' is missing.",
            )
        return current
    return _dependency


def require_admin(authorization: str = Header(default="")) -> dict:
    """FastAPI dependency for backward compatibility — strictly requires admin role."""
    officer = get_current_officer(authorization)
    if officer.get("role") != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted. Administrator privileges required.",
        )
    return officer
