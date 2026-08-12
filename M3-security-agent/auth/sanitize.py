"""
auth/sanitize.py — Input sanitization for Hub message fields (Phase 2)

Runs in the Pydantic request model layer (before any routing logic) on all
string values inside the HubMessage payload dict.

Rules enforced:
  1. Max length  — rejects strings longer than max_len (default 2000 chars)
  2. Control characters — rejects strings containing \x00–\x1f (e.g. null
     bytes, escape sequences used in injection attacks)
  3. HTML markup — strips tags with bleach; raises if stripped != original
     (i.e. input contained HTML — rejected as potentially malicious)

Usage:
  from auth.sanitize import sanitize_text

  clean = sanitize_text("<script>alert(1)</script>", field_name="route")
  # raises ValueError: HTML markup found in field 'route'

  clean = sanitize_text("Colombo Fort - Kandy", field_name="route")
  # returns "Colombo Fort - Kandy" unchanged

Standalone vulnerability check (used by POST /security/vulnerability-check):
  from auth.sanitize import run_vulnerability_check
  result = run_vulnerability_check("<script>alert(1)</script>")
  # {"passed": False, "triggered_rule": "html_detected", "detail": "..."}
"""

from __future__ import annotations

import re
from typing import Any, Dict

import bleach

# ---------------------------------------------------------------------------
# Control character detection regex  (\x00–\x1f, excluding \t \n \r)
# ---------------------------------------------------------------------------
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# ---------------------------------------------------------------------------
# Maximum payload field length (characters)
# ---------------------------------------------------------------------------
DEFAULT_MAX_LEN = 2000


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sanitize_text(value: str, field_name: str = "field", max_len: int = DEFAULT_MAX_LEN) -> str:
    """
    Sanitize a single string value from a Hub message field.

    Args:
        value:      The string to sanitize.
        field_name: Human-readable field name for error messages.
        max_len:    Maximum allowed character length.

    Returns:
        The original *value* unchanged if all checks pass.

    Raises:
        ValueError: If any sanitization rule is violated.
    """
    # Rule 1 — length
    if len(value) > max_len:
        raise ValueError(
            f"Field '{field_name}' exceeds maximum length of {max_len} characters "
            f"(got {len(value)})."
        )

    # Rule 2 — control characters
    if _CONTROL_CHAR_RE.search(value):
        raise ValueError(
            f"Field '{field_name}' contains disallowed control characters."
        )

    # Rule 3 — HTML markup
    stripped = bleach.clean(value, tags=[], strip=True)
    if stripped != value:
        raise ValueError(
            f"HTML markup found in field '{field_name}' — rejected by sanitizer."
        )

    return value


def run_vulnerability_check(text: str, max_len: int = DEFAULT_MAX_LEN) -> Dict[str, Any]:
    """
    Run all sanitization rules on *text* and return a structured report.

    Used by POST /security/vulnerability-check to let callers test arbitrary
    inputs before integration.

    Args:
        text:    The text to check.
        max_len: Maximum allowed character length.

    Returns:
        A dict with keys: input_preview, passed, triggered_rule, detail.
        triggered_rule and detail are None when passed is True.
    """
    preview = text[:120] + ("..." if len(text) > 120 else "")

    # Rule 1 — length
    if len(text) > max_len:
        return {
            "input_preview": preview,
            "passed": False,
            "triggered_rule": "max_length_exceeded",
            "detail": (
                f"Input exceeds maximum length of {max_len} characters "
                f"(got {len(text)})."
            ),
        }

    # Rule 2 — control characters
    if _CONTROL_CHAR_RE.search(text):
        return {
            "input_preview": preview,
            "passed": False,
            "triggered_rule": "control_char_detected",
            "detail": "Input contains disallowed control characters (\\x00–\\x1f).",
        }

    # Rule 3 — HTML markup
    stripped = bleach.clean(text, tags=[], strip=True)
    if stripped != text:
        return {
            "input_preview": preview,
            "passed": False,
            "triggered_rule": "html_detected",
            "detail": "HTML markup found in payload field — rejected by bleach sanitizer.",
        }

    return {
        "input_preview": preview,
        "passed": True,
        "triggered_rule": None,
        "detail": "All sanitization checks passed.",
    }
