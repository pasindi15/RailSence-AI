"""
audit_log.py — Audit trail writer (Phase 1 stub)

Phase 1:  log_message() prints a structured record to stdout.
Phase 4:  This module is replaced with a real async writer to SQLite
          (local) or Supabase Postgres (production) using SQLAlchemy.

Keeping the same function signature across phases means main.py never
needs to change its import or call site.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional


def log_message(
    *,
    message_id: str,
    sender: str,
    receiver: str,
    intent: str,
    status: str,
    timestamp: Optional[datetime] = None,
    risk_flag: bool = False,
    encrypted: bool = False,
    latency_ms: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Write one audit record.

    Phase 1 — prints a JSON line to stdout so the log is visible during
    development without requiring a database.

    Phase 4 — this function will be replaced with an async SQLAlchemy
    INSERT into the audit_log table (SQLite locally, Supabase in prod).
    The call signature is identical so main.py requires no changes.

    Args:
        message_id:  Unique ID of the Hub message.
        sender:      Sending agent name.
        receiver:    Receiving agent name.
        intent:      Message intent string.
        status:      Outcome — 'forwarded', 'rejected', 'phase1-stub', etc.
        timestamp:   When the message arrived (defaults to now).
        risk_flag:   True if the fraud checker flagged this message.
        encrypted:   True if the payload was AES-encrypted.
        latency_ms:  Round-trip latency in milliseconds (None for Phase 1).
        extra:       Any additional metadata to include in the log line.
    """
    record: Dict[str, Any] = {
        "audit": True,
        "message_id": message_id,
        "sender": sender,
        "receiver": receiver,
        "intent": intent,
        "status": status,
        "timestamp": (timestamp or datetime.utcnow()).isoformat(),
        "risk_flag": risk_flag,
        "encrypted": encrypted,
        "latency_ms": latency_ms,
    }
    if extra:
        record.update(extra)

    # Phase 1: console only
    print(f"[AUDIT] {json.dumps(record)}")
