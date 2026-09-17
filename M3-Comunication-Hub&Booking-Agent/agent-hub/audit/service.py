"""
agent-hub/audit/service.py
--------------------------
RailSense AI — Central Agent Communication Hub Audit Service
Phase 2: Traceable message auditing.

Responsibilities:
- Persists structured message trace to the audit_logs table.
- Records: message_id, sender_agent, receiver_agent, intent, status, timestamp, error_message.
- Enforces privacy & security: NEVER stores auth_token, JWT secrets, or payload body.
- Handles database exceptions gracefully without exposing credentials or internal traces.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# Path resolution
_CURRENT_DIR = os.path.dirname(__file__)
_AGENT_HUB_DIR = os.path.abspath(os.path.join(_CURRENT_DIR, ".."))
_MEMBER_C_ROOT = os.path.abspath(os.path.join(_AGENT_HUB_DIR, ".."))
_BOOKING_AGENT_DIR = os.path.join(_MEMBER_C_ROOT, "booking-agent")

for p in (_CURRENT_DIR, _AGENT_HUB_DIR, _MEMBER_C_ROOT, _BOOKING_AGENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from database.models import AuditLog, AuditStatus  # noqa: E402
from hub_database import SessionLocal  # noqa: E402

logger = logging.getLogger("agent-hub.audit")


import re


def sanitize_audit_text(text: str | None) -> str | None:
    """Strip tokens, passwords, raw NICs, and secrets from text before storing in audit logs."""
    if not text:
        return text
    # Mask bearer tokens
    cleaned = re.sub(r"(?i)bearer\s+[A-Za-z0-9-_=.]+", "Bearer [REDACTED_TOKEN]", text)
    # Mask passwords
    cleaned = re.sub(r"(?i)(password|secret)[=:]\s*['\"]?[^\s'\"]+['\"]?", r"\1=[REDACTED]", cleaned)
    # Mask 9-12 digit numbers looking like raw NICs
    cleaned = re.sub(r"\b\d{9}[vVxX]?\b", "[REDACTED_NIC]", cleaned)
    cleaned = re.sub(r"\b\d{12}\b", "[REDACTED_NIC]", cleaned)
    return cleaned


def write_audit_log(
    message_id: str,
    sender_agent: str,
    receiver_agent: str,
    intent: Any,
    status: AuditStatus | str,
    timestamp: datetime | None = None,
    error_message: str | None = None,
    db: Session | None = None,
    correlation_id: str | None = None,
    duration_ms: float | None = None,
    retry_count: int = 0,
) -> AuditLog:
    """
    Write a traceable audit log entry for an inter-agent message.
    """
    # Normalize status enum
    if isinstance(status, str):
        try:
            audit_status = AuditStatus(status)
        except ValueError:
            audit_status = AuditStatus[status]
    else:
        audit_status = status

    # Normalize intent to string representation
    intent_str = str(intent.value if hasattr(intent, "value") else intent)

    # Normalize timestamp
    record_time = timestamp or datetime.now(timezone.utc)

    sanitized_err = sanitize_audit_text(error_message)

    # Instantiate AuditLog without auth_token or payload
    log_entry = AuditLog(
        message_id=message_id,
        sender_agent=sender_agent,
        receiver_agent=receiver_agent,
        intent=intent_str,
        status=audit_status,
        error_message=sanitized_err,
        timestamp=record_time,
    )
    if hasattr(log_entry, "correlation_id") and correlation_id:
        setattr(log_entry, "correlation_id", correlation_id)
    if hasattr(log_entry, "duration_ms") and duration_ms is not None:
        setattr(log_entry, "duration_ms", int(duration_ms))
    if hasattr(log_entry, "retry_count"):
        setattr(log_entry, "retry_count", retry_count)

    should_close = False
    active_session = db
    if active_session is None:
        active_session = SessionLocal()
        should_close = True

    try:
        active_session.add(log_entry)
        active_session.commit()
        active_session.refresh(log_entry)
        return log_entry
    except Exception as exc:
        try:
            active_session.rollback()
        except Exception:
            pass
        logger.error(
            "Failed to persist audit log for message_id=%s: %s",
            message_id,
            exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="Audit logging service failed to persist message trace.",
        ) from None
    finally:
        if should_close and active_session is not None:
            active_session.close()


def query_audit_logs(
    db: Session,
    sender: str | None = None,
    receiver: str | None = None,
    intent: str | None = None,
    status: str | None = None,
    correlation_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """Query audit logs with filtering and pagination for the dashboard timeline."""
    query = db.query(AuditLog)
    if sender:
        query = query.filter(AuditLog.sender_agent == sender)
    if receiver:
        query = query.filter(AuditLog.receiver_agent == receiver)
    if intent:
        query = query.filter(AuditLog.intent == intent)
    if status:
        query = query.filter(AuditLog.status == status)
    if correlation_id and hasattr(AuditLog, "correlation_id"):
        query = query.filter(AuditLog.correlation_id == correlation_id)

    total = query.count()
    rows = query.order_by(AuditLog.id.desc()).offset(offset).limit(limit).all()

    results = []
    for r in rows:
        results.append({
            "id": r.id,
            "message_id": r.message_id,
            "correlation_id": getattr(r, "correlation_id", None) or r.message_id,
            "sender_agent": r.sender_agent,
            "receiver_agent": r.receiver_agent,
            "intent": r.intent,
            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            "error_message": r.error_message,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "duration_ms": float(r.duration_ms) if getattr(r, "duration_ms", None) is not None else None,
            "retry_count": getattr(r, "retry_count", 0),
        })
    return total, results


def get_audit_metrics(db: Session) -> dict[str, Any]:
    """Compute aggregate counts for the Communication Hub Dashboard."""
    from sqlalchemy import func
    total_messages = db.query(func.count(AuditLog.id)).scalar() or 0
    routed_count = db.query(func.count(AuditLog.id)).filter(AuditLog.status == AuditStatus.ROUTED).scalar() or 0
    rejected_count = db.query(func.count(AuditLog.id)).filter(AuditLog.status == AuditStatus.REJECTED).scalar() or 0
    failed_count = db.query(func.count(AuditLog.id)).filter(AuditLog.status == AuditStatus.FAILED).scalar() or 0

    return {
        "total_messages": total_messages,
        "routed_count": routed_count,
        "rejected_count": rejected_count,
        "failed_count": failed_count,
    }

