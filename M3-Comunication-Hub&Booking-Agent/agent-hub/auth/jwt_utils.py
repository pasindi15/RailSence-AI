"""
agent-hub/auth/jwt_utils.py
---------------------------
RailSense AI — Central Agent Communication Hub JWT Utilities
Phase 2: JWT verification for inter-agent communication.

Architectural rules:
- Verifies bearer tokens using PyJWT.
- Reads JWT_SECRET_KEY and JWT_ALGORITHM from environment / config.
- Checks signature, expiry (exp), and sender claim matching (sub).
- Returns HTTP 401 Unauthorized for invalid, malformed, or expired tokens.
- Never logs sensitive tokens or secret keys.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import jwt
from dotenv import load_dotenv
from fastapi import HTTPException, status

load_dotenv()

# ---------------------------------------------------------------------------
# Path resolution to load config safely
# ---------------------------------------------------------------------------
_CURRENT_DIR = os.path.dirname(__file__)
_AGENT_HUB_DIR = os.path.abspath(os.path.join(_CURRENT_DIR, ".."))
if _AGENT_HUB_DIR not in sys.path:
    sys.path.insert(0, _AGENT_HUB_DIR)

try:
    import config
    _DEFAULT_SECRET = getattr(config, "JWT_SECRET_KEY", "") or "change-me"
    _DEFAULT_ALGO = getattr(config, "JWT_ALGORITHM", "HS256")
except ImportError:
    _DEFAULT_SECRET = os.getenv("JWT_SECRET_KEY", "change-me")
    _DEFAULT_ALGO = os.getenv("JWT_ALGORITHM", "HS256")


def get_jwt_secret() -> str:
    """
    Retrieve JWT secret key from environment or configuration.
    Falls back to safe development placeholder if unset.
    """
    return os.getenv("JWT_SECRET_KEY") or _DEFAULT_SECRET


def get_jwt_algorithm() -> str:
    """Retrieve JWT signing algorithm from environment or configuration."""
    return os.getenv("JWT_ALGORITHM") or _DEFAULT_ALGO


def verify_agent_token(
    token: str,
    expected_sender: str | None = None,
) -> dict[str, Any]:
    """
    Verify and decode an inter-agent JWT authentication token.

    Parameters
    ----------
    token : str
        The raw JWT string or 'Bearer '-prefixed token string.
    expected_sender : str | None, optional
        The logical sender_agent from the message envelope. If provided,
        verifies that the token's subject claim matches the sender agent.

    Returns
    -------
    dict[str, Any]
        The decoded claims payload if valid.

    Raises
    ------
    HTTPException (401)
        If the token is empty, malformed, expired, has an invalid signature,
        or if the subject claim does not match expected_sender.
    """
    if not token or not isinstance(token, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
        )

    # Strip optional 'Bearer ' prefix (case-insensitive)
    cleaned_token = token.strip()
    if cleaned_token.lower().startswith("bearer "):
        cleaned_token = cleaned_token[7:].strip()

    if not cleaned_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
        )

    secret = get_jwt_secret()
    algorithm = get_jwt_algorithm()

    try:
        payload = jwt.decode(
            cleaned_token,
            secret,
            algorithms=[algorithm],
            options={"require": ["exp"], "verify_exp": True},
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        # Do not expose low-level cryptographic details
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
        )

    # Optional sender claim check: match 'sub' or 'agent' against expected_sender
    if expected_sender:
        token_sub = payload.get("sub") or payload.get("agent")
        if not token_sub or token_sub != expected_sender:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token subject does not match sender agent",
            )

    return payload
