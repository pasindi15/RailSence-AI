"""
booking-agent/main.py
---------------------
RailSense AI — Booking & Reservation Agent
Phase 1: FastAPI skeleton with /health, an internal message receiver,
and documented-but-not-implemented read route stubs.

What is intentionally NOT implemented here (Phase 2+)
------------------------------------------------------
- JWT / auth_token verification
- Booking creation, seat availability, fare calculation
- Cancellation eligibility and refund logic
- Database CRUD (get_db dependency wired but unused in Phase 1)
- NLP / LLM / RAG integration
- Email notifications
- Admin approval workflow
- CORS — add CORSMiddleware here when the Next.js origin is known;
  do NOT use allow_origins=["*"] in production.
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Resolve the shared package that lives at member-c/shared/
# ---------------------------------------------------------------------------
_MEMBER_C_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _MEMBER_C_ROOT not in sys.path:
    sys.path.insert(0, os.path.abspath(_MEMBER_C_ROOT))

from shared.schemas import AgentMessage  # noqa: E402

load_dotenv()

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RailSense AI - Booking & Reservation Agent",
    description=(
        "Handles structured booking and cancellation requests forwarded "
        "by the Agent Communication Hub."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    tags=["health"],
    summary="Liveness probe",
    response_description="Service health status",
)
async def health_check() -> dict:
    """
    Returns 200 OK when the booking agent is running.
    Used by container orchestrators and the Agent Hub's readiness checks.
    """
    return {"service": "booking-agent", "status": "ok"}


# ---------------------------------------------------------------------------
# Internal — inter-agent message receiver
# ---------------------------------------------------------------------------

@app.post(
    "/internal/messages",
    tags=["internal"],
    summary="Receive a forwarded AgentMessage from the Hub (Phase 1 — ack only)",
    status_code=202,
    response_description="Acknowledgement that the message was received",
)
async def receive_internal_message(message: AgentMessage) -> JSONResponse:
    """
    **Phase 1 behaviour**: validates the `AgentMessage` envelope and
    returns an acknowledgement.  No booking or cancellation logic is executed.

    **Not yet implemented** (Phase 2+):
    - `auth_token` JWT verification
    - intent dispatch (booking_request vs cancel_booking)
    - database writes
    - response back to the Agent Hub
    """
    return JSONResponse(
        status_code=202,
        content={
            "message_id": message.message_id,
            "intent": message.intent.value,  # .value → plain str; Enum is not JSON-serialisable
            "status": "received_for_phase_1",
            "note": (
                "Message validated. "
                "Intent dispatch and database writes are Phase 2 features."
            ),
        },
    )


# ---------------------------------------------------------------------------
# Booking read routes — stubs documented for Phase 2 implementation
# ---------------------------------------------------------------------------
# These endpoints are intentionally skeletal.  They prove the URL contracts
# are correct and prevent route conflicts when Phase 2 logic is added.
# They do NOT query the database or return fake production data.

@app.get(
    "/bookings/{booking_reference}",
    tags=["bookings"],
    summary="[Phase 2] Retrieve a booking by reference",
    response_description="Booking details",
    # Exclude from generated client code until implemented
    include_in_schema=True,
)
async def get_booking(booking_reference: str) -> JSONResponse:
    """
    **Phase 2**: will query the `bookings` table and return full booking
    details for the given `booking_reference`.

    Returns 501 Not Implemented until Phase 2 is complete.
    """
    return JSONResponse(
        status_code=501,
        content={
            "detail": (
                f"GET /bookings/{booking_reference} is not yet implemented. "
                "This endpoint will be active in Phase 2."
            )
        },
    )


# ---------------------------------------------------------------------------
# Cancellation read routes — stubs documented for Phase 2 implementation
# ---------------------------------------------------------------------------

@app.get(
    "/cancellations",
    tags=["cancellations"],
    summary="[Phase 2] List all cancellation requests",
    response_description="List of cancellation request summaries",
    include_in_schema=True,
)
async def list_cancellations() -> JSONResponse:
    """
    **Phase 2**: will return a paginated list of cancellation requests.

    Returns 501 Not Implemented until Phase 2 is complete.
    """
    return JSONResponse(
        status_code=501,
        content={
            "detail": (
                "GET /cancellations is not yet implemented. "
                "This endpoint will be active in Phase 2."
            )
        },
    )


@app.get(
    "/cancellations/{case_reference}",
    tags=["cancellations"],
    summary="[Phase 2] Retrieve a cancellation request by case reference",
    response_description="Cancellation request details",
    include_in_schema=True,
)
async def get_cancellation(case_reference: str) -> JSONResponse:
    """
    **Phase 2**: will query the `cancellation_requests` table by
    `case_reference` and return the full case record including NLP-populated
    fields and admin decision once available.

    Returns 501 Not Implemented until Phase 2 is complete.
    """
    return JSONResponse(
        status_code=501,
        content={
            "detail": (
                f"GET /cancellations/{case_reference} is not yet implemented. "
                "This endpoint will be active in Phase 2."
            )
        },
    )
