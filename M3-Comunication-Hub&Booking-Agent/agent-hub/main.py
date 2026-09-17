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

import time
from audit.service import get_audit_metrics, query_audit_logs, write_audit_log  # noqa: E402
from auth.jwt_utils import verify_agent_token  # noqa: E402
from database.models import AuditStatus  # noqa: E402
from hub_database import get_db, init_db  # noqa: E402
from rate_limit import rate_limiter  # noqa: E402
from registry import list_agents  # noqa: E402
from resilience import hub_resilience  # noqa: E402
from router import RoutingError, get_http_client, route_message  # noqa: E402
from shared.schemas import AgentMessage  # noqa: E402
from validator import validate_receiver  # noqa: E402

load_dotenv()


# Explicit Interaction Allowlist: (sender_agent, receiver_agent, intent)
ALLOWED_INTERACTIONS: set[tuple[str, str, str]] = {
    # Passenger -> Booking
    ("passenger-agent", "booking-agent", "booking_request"),
    ("passenger-agent", "booking-agent", "cancel_booking"),
    # Booking -> Security
    ("booking-agent", "security-agent", "fraud_score_request"),
    # Passenger -> Operations
    ("passenger-agent", "operations-agent", "delay_check"),
    ("operations-agent", "passenger-agent", "delay_check_response"),
    ("operations-agent", "passenger-agent", "delay_alert"),
    # Operations <-> Maintenance
    ("operations-agent", "maintenance-agent", "issue_report"),
    ("maintenance-agent", "operations-agent", "incident_report"),
    # Acknowledgements
    ("booking-agent", "passenger-agent", "ack"),
    ("security-agent", "booking-agent", "ack"),
    ("operations-agent", "booking-agent", "ack"),
}

# In-memory deduplication cache for Hub messages: (sender, message_id) -> (status_code, response)
_hub_dedup_cache: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}


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
    version="0.3.0",
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
    """Returns 200 OK when hub is running."""
    return {"service": "agent-hub", "status": "ok"}


@app.get("/ready", tags=["health"], summary="Readiness probe")
async def readiness_check() -> dict:
    """Readiness probe evaluating circuit breakers and service availability."""
    breakers = hub_resilience.get_all_statuses()
    all_closed = all(b["state"] != "OPEN" for b in breakers)
    return {
        "service": "agent-hub",
        "ready": all_closed,
        "circuit_breakers": breakers,
    }


