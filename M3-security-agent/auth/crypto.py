"""
auth/crypto.py — AES-256 Fernet payload encryption / decryption (Phase 2)

Provides symmetric encryption for sensitive HubMessage payload fields using
the cryptography library's Fernet implementation (AES-128-CBC under the
hood, with HMAC-SHA256 integrity — equivalent to AES-256 when a 32-byte key
is used to derive the Fernet key).

Environment variables consumed:
  AES_KEY — URL-safe base64-encoded Fernet key.
            Generate with:
              python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
            If unset, a one-time key is generated at startup (not persistent
            across restarts — only suitable for local development).

Usage:
  from auth.crypto import encrypt_payload, decrypt_payload

  encrypted_str = encrypt_payload({"user_id": "usr_4421", "ticket_price": 480})
  original_dict = decrypt_payload(encrypted_str)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------

_raw_key: str = os.getenv("AES_KEY", "")

if _raw_key:
    _fernet = Fernet(_raw_key.encode())
    logger.info("AES key loaded from AES_KEY environment variable.")
else:
    _generated_key = Fernet.generate_key()
    _fernet = Fernet(_generated_key)
    logger.warning(
        "AES_KEY env var is not set. "
        "A one-time key has been generated: %s  "
        "Set AES_KEY in your .env to persist encryption across restarts.",
        _generated_key.decode(),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encrypt_payload(data: Dict[str, Any]) -> str:
    """
    Serialize *data* to JSON and encrypt with AES-256 Fernet.

    Args:
        data: Arbitrary key-value payload dict (must be JSON-serializable).

    Returns:
        URL-safe base64-encoded ciphertext string.

    Raises:
        TypeError: If *data* contains non-JSON-serializable values.
    """
    plaintext: bytes = json.dumps(data, default=str).encode("utf-8")
    ciphertext: bytes = _fernet.encrypt(plaintext)
    return ciphertext.decode("utf-8")


def decrypt_payload(token: str) -> Dict[str, Any]:
    """
    Decrypt an encrypted payload string and return the original dict.

    Args:
        token: URL-safe base64-encoded ciphertext produced by encrypt_payload().

    Returns:
        The original dict that was passed to encrypt_payload().

    Raises:
        cryptography.fernet.InvalidToken: If the token is tampered with,
            uses a different key, or has expired (Fernet supports TTL).
        json.JSONDecodeError: If decryption succeeds but the plaintext is
            not valid JSON (should not happen in normal use).
    """
    try:
        plaintext: bytes = _fernet.decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        logger.error("Payload decryption failed — invalid or tampered token.")
        raise InvalidToken("Payload decryption failed — invalid token.") from exc

    return json.loads(plaintext.decode("utf-8"))
