"""
M2 Admin Dashboard — placeholder admin authentication.

This is intentionally self-contained (stdlib only, no new pip dependency)
so the admin dashboard is usable immediately. It issues a signed, expiring
token on login and verifies it on every admin API call.

IMPORTANT: this is a stand-in. Per the project's architecture, the Security
Agent (Member C) owns the Hub's real auth layer. Before final submission,
swap `create_admin_token` / `verify_admin_token` for a call into the real
JWT system so there's one source of truth for auth across the project.

Env vars:
    ADMIN_USERNAME        default: "admin"
    ADMIN_PASSWORD        default: "operations2026"  (CHANGE THIS)
    ADMIN_TOKEN_SECRET     default: randomly generated per-process if unset
    ADMIN_TOKEN_TTL_SECONDS  default: 8 hours
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Header, HTTPException

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "operations2026")
_SECRET = os.getenv("ADMIN_TOKEN_SECRET") or secrets.token_hex(32)
TOKEN_TTL_SECONDS = int(os.getenv("ADMIN_TOKEN_TTL_SECONDS", str(8 * 3600)))


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_admin_token(username: str) -> str:
    payload = {"sub": username, "exp": time.time() + TOKEN_TTL_SECONDS}
    payload_bytes = json.dumps(payload).encode()
    payload_b64 = _b64url_encode(payload_bytes)
    signature = hmac.new(_SECRET.encode() if isinstance(_SECRET, str) else _SECRET,
                          payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)
    return f"{payload_b64}.{sig_b64}"


def verify_admin_token(token: str) -> dict:
    try:
        payload_b64, sig_b64 = token.split(".")
        expected_sig = hmac.new(_SECRET.encode() if isinstance(_SECRET, str) else _SECRET,
                                 payload_b64.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_encode(expected_sig), sig_b64):
            raise ValueError("bad signature")
        payload = json.loads(_b64url_decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            raise ValueError("expired")
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired admin token")


def check_login(username: str, password: str) -> bool:
    return hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(password, ADMIN_PASSWORD)


def require_admin(authorization: str = Header(default="")) -> dict:
    """FastAPI dependency — use as: Depends(require_admin)"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing admin token")
    token = authorization.removeprefix("Bearer ").strip()
    return verify_admin_token(token)
