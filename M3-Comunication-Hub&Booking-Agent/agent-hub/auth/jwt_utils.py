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


def create_agent_token(
    sub: str,
    role: str = "service",
    user_id: str | None = None,
    issuer: str = "railsense-hub",
    audience: str = "railsense-services",
    expires_in_seconds: int = 3600,
    secret: str | None = None,
    algorithm: str | None = None,
) -> str:
    """Generate a signed JWT with full claims structure."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "role": role,
        "iss": issuer,
        "aud": audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
    }
    if user_id:
        payload["user_id"] = user_id
    sec = secret or get_jwt_secret()
    alg = algorithm or get_jwt_algorithm()
    return jwt.encode(payload, sec, algorithm=alg)


def mint_delegation_token(
    original_sender: str,
    receiver_agent: str,
    user_id: str | None = None,
    role: str = "service",
    intent: str | None = None,
) -> str:
    """
    Mint a trusted delegation token from the Communication Hub to the destination service.
    Guarantees receiving service that Hub verified the original caller, preserving identity.
    """
    return create_agent_token(
        sub=original_sender,
        role=role,
        user_id=user_id,
        issuer="railsense-hub",
        audience=receiver_agent,
        expires_in_seconds=300,
    )


def verify_agent_token(
    token: str,
    expected_sender: str | None = None,
    expected_audience: str | None = None,
    expected_issuer: str | None = None,
    required_role: str | None = None,
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
    expected_audience : str | None, optional
        If specified or present, verifies audience.
    expected_issuer : str | None, optional
        If specified or present, verifies issuer.
    required_role : str | None, optional
        If specified, verifies role claim matches (e.g. 'admin').

    Returns
    -------
    dict[str, Any]
        The decoded claims payload if valid.

    Raises
    ------
    HTTPException (401 / 403)
        If token is invalid, expired, wrong issuer, wrong audience, or missing required role.
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

    # Decode options: require exp
    decode_options = {
        "require": ["exp"],
        "verify_exp": True,
        "verify_nbf": True,
    }

    try:
        payload = jwt.decode(
            cleaned_token,
            secret,
            algorithms=[algorithm],
            options={"require": ["exp"], "verify_exp": True},
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
        )

    # Check Issuer (iss) if present in token
    token_iss = payload.get("iss")
    if expected_issuer and token_iss and token_iss != expected_issuer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token issuer '{token_iss}' does not match expected '{expected_issuer}'",
        )

    # Check Audience (aud) if present in token
    token_aud = payload.get("aud")
    if expected_audience and token_aud:
        if isinstance(token_aud, list) and expected_audience not in token_aud and "railsense-services" not in token_aud:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token audience '{token_aud}' does not match expected '{expected_audience}'",
            )
        elif isinstance(token_aud, str) and token_aud != expected_audience and token_aud != "railsense-services":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token audience '{token_aud}' does not match expected '{expected_audience}'",
            )

    # Sender claim check: match 'sub' or 'agent' against expected_sender
    if expected_sender:
        token_sub = payload.get("sub") or payload.get("agent")
        if not token_sub or token_sub != expected_sender:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token subject does not match sender agent",
            )

    # Role check if required
    if required_role:
        token_role = payload.get("role")
        if token_role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action requires role '{required_role}', but token has role '{token_role}'",
            )

    return payload

