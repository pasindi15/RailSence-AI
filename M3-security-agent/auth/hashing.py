"""
auth/hashing.py — bcrypt password hashing for agent credentials (Phase 2)

Uses passlib's bcrypt implementation for constant-time secret comparison.
Agent shared secrets are stored as bcrypt hashes in the in-memory
_agent_credentials store in main.py — never as plaintext.

Usage:
  from auth.hashing import hash_secret, verify_secret

  hashed = hash_secret("my-agent-secret")
  is_valid = verify_secret("my-agent-secret", hashed)   # True
  is_valid = verify_secret("wrong-secret",   hashed)   # False
"""

from __future__ import annotations

import logging

from passlib.context import CryptContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Passlib context — bcrypt with automatic rehashing when work factor changes
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def hash_secret(plain: str) -> str:
    """
    Hash *plain* with bcrypt and return the hash string.

    Args:
        plain: The plaintext agent secret to hash.

    Returns:
        A bcrypt hash string (e.g. "$2b$12$...").
    """
    return _pwd_context.hash(plain)


def verify_secret(plain: str, hashed: str) -> bool:
    """
    Verify *plain* against *hashed* using constant-time bcrypt comparison.

    Args:
        plain:  The plaintext secret supplied by the agent at login.
        hashed: The stored bcrypt hash to compare against.

    Returns:
        True if the secret matches, False otherwise.
    """
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception:  # noqa: BLE001
        # passlib raises if the hash string is malformed — treat as failure
        logger.warning("verify_secret() encountered a malformed hash — returning False.")
        return False
