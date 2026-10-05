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
    RouteMismatchError,
    ScheduleNotFoundError,
    SeatsUnavailableError,
    TrainNotFoundError,
    TrainUnderMaintenanceError,
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
        from database.database import is_test_environment, SessionLocal
        init_db(seed=is_test_environment())
        # Warm up database connection pool
        with SessionLocal() as db:
            import sqlalchemy as sa
            db.execute(sa.text("SELECT 1"))
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

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


# In-memory route options cache with 15-second TTL
_options_cache: dict[tuple[str, str, str], tuple[float, list[dict]]] = {}

def invalidate_options_cache() -> None:
    _options_cache.clear()


@app.get(
    "/booking-options",
    tags=["schedules"],
    summary="Get available train schedules and seat counts for route and date",
)
@app.get(
    "/api/booking-options",
    include_in_schema=False,
)
def get_booking_options(
    from_station: str,
    to_station: str,
    travel_date: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    import time
    t0 = time.time()
    from booking.availability import get_schedules_for_route
    try:
        d = date.fromisoformat(travel_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

    cache_key = (from_station.strip().lower(), to_station.strip().lower(), travel_date.strip())
    now = time.time()
    cached_entry = _options_cache.get(cache_key)
    if cached_entry and (now - cached_entry[0]) < 15.0:
        return JSONResponse(status_code=200, content=cached_entry[1])

    options = get_schedules_for_route(db, from_station, to_station, d)
    _options_cache[cache_key] = (now, options)
    print(f"[get_booking_options] Elapsed: {time.time() - t0:.3f}s for {from_station}->{to_station} on {travel_date}")
    return JSONResponse(status_code=200, content=options)


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
            invalidate_options_cache()
        except (TrainNotFoundError, ScheduleNotFoundError, FareNotFoundError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            )
        except TrainUnderMaintenanceError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            )
        except RouteMismatchError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
                    "ticket_token": booking_result.ticket_token,
                    "train_id": booking_result.train_id,
                    "from_station": booking_result.from_station,
                    "to_station": booking_result.to_station,
                    "travel_date": booking_result.travel_date.isoformat(),
                    "seat_class": booking_result.seat_class,
                    "passenger_count": booking_result.passenger_count,
                    "fare": fare_str,
                    "status": booking_result.status,
                    "hold_token": booking_result.hold_token,
                },
            },
        )

    elif intent_val == "cancel_booking":
        booking_ref = message.payload.get("booking_reference")
        reason = message.payload.get("reason", "")
        reason_category = message.payload.get("reason_category")
        user_id = message.payload.get("user_id")
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
                user_id=user_id,
                reason_category=reason_category,
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




# ---------------------------------------------------------------------------
# Booking Retrieval & Management
# ---------------------------------------------------------------------------

