"""
shared/nic.py
-------------
RailSense AI — National Identity Card (NIC) Privacy & Validation Utilities.

Responsibilities:
1. Sri Lankan NIC Format Validation:
   - Old format: 9 digits followed by 'V' or 'X' (e.g., 123456789V, 923456789X)
   - New format: 12 digits (e.g., 199012345678, 200312345678)
2. Normalization:
   - Strips whitespace and normalizes suffix to uppercase.
3. Privacy & Deterministic Lookup:
   - Computes HMAC-SHA256 hash using NIC_HMAC_SECRET for database indexing and conflict checks.
   - Raw NIC is never stored or logged.
4. Administrative Masking:
   - Masks all but last 4 characters (e.g., ********5678) for safe UI display.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re


NIC_OLD_PATTERN = re.compile(r"^\d{9}[vVxX]$")
NIC_NEW_PATTERN = re.compile(r"^\d{12}$")


class InvalidNICError(ValueError):
    """Raised when an NIC fails Sri Lankan format validation."""
    pass


def normalize_nic(nic: str) -> str:
    """Strip whitespace and convert suffix to uppercase."""
    if not nic:
        return ""
    return nic.strip().upper()


def validate_sri_lankan_nic(nic: str) -> tuple[bool, str]:
    """
    Validate Sri Lankan National Identity Card format.

    Supports:
    - Old format: 9 digits + 'V' or 'X' (case-insensitive)
    - New format: 12 digits

    Returns
    -------
    tuple[bool, str]:
        (True, normalized_nic) if valid,
        (False, error_message) if invalid.
    """
    clean = normalize_nic(nic)
    if not clean:
        return False, "INVALID_NIC: NIC number is required."

    if NIC_OLD_PATTERN.match(clean):
        return True, clean

    if NIC_NEW_PATTERN.match(clean):
        return True, clean

    return False, (
        f"INVALID_NIC: '{clean}' is not a valid Sri Lankan NIC. "
        "Must be 9 digits followed by 'V'/'X' (old format) or 12 digits (new format)."
    )


def hash_nic(nic: str, secret: str | None = None) -> str:
    """
    Generate a deterministic HMAC-SHA256 digest of the normalized NIC.

    Used for database indexing, duplicate detection, and cross-train conflict lookups
    without storing or exposing plaintext NICs.
    """
    clean = normalize_nic(nic)
    if not clean:
        raise InvalidNICError("Cannot hash empty NIC.")

    hmac_key = secret or os.getenv("NIC_HMAC_SECRET", "railsense-nic-hmac-secret-2026")
    return hmac.new(
        hmac_key.encode("utf-8"),
        clean.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def mask_nic(nic: str) -> str:
    """
    Mask NIC for privacy-preserving administrative display.

    Example:
    '123456789V'   -> '******678V'
    '200312345678' -> '********5678'
    """
    clean = normalize_nic(nic)
    if not clean:
        return "********"
    if len(clean) <= 4:
        return "****" + clean
    masked_part = "*" * (len(clean) - 4)
    return f"{masked_part}{clean[-4:]}"
