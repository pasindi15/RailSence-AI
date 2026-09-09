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


def write_audit_log(
    message_id: str,
    sender_agent: str,
    receiver_agent: str,
    intent: Any,
    status: AuditStatus | str,
    timestamp: datetime | None = None,
    error_message: str | None = None,
    db: Session | None = None,
) -> AuditLog:
    """
    Write a traceable audit log entry for an inter-agent message.

    Parameters
    ----------
    message_id : str
        Unique message identifier (e.g. 'MSG-2001').
    sender_agent : str
        Originating agent (e.g. 'passenger-agent').
    receiver_agent : str
        Target agent (e.g. 'booking-agent').
    intent : Any
        Message action or MemberCIntent enum.
    status : AuditStatus | str
        Processing status (e.g. AUTHENTICATED, REJECTED, FAILED).
    timestamp : datetime | None, optional
        Message creation timestamp. Defaults to UTC now if omitted.
    error_message : str | None, optional
        Human-readable reason if rejected or failed.
    db : Session | None, optional
        Active database session. If None, creates a standalone session.

    Returns
    -------
    AuditLog
        The persisted audit record.

    Raises
    ------
    HTTPException (500)
        If database persistence fails unexpectedly.
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

    # Instantiate AuditLog without auth_token or payload
    log_entry = AuditLog(
        message_id=message_id,
        sender_agent=sender_agent,
        receiver_agent=receiver_agent,
        intent=intent_str,
        status=audit_status,
        error_message=error_message,
        timestamp=record_time,
    )

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
        # Log failure safely without exposing sensitive connection info
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
