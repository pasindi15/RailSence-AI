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

from datetime import date
import os
import sys
from contextlib import asynccontextmanager

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

from booking.exceptions import (
    ConflictingActiveJourneyError,
    DuplicateActiveTicketError,
    DuplicateNICInBookingError,
    FareNotFoundError,
    InvalidBookingError,
    ScheduleNotFoundError,
    SeatsUnavailableError,
    TrainNotFoundError,
)
from booking.service import BookingService
from cancellation.service import (
    CancellationService,
    CancellationError,
    BookingNotFoundError,
    BookingAlreadyCancelledError,
    CancellationAlreadyPendingError,
)
from database.database import get_db, init_db
from pydantic import BaseModel, Field
from schemas.booking import BookingRequest
from shared.schemas import AgentMessage, MemberCIntent

load_dotenv()

# ---------------------------------------------------------------------------
# Application Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database tables exist on startup (seed test schedules in test environments)
    try:
        from database.database import is_test_environment
        init_db(seed=is_test_environment())
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RailSense AI - Booking & Reservation Agent",
    description=(
        "Handles structured booking and cancellation requests forwarded "
        "by the Agent Communication Hub."
    ),
    version="0.3.0",
    lifespan=lifespan,
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
    summary="Receive a forwarded AgentMessage from the Hub (Phase 3: Booking dispatch)",
    status_code=200,
    response_description="Message processed and booking confirmation returned",
)
async def receive_internal_message(
    message: AgentMessage,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Handle forwarded AgentMessage from the Central Communication Hub.

    Supported intents:
    - booking_request: validates payload using BookingRequest, calls BookingService,
      and returns structured booking confirmation.
    - cancel_booking: returns not-implemented response (reserved for subsequent phases).
    """
    intent_val = message.intent.value if hasattr(message.intent, "value") else str(message.intent)

    if intent_val == "booking_request":
        try:
            booking_req = BookingRequest.model_validate(message.payload)
        except Exception as exc:
            err_str = str(exc)
            if "duplicate_nic_in_booking" in err_str.lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"DUPLICATE_NIC_IN_BOOKING: Each passenger in a booking must provide a distinct NIC.",
                )
            if "invalid_nic" in err_str.lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"INVALID_NIC: One or more passenger NICs failed format validation.",
                )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid booking_request payload: {exc}",
            )

        service = BookingService(db)
        try:
            booking_result = service.process_booking(booking_req)
        except (TrainNotFoundError, ScheduleNotFoundError, FareNotFoundError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            )
        except SeatsUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            )
        except (DuplicateActiveTicketError, ConflictingActiveJourneyError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            )
        except (DuplicateNICInBookingError, InvalidBookingError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal booking error: {exc}",
            )

        fare_str = f"{booking_result.fare:.2f}"

        if booking_result.status == "PENDING_FRAUD_REVIEW":
            return JSONResponse(
                status_code=200,
                content={
                    "message_id": message.message_id,
                    "status": "pending_fraud_review",
                    "case_reference": booking_result.case_reference,
                    "risk_level": booking_result.risk_level,
                    "reasons": booking_result.reasons,
                    "message": "Your booking request requires security review.",
                    "booking": {
                        "booking_reference": None,
                        "case_reference": booking_result.case_reference,
                        "train_id": booking_result.train_id,
                        "from_station": booking_result.from_station,
                        "to_station": booking_result.to_station,
                        "travel_date": booking_result.travel_date.isoformat(),
                        "seat_class": booking_result.seat_class,
                        "passenger_count": booking_result.passenger_count,
                        "fare": fare_str,
                        "status": "PENDING_FRAUD_REVIEW",
                        "risk_level": booking_result.risk_level,
                        "reasons": booking_result.reasons,
                    },
                },
            )

        return JSONResponse(
            status_code=200,
            content={
                "message_id": message.message_id,
                "status": "booking_confirmed",
                "booking": {
                    "booking_reference": booking_result.booking_reference,
                    "train_id": booking_result.train_id,
                    "from_station": booking_result.from_station,
                    "to_station": booking_result.to_station,
                    "travel_date": booking_result.travel_date.isoformat(),
                    "seat_class": booking_result.seat_class,
                    "passenger_count": booking_result.passenger_count,
                    "fare": fare_str,
                    "status": booking_result.status,
                },
            },
        )

    elif intent_val == "cancel_booking":
        booking_ref = message.payload.get("booking_reference")
        reason = message.payload.get("reason", "")
        if not booking_ref or not str(booking_ref).strip():
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "message_id": message.message_id,
                    "status": "not_implemented",
                    "intent": "cancel_booking",
                    "detail": "Missing 'booking_reference' in cancel_booking payload.",
                },
            )
        if not reason or not str(reason).strip():
            reason = "No reason provided"

        cancellation_service = CancellationService(db)
        try:
            canc_result = cancellation_service.process_cancellation_request(
                booking_reference=str(booking_ref),
                reason=str(reason),
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "message_id": message.message_id,
                    "status": "cancellation_requested",
                    "cancellation": canc_result,
                },
            )
        except CancellationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported intent '{message.intent}'.",
        )


# ---------------------------------------------------------------------------
# Booking Options & Schedule Discovery
# ---------------------------------------------------------------------------

@app.get(
    "/booking-options",
    tags=["bookings"],
    summary="Retrieve available train schedules and live seat availability for a route and date",
    response_description="List of available train options",
)
async def get_booking_options(
    from_station: str,
    to_station: str,
    travel_date: date,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Query real train schedules from Supabase matching the route and date,
    with dynamically derived available seat counts and fare information.
    """
    from booking.availability import get_schedules_for_route

    options = get_schedules_for_route(
        db=db,
        from_station=from_station,
        to_station=to_station,
        travel_date=travel_date,
    )
    return JSONResponse(status_code=200, content=options)


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
# Cancellation Routes & Admin Review
# ---------------------------------------------------------------------------

class AdminReviewInput(BaseModel):
    decision: str = Field(..., description="APPROVE or REJECT")
    admin_reason: str | None = Field(default=None, description="Optional reasoning from administrator")


@app.get(
    "/cancellations",
    tags=["cancellations"],
    summary="List cancellation requests with optional status filter",
    response_description="List of cancellation request summaries",
    include_in_schema=True,
)
def list_cancellations(
    status: str | None = None,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Query cancellation_requests from database and return case records with
    associated booking details, NLP category, RAG evidence, and AI summary.
    """
    service = CancellationService(db)
    cases = service.list_cancellation_cases(status_filter=status)
    return JSONResponse(status_code=200, content=cases)


@app.get(
    "/cancellations/{case_reference}",
    tags=["cancellations"],
    summary="Retrieve a cancellation request by case reference",
    response_description="Cancellation request details",
    include_in_schema=True,
)
def get_cancellation(
    case_reference: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Query the cancellation_requests table by case_reference.
    """
    service = CancellationService(db)
    cases = service.list_cancellation_cases()
    matched = next((c for c in cases if c["case_reference"].upper() == case_reference.strip().upper()), None)
    if not matched:
        raise HTTPException(status_code=404, detail=f"Cancellation case '{case_reference}' not found.")
    return JSONResponse(status_code=200, content=matched)


@app.post(
    "/internal/cancellations/{case_reference}/review",
    tags=["cancellations"],
    summary="Human-in-the-Loop Admin Review (Approve or Reject)",
    response_description="Adjudication outcome",
    include_in_schema=True,
)
def review_cancellation_endpoint(
    case_reference: str,
    payload: AdminReviewInput,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Execute human administrator review:
    - APPROVE: transitions Booking.status -> CANCELLED and CancellationRequest.status -> APPROVED
    - REJECT: keeps Booking.status as CONFIRMED and transitions CancellationRequest.status -> REJECTED
    """
    service = CancellationService(db)
    try:
        res = service.review_cancellation(
            case_reference=case_reference,
            decision=payload.decision,
            admin_reason=payload.admin_reason,
        )
        return JSONResponse(status_code=200, content=res)
    except CancellationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


class AdminNLPPreviewInput(BaseModel):
    reason: str = Field(..., description="Administrator's proposed rejection explanation")


@app.post(
    "/internal/cancellations/nlp-preview",
    tags=["cancellations"],
    summary="Real-time NLP preview and classification for admin rejection reason",
    response_description="NLP classification, tone assessment, and polished passenger message",
    include_in_schema=True,
)
def preview_admin_rejection_nlp(payload: AdminNLPPreviewInput) -> JSONResponse:
    """
    Analyze proposed administrator rejection explanation using NLP.
    Returns category classification, extracted policy markers, and polite phrasing.
    """
    from cancellation.nlp import analyze_admin_rejection_reason
    analysis = analyze_admin_rejection_reason(payload.reason)
    return JSONResponse(status_code=200, content=analysis)


# ---------------------------------------------------------------------------
# Fraud Review Endpoints (Admin Adjudication)
# ---------------------------------------------------------------------------

@app.get(
    "/internal/fraud-reviews",
    tags=["fraud-review"],
    summary="List fraud review cases with optional status filter",
    response_description="List of fraud review cases",
    include_in_schema=True,
)
def list_fraud_reviews(
    status: str | None = None,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    List fraud review cases for human administrator inspection.
    """
    from fraud.review_service import FraudReviewService
    service = FraudReviewService(db)
    cases = service.list_cases(status_filter=status)
    return JSONResponse(status_code=200, content=cases)


@app.get(
    "/internal/fraud-reviews/{case_reference}",
    tags=["fraud-review"],
    summary="Retrieve a fraud review case by case reference",
    response_description="Fraud review case details",
    include_in_schema=True,
)
def get_fraud_review(
    case_reference: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Query the fraud_reviews table by case_reference.
    """
    from fraud.review_service import FraudCaseNotFoundError, FraudReviewService
    service = FraudReviewService(db)
    cases = service.list_cases()
    matched = next((c for c in cases if c["case_reference"].upper() == case_reference.strip().upper()), None)
    if not matched:
        raise HTTPException(status_code=404, detail=f"Fraud review case '{case_reference}' not found.")
    return JSONResponse(status_code=200, content=matched)


@app.post(
    "/internal/fraud-reviews/{case_reference}/review",
    tags=["fraud-review"],
    summary="Adjudicate a flagged booking (Approve or Reject)",
    response_description="Adjudication outcome",
    include_in_schema=True,
)
def review_fraud_case_endpoint(
    case_reference: str,
    payload: AdminReviewInput,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Execute human administrator fraud review:
    - APPROVE: re-verifies train, schedule, duplicate active tickets, cross-train time conflicts,
      and seat availability (HTTP 409 if seats taken), then confirms booking and creates passenger records.
    - REJECT: transitions FraudReview.status -> REJECTED and creates no booking.
    """
    from fraud.review_service import FraudReviewError, FraudReviewService
    service = FraudReviewService(db)
    try:
        res = service.review_case(
            case_reference=case_reference,
            decision=payload.decision,
            admin_reason=payload.admin_reason,
        )
        return JSONResponse(status_code=200, content=res)
    except SeatsUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (DuplicateActiveTicketError, ConflictingActiveJourneyError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except FraudReviewError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


