"""
Passenger authentication for the M1 Passenger Assistant.

Mirrors the pattern already proven in M2 (`M2-operations-agent/admin/admin_auth.py`):
bcrypt password hashes, short-lived JWTs signed with the shared JWT_SECRET_KEY,
and FastAPI dependencies that guard individual routes.

The one rule that makes chat ownership safe:

    user_id is NEVER read from a request body, query string or custom header.
    It comes only from the `sub` claim of a token whose HMAC signature this
    module has verified.

A client cannot forge `sub` without JWT_SECRET_KEY, which never leaves the
server, so "just send someone else's user_id" is not an available attack.

Two dependencies are exported because M1 has two kinds of caller:

  require_passenger   - the M1 chat app. No valid token -> 401.
  optional_passenger  - POST /chat, which is also called anonymously by the
                        public homepage, the passenger portal, M2's hand-off
                        and the integration scripts. No token -> None, and the
                        conversation is stored with user_id = NULL so it stays
                        out of every signed-in passenger's sidebar.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Header, HTTPException, status

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
TOKEN_TTL_SECONDS = int(os.getenv("M1_TOKEN_TTL_SECONDS", str(12 * 60 * 60)))

# Kill switch. Default on; set M1_REQUIRE_AUTH=false in .env to fall back to the
# old open behaviour without a redeploy (e.g. if a live demo breaks). It only
# relaxes the guards - it never changes how a *valid* token is verified.
REQUIRE_AUTH = os.getenv("M1_REQUIRE_AUTH", "true").strip().lower() not in ("false", "0", "no")

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sign in to view your chats.",
    headers={"WWW-Authenticate": "Bearer"},
)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(plain_password: str) -> str:
    """Hash a plaintext password with bcrypt and a unique salt."""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its bcrypt hash, in constant time."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), (hashed_password or "").encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed/empty hash in the row - treat as a failed login, never a 500.
        return False


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
def create_passenger_token(passenger: dict, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    """Sign a JWT whose `sub` is the passenger's user_id."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(passenger["user_id"]),
        "username": passenger.get("username", ""),
        "name": passenger.get("full_name", ""),
        "role": "passenger",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_passenger_token(token: str) -> dict:
    """Return the verified claims, or raise 401. Signature and exp are both checked."""
    try:
        claims = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        # Bad signature, wrong algorithm, malformed token - all the same to the
        # caller. The reason is deliberately not echoed back.
        raise _UNAUTHORIZED
    if not claims.get("sub"):
        raise _UNAUTHORIZED
    return claims


def _token_from_header(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------
def require_passenger(authorization: str | None = Header(default=None)) -> dict:
    """Guard for the passenger's own chat data. No valid token -> 401."""
    token = _token_from_header(authorization)
    if token is None:
        if not REQUIRE_AUTH:
            return {"sub": None, "name": "", "username": ""}
        raise _UNAUTHORIZED
    return verify_passenger_token(token)


def optional_passenger(authorization: str | None = Header(default=None)) -> dict | None:
    """Identify the caller when they are signed in, without requiring it.

    A malformed or expired token still raises 401 rather than being silently
    downgraded to anonymous - a passenger whose session quietly expired should
    be told to sign in again, not have their chat saved to the NULL bucket
    where they can never see it.
    """
    token = _token_from_header(authorization)
    if token is None:
        return None
    return verify_passenger_token(token)


def current_user_id(claims: dict | None) -> str | None:
    """The one approved way to turn a request into a user_id."""
    return (claims or {}).get("sub") or None
