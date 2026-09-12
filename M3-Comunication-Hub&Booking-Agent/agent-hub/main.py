"""
agent-hub/main.py
-----------------
RailSense AI — Central Agent Communication Hub
Phase 2 (Complete Communication Hub Pipeline):
Receive
→ Validate schema (Pydantic v2)
→ Verify JWT
→ Check receiver (registry)
→ Write audit information
→ Route to destination (asynchronous httpx)
→ Record route result
→ Return destination response

Architectural rules:
- Does NOT perform booking business logic, fare calculation, seat checks, or cancellations.
- Hub only receives, authenticates, audits, and forwards structured messages.
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
_CURRENT_DIR = os.path.dirname(__file__)
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_CURRENT_DIR))

_MEMBER_C_ROOT = os.path.join(_CURRENT_DIR, "..")
if _MEMBER_C_ROOT not in sys.path:
    sys.path.insert(0, os.path.abspath(_MEMBER_C_ROOT))

_BOOKING_AGENT_DIR = os.path.join(_MEMBER_C_ROOT, "booking-agent")
if _BOOKING_AGENT_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_BOOKING_AGENT_DIR))

from audit.service import write_audit_log  # noqa: E402
from auth.jwt_utils import verify_agent_token  # noqa: E402
from database.models import AuditStatus  # noqa: E402
from hub_database import get_db, init_db  # noqa: E402
from rate_limit import rate_limiter  # noqa: E402
from router import RoutingError, get_http_client, route_message  # noqa: E402
from shared.schemas import AgentMessage  # noqa: E402
from validator import validate_receiver  # noqa: E402

load_dotenv()


# ---------------------------------------------------------------------------
# Application Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup (if available)
    init_db()
    yield


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RailSense AI - Agent Communication Hub",
    description=(
        "Central hub responsible for receiving, validating, authenticating, "
        "auditing, and routing structured inter-agent messages across the RailSense AI system."
    ),
    version="0.2.3",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    tags=["health"],
    summary="Liveness probe",
    response_description="Service health status",
)
async def health_check() -> dict:
    """
    Returns 200 OK with a minimal JSON body when the hub is running.
    Used by container orchestrators and load balancers.
    """
    return {"service": "agent-hub", "status": "ok"}


@app.post(
    "/messages",
    tags=["messages"],
    summary="Receive an inter-agent message (Phase 2 complete pipeline)",
    status_code=200,
    response_description="Message routed and destination response returned",
)
async def receive_message(
    message: AgentMessage,
    db: Session = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> JSONResponse:
    """
    Complete Phase 2 Communication Hub pipeline:
    1. Receive & Pydantic schema validation: handled automatically by FastAPI.
    2. JWT authentication: verify token signature, expiry, and sender match.
       If invalid -> record REJECTED in audit_logs, return 401.
    3. Receiver validation: check receiver_agent against central registry.
       If unregistered -> record REJECTED in audit_logs, return 404.
    4. Write initial audit record (status: AUTHENTICATED).
    5. Route message to destination internal endpoint via asynchronous httpx.
       - If routing fails (502/503/504) -> record FAILED in audit_logs, raise HTTP error.
       - If routing succeeds -> record ROUTED in audit_logs.
    6. Return destination response in structured format.
    """
    # Step 2: Verify JWT authentication token
    try:
        verify_agent_token(message.auth_token, expected_sender=message.sender_agent)
    except HTTPException as exc:
        write_audit_log(
            message_id=message.message_id,
            sender_agent=message.sender_agent,
            receiver_agent=message.receiver_agent,
            intent=message.intent,
            status=AuditStatus.REJECTED,
            timestamp=message.timestamp,
            error_message=exc.detail,
            db=db,
        )
        raise exc

    # Step 2.5: Per-Agent Rate Limiting & Flood Protection
    if not rate_limiter.is_allowed(message.sender_agent):
        write_audit_log(
            message_id=message.message_id,
            sender_agent=message.sender_agent,
            receiver_agent=message.receiver_agent,
            intent=message.intent,
            status=AuditStatus.REJECTED,
            timestamp=message.timestamp,
            error_message="Rate limit exceeded",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )

    # Step 3: Verify receiver exists in central registry
    try:
        validate_receiver(message.receiver_agent)
    except HTTPException as exc:
        write_audit_log(
            message_id=message.message_id,
            sender_agent=message.sender_agent,
            receiver_agent=message.receiver_agent,
            intent=message.intent,
            status=AuditStatus.REJECTED,
            timestamp=message.timestamp,
            error_message=exc.detail,
            db=db,
        )
        raise exc

    # Step 4: Write audit record (pre-routing record)
    audit_record = write_audit_log(
        message_id=message.message_id,
        sender_agent=message.sender_agent,
        receiver_agent=message.receiver_agent,
        intent=message.intent,
        status=AuditStatus.AUTHENTICATED,
        timestamp=message.timestamp,
        error_message=None,
        db=db,
    )

    # Step 5: Route message to destination agent
    try:
        dest_status_code, dest_response = await route_message(
            message, client=http_client
        )
        # Step 6: Record route result (ROUTED)
        audit_record.status = AuditStatus.ROUTED
        db.commit()
    except RoutingError as exc:
        # Step 6: Record route result (FAILED)
        audit_record.status = AuditStatus.FAILED
        audit_record.error_message = exc.detail
        db.commit()
        raise exc
    except Exception as exc:
        audit_record.status = AuditStatus.FAILED
        audit_record.error_message = "Unexpected routing error"
        db.commit()
        raise HTTPException(
            status_code=502,
            detail="Unexpected failure communicating with destination agent.",
        ) from None

    # Step 7: Return structured destination response
    return JSONResponse(
        status_code=200,
        content={
            "message_id": message.message_id,
            "status": "routed",
            "receiver_agent": message.receiver_agent,
            "response": dest_response,
            "note": "Message routed to destination agent.",
        },
    )
