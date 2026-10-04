"""
privacy_assessment/pii_scanner.py
---------------------------------
RailSense AI — Privacy & Personally Identifiable Information (PII) Scanner.
Module: IT3041 Information Retrieval and Web Analytics
Assigned Specialisation: Privacy and Data Leakage Assessment (Student 2)

Automated pattern-matching engine for detecting, cataloguing, and redacting
sensitive data, credentials, and passenger PII across API bodies, logs,
error streams, and message payloads.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Union

# ---------------------------------------------------------------------------
# PII & Sensitive Pattern Definitions (Sri Lanka & RailSense Domain)
# ---------------------------------------------------------------------------
PATTERNS = {
    # Sri Lankan National Identity Card (Old format: 9 digits + V/X)
    "SL_NIC_OLD": re.compile(r"\b[0-9]{9}[vVxX]\b"),
    # Sri Lankan National Identity Card (New format: 12 digits, typically starts with 19 or 20)
    "SL_NIC_NEW": re.compile(r"\b(19|20)[0-9]{10}\b"),
    # Generic 12 digit number when within passenger context
    "GENERIC_NIC_12DIGIT": re.compile(r"\b[0-9]{12}\b"),
    # Email addresses
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"),
    # Sri Lankan telephone numbers (+947xxxxxxxx, 07xxxxxxxx)
    "PHONE_SL": re.compile(r"\b(?:\+94|0)(?:7[01245678]|11|2[1-8]|3[1-8]|4[1-7]|5[1-7]|6[3-7]|81)\d{7}\b"),
    # JSON Web Tokens (3-part base64url structure)
    "JWT_TOKEN": re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+\b"),
    # Bearer authentication header strings
    "BEARER_TOKEN": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]+\b"),
    # Password / secret assignments in text/configs/JSON
    "SECRET_ASSIGNMENT": re.compile(r"(?i)(password|secret_key|jwt_secret|api_key|service_role|supabase_key|auth_token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-.~!@#$%^&*()+=]{6,})['\"]?"),
    # Database connection URIs
    "DB_CONNECTION_URI": re.compile(r"(?i)(postgresql|postgres|mysql|sqlite|mongodb)\+?[a-z]*://[^\s'\"]+"),
    # Python stack traces / Internal file paths
    "STACK_TRACE": re.compile(r"(Traceback \(most recent call last\):|File \".*?\", line \d+|fastapi\.exceptions|sqlalchemy\.exc)"),
    # Internal booking references (RS-XXXXX or BK-XXXXX)
    "BOOKING_REF": re.compile(r"\b(?:RS|BK)-[A-Z0-9]{4,12}\b"),
    # Sri Lanka train service codes
    "TRAIN_ID": re.compile(r"\b[A-Z]{2,12}-\d{3,5}\b"),
}

# Known sensitive environment key names or known values from audit
SENSITIVE_ENV_PATTERNS = [
    "JWT_SECRET_KEY",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "SMTP_PASSWORD",
    "hhqkakajstgcpeby",      # Discovered SMTP app password
    "mkatERZylm0r2Lre",      # Discovered service secret fragment
    "railsense-nic-hmac",    # Discovered HMAC key name
]


@dataclass
class PIIFinding:
    """Represents an identified sensitive data exposure."""
    category: str
    match_value_redacted: str
    position: Optional[int] = None
    severity: str = "High"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PIIScanner:
    """Comprehensive scanner for detecting and masking sensitive data."""

    @staticmethod
    def is_nic_masked(val: str) -> bool:
        """
        Returns True if the NIC representation is properly masked or hashed.
        Examples: '2000****5678', '9912****V', or 64-char HMAC-SHA256 hex string.
        """
        if not val or not isinstance(val, str):
            return False
        # Masked format with asterisks
        if "*" in val:
            return True
        # 64-char hex string (HMAC-SHA256 hash)
        if len(val) == 64 and re.fullmatch(r"[0-9a-fA-F]{64}", val):
            return True
        return False

    @staticmethod
    def scan_text(text: str, target_synthetic_values: Optional[List[str]] = None) -> List[PIIFinding]:
        """
        Scan a plain text or JSON string for sensitive patterns.
        """
        if not text or not isinstance(text, str):
            return []

        findings: List[PIIFinding] = []

        # Check for explicitly supplied synthetic test values (e.g. specific test NIC or email)
        if target_synthetic_values:
            for val in target_synthetic_values:
                if val and val in text:
                    redacted = val[:2] + "****" + val[-2:] if len(val) > 4 else "****"
                    findings.append(PIIFinding(
                        category="SYNTHETIC_TARGET_PII",
                        match_value_redacted=f"[LEAKED: {redacted}]",
                        severity="High"
                    ))

        # Check for known leaked environment secrets
        for secret_val in SENSITIVE_ENV_PATTERNS:
            if secret_val in text:
                redacted = secret_val[:3] + "..." + secret_val[-3:] if len(secret_val) > 6 else "[SECRET]"
                findings.append(PIIFinding(
                    category="CREDENTIAL_OR_SECRET",
                    match_value_redacted=f"[SECRET: {redacted}]",
                    severity="Critical"
                ))

        # Check regex patterns
        for cat_name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                matched_str = match.group(0)

                # Skip if matched value is already masked
                if cat_name in ("SL_NIC_OLD", "SL_NIC_NEW", "GENERIC_NIC_12DIGIT"):
                    if PIIScanner.is_nic_masked(matched_str):
                        continue

                # Categorize severity
                if cat_name in ("JWT_TOKEN", "BEARER_TOKEN", "SECRET_ASSIGNMENT", "DB_CONNECTION_URI"):
                    sev = "Critical"
                elif cat_name in ("SL_NIC_OLD", "SL_NIC_NEW", "EMAIL", "PHONE_SL"):
                    sev = "High"
                elif cat_name == "STACK_TRACE":
                    sev = "Medium"
                else:
                    sev = "Low"

                redacted = matched_str[:2] + "****" + matched_str[-2:] if len(matched_str) > 4 else "****"
                findings.append(PIIFinding(
                    category=cat_name,
                    match_value_redacted=f"[{cat_name}: {redacted}]",
                    position=match.start(),
                    severity=sev
                ))

        return findings

    @staticmethod
    def scan_data_structure(data: Any, target_synthetic_values: Optional[List[str]] = None) -> List[PIIFinding]:
        """Convert arbitrary dictionary/list structure into serialized text and scan."""
        try:
            serialized = json.dumps(data, default=str)
        except Exception:
            serialized = str(data)
        return PIIScanner.scan_text(serialized, target_synthetic_values=target_synthetic_values)

    @staticmethod
    def redact_text(text: str) -> str:
        """
        Redacts all sensitive patterns from a text string, replacing them with safe placeholders.
        Guarantees that evidence files and logs do not preserve raw secrets.
        """
        if not text or not isinstance(text, str):
            return text

        result = text

        # Redact known credentials
        for secret_val in SENSITIVE_ENV_PATTERNS:
            result = result.replace(secret_val, "[REDACTED_SECRET]")

        # Redact JWTs
        result = PATTERNS["JWT_TOKEN"].sub("[REDACTED_JWT_TOKEN]", result)
        # Redact Bearer tokens
        result = PATTERNS["BEARER_TOKEN"].sub("Bearer [REDACTED_TOKEN]", result)
        # Redact secret assignments
        result = PATTERNS["SECRET_ASSIGNMENT"].sub(r"\1=[REDACTED_CREDENTIAL]", result)
        # Redact database URIs
        result = PATTERNS["DB_CONNECTION_URI"].sub("[REDACTED_DB_URI]", result)
        # Redact Sri Lankan NICs
        result = PATTERNS["SL_NIC_NEW"].sub("[REDACTED_NIC_12D]", result)
        result = PATTERNS["SL_NIC_OLD"].sub("[REDACTED_NIC_9D]", result)
        # Redact emails (except local audit domain)
        result = re.sub(r"\b[A-Za-z0-9._%+-]+@(?!railsense-audit\.local)[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b", "[REDACTED_EMAIL]", result)

        return result
