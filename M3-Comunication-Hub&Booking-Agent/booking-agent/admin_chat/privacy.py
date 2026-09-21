"""
admin_chat/privacy.py
---------------------
Privacy preservation, PII masking, and prompt-injection defense utilities
for the RailSense AI Admin Booking Intelligence Chatbot.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

# Ensure access to shared/nic.py
_CURRENT_DIR = Path(__file__).resolve().parent
_BOOKING_AGENT_DIR = _CURRENT_DIR.parent
_M3_ROOT = _BOOKING_AGENT_DIR.parent
for p in (str(_M3_ROOT), str(_BOOKING_AGENT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.nic import mask_nic


PROMPT_INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?(previous\s+)?instructions",
    r"(?i)system\s*override",
    r"(?i)override\s*rules?",
    r"(?i)show\s+every\s+nic",
    r"(?i)show\s+(all\s+)?passwords?",
    r"(?i)reveal\s+(system\s+)?prompt",
    r"(?i)disregard\s+(the\s+)?rules",
    r"(?i)jailbreak",
    r"(?i)drop\s+table",
    r"(?i)truncate\s+table",
    r"(?i)delete\s+from",
]


def sanitize_admin_input(text: str | None, max_length: int = 500) -> str:
    """
    Sanitize administrator query:
    1. Truncate to maximum allowed length.
    2. Strip prompt-injection keywords.
    3. Mask any accidental plaintext NIC numbers.
    """
    if not text:
        return ""

    cleaned = text.strip()[:max_length]

    # Neutralize prompt injection markers
    for pattern in PROMPT_INJECTION_PATTERNS:
        cleaned = re.sub(pattern, "[FILTERED]", cleaned)

    # Mask any raw Sri Lankan NICs (9 digits + V/X, or 12 digits)
    cleaned = re.sub(
        r"\b(\d{9}[vVxX]|\d{12})\b",
        lambda m: mask_nic(m.group(1)),
        cleaned,
    )

    return cleaned


def mask_passenger_info(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Ensure all passenger objects have their NICs masked and no raw PII exposed.
    """
    sanitized: list[dict[str, Any]] = []
    for rec in records:
        item = dict(rec)
        if "nic" in item and item["nic"]:
            item["nic_masked"] = mask_nic(str(item["nic"]))
            item.pop("nic", None)
        if "primary_nic" in item and item["primary_nic"]:
            item["nic_masked"] = mask_nic(str(item["primary_nic"]))
            item.pop("primary_nic", None)
        if "primary_nic_hash" in item:
            item.pop("primary_nic_hash", None)
        sanitized.append(item)
    return sanitized