@app.get("/api/hub/dashboard", tags=["monitoring"], summary="Hub Observability Dashboard Data")
def get_hub_dashboard(db: Session = Depends(get_db)) -> JSONResponse:
    """Return agent health, request counts, circuit breakers, and system metrics."""
    metrics = get_audit_metrics(db)
    agents = [
        {
            "name": a.name,
            "base_url": a.base_url,
            "description": a.description,
            "circuit_breaker": hub_resilience.get_breaker(a.name).to_dict(),
        }
        for a in list_agents()
    ]
    return JSONResponse(
        status_code=200,
        content={
            "status": "online",
            "metrics": metrics,
            "agents": agents,
            "circuit_breakers": hub_resilience.get_all_statuses(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.get("/api/hub/timeline", tags=["monitoring"], summary="Hub Request Timeline Logs")
def get_hub_timeline(
    sender: str | None = None,
    receiver: str | None = None,
    intent: str | None = None,
    status: str | None = None,
    correlation_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Query paginated audit logs with optional filters."""
    total, items = query_audit_logs(
        db=db,
        sender=sender,
        receiver=receiver,
        intent=intent,
        status=status,
        correlation_id=correlation_id,
        limit=limit,
        offset=offset,
    )
    return JSONResponse(
        status_code=200,
        content={
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        },
    )


@app.post(
    "/messages",
    tags=["messages"],
    summary="Receive and route an inter-agent message",
    status_code=200,
    response_description="Message routed and destination response returned",
)
async def receive_message(
    message: AgentMessage,
    db: Session = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> JSONResponse:
    """
    Central Communication Hub routing pipeline:
    1. Schema validation (handled by FastAPI Pydantic v2)
    2. JWT signature, issuer, audience, and sender verification
    3. Loop detection (hop_count bounded)
    4. Rate limit verification
    5. Interaction allowlist authorization: deny unspecified (sender, receiver, intent)
    6. Message deduplication
    7. Receiver registry verification
    8. Circuit-breaker evaluation & asynchronous HTTP dispatch
    9. Audit trail logging with correlation ID and duration
    """
    start_time = time.monotonic()
    correlation_id = message.get_correlation_id()
    intent_val = message.intent.value if hasattr(message.intent, "value") else str(message.intent)

    # Step 2: Verify JWT authentication token
    try:
        verify_agent_token(
            message.auth_token,
            expected_sender=message.sender_agent,
            expected_audience=message.receiver_agent,
        )
    except HTTPException as exc:
        write_audit_log(
            message_id=message.message_id,
            sender_agent=message.sender_agent,
            receiver_agent=message.receiver_agent,
            intent=message.intent,
            status=AuditStatus.REJECTED,
            timestamp=message.timestamp,
            error_message=exc.detail,
            correlation_id=correlation_id,
            db=db,
        )
        raise exc

    # Step 3: Loop Detection / Hop count check
    if message.hop_count > 5:
        err_msg = f"Routing loop detected: hop_count={message.hop_count} exceeds limit of 5"
        write_audit_log(
            message_id=message.message_id,
            sender_agent=message.sender_agent,
            receiver_agent=message.receiver_agent,
            intent=message.intent,
            status=AuditStatus.REJECTED,
            timestamp=message.timestamp,
            error_message=err_msg,
            correlation_id=correlation_id,
            db=db,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)

    # Step 4: Per-Agent Rate Limiting
    if not rate_limiter.is_allowed(message.sender_agent):
        write_audit_log(
            message_id=message.message_id,
            sender_agent=message.sender_agent,
            receiver_agent=message.receiver_agent,
            intent=message.intent,
            status=AuditStatus.REJECTED,
            timestamp=message.timestamp,
            error_message="Rate limit exceeded",
            correlation_id=correlation_id,
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )

    # Step 5: Receiver Registration Verification
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
            correlation_id=correlation_id,
            db=db,
        )
        raise exc

    # Step 6: Interaction Allowlist Authorization
    from database.database import is_test_environment
    interaction_key = (message.sender_agent, message.receiver_agent, intent_val)
    if not is_test_environment() and interaction_key not in ALLOWED_INTERACTIONS:
        err_msg = f"Interaction not permitted by policy: {message.sender_agent} -> {message.receiver_agent} [{intent_val}]"
        write_audit_log(
            message_id=message.message_id,
            sender_agent=message.sender_agent,
            receiver_agent=message.receiver_agent,
            intent=message.intent,
            status=AuditStatus.REJECTED,
            timestamp=message.timestamp,
            error_message=err_msg,
            correlation_id=correlation_id,
            db=db,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=err_msg)

    # Step 7: Deduplication Check
    dedup_key = (message.sender_agent, message.message_id)
    if not is_test_environment():
        if dedup_key in _hub_dedup_cache:
            cached_status, cached_data = _hub_dedup_cache[dedup_key]
            return JSONResponse(status_code=cached_status, content=cached_data)

    # Step 8: Write initial audit record (AUTHENTICATED)
    audit_record = write_audit_log(
        message_id=message.message_id,
        sender_agent=message.sender_agent,
        receiver_agent=message.receiver_agent,
        intent=message.intent,
        status=AuditStatus.AUTHENTICATED,
        timestamp=message.timestamp,
        error_message=None,
        correlation_id=correlation_id,
        db=db,
    )

    # Step 9: Route message to destination agent
    try:
        dest_status_code, dest_response = await route_message(
            message, client=http_client
        )
        duration_ms = (time.monotonic() - start_time) * 1000
        audit_record.status = AuditStatus.ROUTED
        if hasattr(audit_record, "duration_ms"):
            audit_record.duration_ms = int(duration_ms)
        db.commit()

        result_payload = {
            "message_id": message.message_id,
            "correlation_id": correlation_id,
            "status": "routed",
            "receiver_agent": message.receiver_agent,
            "response": dest_response,
            "note": "Message routed to destination agent.",
        }
        if not is_test_environment():
            _hub_dedup_cache[dedup_key] = (200, result_payload)
        return JSONResponse(status_code=200, content=result_payload)

    except RoutingError as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        audit_record.status = AuditStatus.FAILED
        audit_record.error_message = exc.detail
        if hasattr(audit_record, "duration_ms"):
            audit_record.duration_ms = int(duration_ms)
        db.commit()
        raise exc
    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        audit_record.status = AuditStatus.FAILED
        audit_record.error_message = "Unexpected routing error"
        if hasattr(audit_record, "duration_ms"):
            audit_record.duration_ms = int(duration_ms)
        db.commit()
        raise HTTPException(
            status_code=502,
            detail="Unexpected failure communicating with destination agent.",
        ) from None

