"""
auth/jwt_handler.py — JWT issue / verify / revoke (Phase 2)

Phase 2:
  - issue_token()   signs a real HS256 JWT with sub, iat, exp claims.
  - verify_token()  verifies signature, expiry, and revocation list.
                    Raises jose.JWTError on any failure (caller → 401).
  - revoke_token()  adds to in-memory blacklist.
  - decode_token()  decodes claims without raising — returns None on failure.

Environment variables consumed:
  JWT_SECRET          — HS256 signing key (required; warn + fallback if unset)
  JWT_ALGORITHM       — algorithm string, default "HS256"
  JWT_EXPIRY_MINUTES  — token lifetime in minutes, default 60
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

_SECRET: str = os.getenv("JWT_SECRET", "")
if not _SECRET:
    _SECRET = "railsense-dev-secret-change-in-production"
    logger.warning(
        "JWT_SECRET env var is not set. "
        "Using insecure development default — set a real secret before deploying."
    )

_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")

_EXPIRY_MINUTES: int = int(os.getenv("JWT_EXPIRY_MINUTES", "60"))

# ---------------------------------------------------------------------------
# In-memory revocation set
# Cleared on restart. A production upgrade moves this to Redis / DB.
# ---------------------------------------------------------------------------

_revoked: set[str] = set()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def issue_token(agent_id: str, secret: str) -> str:  # noqa: ARG001
    """
    Sign and return an HS256 JWT for *agent_id*.

    The *secret* parameter is not validated here — credential checking is the
    caller's responsibility (main.py /auth/login calls hashing.verify_secret
    before calling issue_token).

    Args:
        agent_id: The agent requesting authentication (stored as JWT 'sub').
        secret:   Caller-supplied secret (unused at this layer — validated upstream).

    Returns:
        A signed JWT string the agent should embed in every HubMessage.
    """
    now = datetime.now(tz=timezone.utc)
    claims: Dict[str, Any] = {
        "sub": agent_id,
        "iat": now,
        "exp": now + timedelta(minutes=_EXPIRY_MINUTES),
        "type": "agent_token",
    }
    token: str = jwt.encode(claims, _SECRET, algorithm=_ALGORITHM)
    logger.info("Issued JWT for agent '%s' (expires in %d min)", agent_id, _EXPIRY_MINUTES)
    return token


def verify_token(token: str) -> bool:
    """
    Return True if *token* is a valid, unexpired, non-revoked HS256 JWT.

    Raises:
        jose.JWTError: If the signature is invalid, the token is expired,
                       or the token has been revoked.  The caller should
                       convert this to an HTTP 401 response.

    Args:
        token: The token extracted from an incoming HubMessage.auth_token.

    Returns:
        True — always, if no exception is raised.
    """
    if token in _revoked:
        raise JWTError("Token has been revoked")

    # This will raise JWTError for invalid signature or expiry
    jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
    return True


def revoke_token(token: str) -> None:
    """
    Add *token* to the revocation set so verify_token() rejects it.

    In-memory only — cleared on restart.  A production upgrade moves this
    to a Redis SET or a database table with a TTL matching JWT_EXPIRY_MINUTES.

    Args:
        token: The token to invalidate immediately.
    """
    _revoked.add(token)
    logger.info("Token revoked (total revoked: %d)", len(_revoked))


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode *token* and return its claims without raising on failure.

    Used by endpoints that want to read the agent_id from a token without
    triggering a 401 themselves.

    Args:
        token: JWT string to decode.

    Returns:
        Decoded claims dict, or None if the token is invalid / expired.
    """
    try:
        return jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
    except JWTError:
        return None