@app.get(
    "/bookings/{booking_reference}",
    tags=["bookings"],
    summary="Retrieve a confirmed or held booking by reference",
    response_description="Booking details",
    include_in_schema=True,
)
async def get_booking(
    booking_reference: str,
    user_id: str | None = None,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Retrieve full booking details for given booking_reference,
    including masked passenger identities and QR e-ticket verification representation.
    """
    from database.models import Booking
    from booking.qr_service import generate_ticket_qr_svg
    clean_ref = booking_reference.strip().upper()
    booking = db.query(Booking).filter(Booking.booking_reference == clean_ref).first()
    if not booking:
        return JSONResponse(
            status_code=501,
            content={"detail": f"GET /bookings/{booking_reference} is not yet implemented or booking not found."},
        )

    if user_id and booking.user_id and booking.user_id not in ("guest_passenger", user_id, "admin"):
        raise HTTPException(status_code=403, detail="Unauthorized access to this booking.")

    qr_svg = generate_ticket_qr_svg(booking.ticket_token) if booking.ticket_token else None

    return JSONResponse(
        status_code=200,
        content={
            "booking_reference": booking.booking_reference,
            "ticket_token": booking.ticket_token,
            "train_id": booking.train.train_id if booking.train else str(booking.train_id),
            "from_station": booking.from_station,
            "to_station": booking.to_station,
            "travel_date": booking.travel_date.isoformat(),
            "seat_class": booking.seat_class,
            "passenger_count": booking.passenger_count,
            "passenger_email": booking.passenger_email,
            "fare": f"{booking.fare:.2f}",
            "status": booking.status.value if hasattr(booking.status, "value") else str(booking.status),
            "created_at": booking.created_at.isoformat() if booking.created_at else None,
            "qr_svg": qr_svg,
        },
    )


# ---------------------------------------------------------------------------
# Seat Holds & Expiring Holds
# ---------------------------------------------------------------------------

from schemas.booking import (
    SeatHoldRequest,
    SeatHoldResponse,
    WaitingListRequest,
    WaitingListResponse,
    TicketVerificationResponse,
)

@app.post(
    "/internal/seat-holds",
    tags=["holds"],
    summary="Create a temporary 5-minute seat hold (Project prototype setting)",
    response_model=SeatHoldResponse,
)
def create_seat_hold_endpoint(
    req: SeatHoldRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    from booking.availability import get_schedule_for_trip
    from booking.lifecycle import create_seat_hold
    try:
        schedule = get_schedule_for_trip(
            db=db,
            train_id=req.train_id,
            from_station=req.from_station,
            to_station=req.to_station,
            travel_date=req.travel_date,
        )
        hold = create_seat_hold(
            db=db,
            schedule_id=schedule.id,
            seat_class=req.seat_class,
            seat_count=req.passenger_count,
            user_id=req.user_id,
            duration_minutes=5,
        )
        return JSONResponse(
            status_code=200,
            content={
                "hold_token": hold.hold_token,
                "expires_at": hold.expires_at.isoformat(),
                "duration_seconds": 300,
                "train_id": req.train_id,
                "seat_class": req.seat_class,
                "seat_count": req.passenger_count,
                "status": hold.status.value if hasattr(hold.status, "value") else str(hold.status),
            },
        )
    except (TrainNotFoundError, ScheduleNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except SeatsUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# FIFO Waiting List
# ---------------------------------------------------------------------------

@app.post(
    "/internal/waiting-list",
    tags=["waiting-list"],
    summary="Enqueue passenger into FIFO waiting list when train is fully booked",
)
def join_waiting_list_endpoint(
    req: WaitingListRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    from booking.availability import get_schedule_for_trip
    from booking.waiting_list import enqueue_waiting_list
    try:
        schedule = get_schedule_for_trip(
            db=db,
            train_id=req.train_id,
            from_station=req.from_station,
            to_station=req.to_station,
            travel_date=req.travel_date,
        )
        entry = enqueue_waiting_list(
            db=db,
            schedule_id=schedule.id,
            seat_class=req.seat_class,
            seat_count=req.passenger_count,
            user_id=req.user_id,
            passenger_email=req.passenger_email,
        )
        return JSONResponse(
            status_code=200,
            content={
                "queue_id": entry.queue_id,
                "position": entry.position,
                "status": entry.status.value if hasattr(entry.status, "value") else str(entry.status),
                "train_id": req.train_id,
                "travel_date": req.travel_date.isoformat(),
                "seat_class": req.seat_class,
                "seat_count": entry.seat_count,
            },
        )
    except (TrainNotFoundError, ScheduleNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get(
    "/internal/waiting-list/{queue_id}",
    tags=["waiting-list"],
    summary="Check position in waiting list queue",
)
def get_waiting_list_status_endpoint(
    queue_id: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    from booking.waiting_list import get_waiting_list_position
    pos_info = get_waiting_list_position(db, queue_id)
    if not pos_info:
        raise HTTPException(status_code=404, detail="Waiting list entry not found.")
    return JSONResponse(status_code=200, content=pos_info)


# ---------------------------------------------------------------------------
# E-Ticket QR Verification
# ---------------------------------------------------------------------------

@app.get(
    "/api/tickets/verify/{ticket_token}",
    tags=["tickets"],
    summary="Live server-side verification of QR e-ticket without exposing raw PII",
)
def verify_ticket_endpoint(
    ticket_token: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    from booking.qr_service import verify_ticket_token
    info = verify_ticket_token(db, ticket_token)
    if not info.get("valid"):
        return JSONResponse(status_code=404, content=info)
    return JSONResponse(status_code=200, content=info)


# ---------------------------------------------------------------------------
# Operation / Mutation Status (Idempotency Lookup)
# ---------------------------------------------------------------------------

@app.get(
    "/operations/status/{idempotency_key}",
    tags=["operations"],
    summary="Check status of an asynchronous or idempotent mutation",
)
def get_operation_status(
    idempotency_key: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    import json
    from database.models import IdempotencyRecord
    rec = db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == idempotency_key).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Operation key not found.")

    resp_content = None
    if rec.response_payload:
        try:
            resp_content = json.loads(rec.response_payload)
        except Exception:
            resp_content = rec.response_payload

    return JSONResponse(
        status_code=200,
        content={
            "idempotency_key": rec.idempotency_key,
            "status": rec.status.value if hasattr(rec.status, "value") else str(rec.status),
            "operation_type": rec.operation_type,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
            "result": resp_content,
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


# ---------------------------------------------------------------------------
# Admin — Train List (for dropdown)
# ---------------------------------------------------------------------------

@app.get(
    "/admin/trains",
    tags=["admin"],
    summary="List active trains for admin dropdown selector",
    include_in_schema=True,
)
@app.get(
    "/api/admin/trains",
    include_in_schema=False,
)
def list_admin_trains(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Return all active trains with id, train_id, train_name, and route
    so the admin dashboard can populate the train filter dropdown.
    """
    from database.models import Train

    # Only the columns the dropdown shows: full rows (with metadata) are about
    # twice as slow to fetch for ~2,900 trains.
    trains = (
        db.query(
            Train.id,
            Train.train_id,
            Train.train_name,
            Train.route,
            Train.origin_station,
            Train.destination_station,
        )
        .filter(Train.active == True)  # noqa: E712
        .order_by(Train.train_id)
        .all()
    )
    return JSONResponse(
        status_code=200,
        content=[
            {
                "id": t.id,
                "train_id": t.train_id,
                "train_name": t.train_name,
                "route": t.route or f"{t.origin_station or ''} → {t.destination_station or ''}".strip(" →"),
                "origin_station": t.origin_station,
                "destination_station": t.destination_station,
            }
            for t in trains
        ],
    )


# ---------------------------------------------------------------------------
# Admin — Booking Manifest (filtered by train + date)
# ---------------------------------------------------------------------------

@app.get(
    "/admin/bookings",
    tags=["admin"],
    summary="Retrieve booked tickets filtered by train and travel date",
    include_in_schema=True,
)
@app.get(
    "/api/admin/bookings",
    include_in_schema=False,
)
def list_admin_bookings(
    train_id: str | None = None,
    travel_date: str | None = None,
    booking_status: str | None = None,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Return a manifest of bookings filtered by train (train_id string) and
    travel_date (YYYY-MM-DD), with optional booking_status filter.

    - travel_date refers to the JOURNEY date (Booking.travel_date), NOT created_at.
    - CANCELLED bookings are always included unless explicitly filtered out.
    - Requires at least one of train_id or travel_date to avoid full-table scans.
    """
    from database.models import Booking, BookingPassenger, Passenger, Train, TrainSchedule

    # Validate travel_date if provided
    parsed_date: date | None = None
    if travel_date:
        try:
            parsed_date = date.fromisoformat(travel_date.strip())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid travel_date format. Expected YYYY-MM-DD.",
            )

    # Require at least one filter to prevent large unindexed dumps
    if not train_id and not parsed_date:
        raise HTTPException(
            status_code=400,
            detail="At least one filter (train_id or travel_date) is required.",
        )

    # Build query with joins
    query = (
        db.query(Booking)
        .join(Train, Booking.train_id == Train.id)
        .join(TrainSchedule, Booking.schedule_id == TrainSchedule.id)
    )

    # Apply train filter (match on string train_id like "1005")
    if train_id:
        clean_tid = train_id.strip()
        train_row = db.query(Train).filter(Train.train_id == clean_tid).first()
        if not train_row:
            raise HTTPException(
                status_code=404,
                detail=f"Train '{clean_tid}' not found.",
            )
        query = query.filter(Booking.train_id == train_row.id)

    # Apply date filter on journey travel_date (NOT created_at)
    if parsed_date:
        query = query.filter(Booking.travel_date == parsed_date)

    # Apply optional status filter
    if booking_status:
        query = query.filter(
            Booking.status == booking_status.upper()
        )

    bookings = query.order_by(Booking.travel_date, Booking.created_at).all()

    results = []
    for b in bookings:
        train = b.train
        schedule = b.schedule

        # Gather passengers from booking_passengers relationship
        passengers_info = []
        for bp in b.booking_passengers:
            p = bp.passenger
            if p:
                passengers_info.append({
                    "full_name": p.full_name or "Unknown",
                    "nic_masked": p.nic_masked,
                })

        # Payment status inference: CANCELLED → REFUNDED if approved, else PAID/PENDING
        canc_req = b.cancellation_request
        if b.status.value == "CANCELLED" and canc_req and canc_req.admin_decision == "APPROVE":
            payment_status = "REFUNDED"
        elif b.status.value in ("CONFIRMED",):
            payment_status = "PAID"
        elif b.status.value in ("HELD", "PENDING_FRAUD_REVIEW"):
            payment_status = "PENDING"
        else:
            payment_status = "UNKNOWN"

        results.append({
            "id": b.id,
            "booking_reference": b.booking_reference,
            "ticket_token": b.ticket_token,
            "passenger_email": b.passenger_email or "",
            "passengers": passengers_info,
            "passenger_count": b.passenger_count,
            "fare": str(b.fare),
            "train_id": train.train_id if train else str(b.train_id),
            "train_name": train.train_name if train else "",
            "route": (train.route or "") if train else "",
            "from_station": b.from_station,
            "to_station": b.to_station,
            "travel_date": b.travel_date.isoformat(),
            "departure_time": schedule.departure_time.strftime("%H:%M") if schedule and schedule.departure_time else "",
            "arrival_time": schedule.arrival_time.strftime("%H:%M") if schedule and schedule.arrival_time else "",
            "seat_class": b.seat_class,
            "status": b.status.value if hasattr(b.status, "value") else str(b.status),
            "payment_status": payment_status,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "cancellation_case": canc_req.case_reference if canc_req else None,
        })

    return JSONResponse(
        status_code=200,
        content={
            "count": len(results),
            "filters": {
                "train_id": train_id,
                "travel_date": travel_date,
                "booking_status": booking_status,
            },
            "bookings": results,
        },
    )


# ---------------------------------------------------------------------------
# Admin Booking Intelligence Chatbot (NLP + IR/RAG + LLM)
# ---------------------------------------------------------------------------

from admin_chat.schemas import AdminChatRequest, AdminChatResponse

@app.post(
    "/admin/chat",
    tags=["admin-chat"],
    summary="Admin Booking Intelligence Assistant (NLP + IR/RAG + LLM)",
    response_model=AdminChatResponse,
)
@app.post(
    "/api/admin/booking-chat",
    tags=["admin-chat"],
    include_in_schema=False,
    response_model=AdminChatResponse,
)
def admin_chat_endpoint(
    req: AdminChatRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Process natural-language administrative questions regarding:
    1. 🛡️ Fraud Review Queue
    2. 🔄 Cancellation Queue
    3. 📋 Schedules & Seat Inventory
    4. 🎫 Booked Tickets — Manifest
    """
    from admin_chat.query_router import AdminChatService
    service = AdminChatService(db)
    response = service.process_chat_message(req)
    return JSONResponse(status_code=200, content=response.model_dump())



