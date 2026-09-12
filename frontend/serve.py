"""
frontend/serve.py
-----------------
RailSense AI — Unified Passenger & Booking Web Application Server.

Responsibilities:
1. Serves the rich Victorian Station Intelligence frontend (HTML/CSS/JS).
2. Handles Passenger Chat (/api/chat) with intent & entity extraction,
   producing 'Continue to Booking' prefill actions.
3. Proxies schedule & seat queries (/api/booking-options) to Booking Agent.
4. Provides secure server-side booking submission (/api/bookings/confirm):
   - Signs trusted inter-agent JWT with server-side JWT_SECRET_KEY.
   - Envelopes booking data in AgentMessage schema.
   - Forwards to Central Agent Communication Hub (POST /messages).
   - Sanitizes and translates errors without exposing DB, JWT, or internal traces.
   - NO JWT secrets or database credentials are ever exposed to the browser.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import httpx
import jwt
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

# ---------------------------------------------------------------------------
# Path & Environment Setup
# ---------------------------------------------------------------------------
_CURRENT_DIR = Path(__file__).resolve().parent
_WORKSPACE_ROOT = _CURRENT_DIR.parent
_M3_ROOT = _WORKSPACE_ROOT / "M3-Comunication-Hub&Booking-Agent"

# Load environment variables
for env_file in (_M3_ROOT / ".env", _WORKSPACE_ROOT / ".env"):
    if env_file.is_file():
        load_dotenv(dotenv_path=env_file, override=False)
load_dotenv()

def is_test_environment() -> bool:
    return (
        "PYTEST_CURRENT_TEST" in os.environ
        or os.getenv("TESTING", "").lower() in ("1", "true")
        or any("pytest" in arg.lower() for arg in sys.argv)
    )

if is_test_environment() and os.getenv("USE_LIVE_HUB") != "1":
    HUB_URL = "http://127.0.0.1:19999"
    BOOKING_AGENT_URL = "http://127.0.0.1:19999"
else:
    HUB_URL = os.getenv("AGENT_HUB_URL", "http://localhost:8002").rstrip("/")
    BOOKING_AGENT_URL = os.getenv("BOOKING_AGENT_URL", "http://localhost:8003").rstrip("/")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
HTML_FILE = _CURRENT_DIR / "index.html"

app = FastAPI(
    title="RailSense AI - Passenger Web & Booking Gateway",
    description="Serves passenger chat, booking UI, and secure server-side inter-agent dispatch.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ChatInput(BaseModel):
    message: str = Field(..., min_length=1, description="Passenger user message")
    session_id: str | None = Field(default=None, description="Optional session tracking ID")


from fastapi.exceptions import RequestValidationError


class ConfirmBookingInput(BaseModel):
    from_station: str = Field(default="")
    to_station: str = Field(default="")
    travel_date: str = Field(default="")
    train_id: str = Field(default="")
    seat_class: str = Field(default="")
    passenger_count: int = Field(default=1, ge=1, le=10)
    passenger_email: EmailStr | None = Field(default=None)
    user_id: str | None = Field(default=None)
    passengers: list[dict[str, Any]] | None = Field(default=None)

ConfirmBookingInput.model_rebuild()


class ConfirmCancellationInput(BaseModel):
    booking_reference: str = Field(default="")
    reason: str = Field(default="")


class AdminReviewActionInput(BaseModel):
    decision: str = Field(default="APPROVE")
    admin_reason: str | None = Field(default=None)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"error": "Please complete all booking details."},
    )


# ---------------------------------------------------------------------------
# Intent & Entity Extraction Helper
# ---------------------------------------------------------------------------
KNOWN_STATIONS = [
    "Colombo", "Kandy", "Galle", "Matara", "Badulla",
    "Jaffna", "Anuradhapura", "Peradeniya", "Ella", "Nanu Oya"
]

BOOKING_KEYWORDS = [
    "book", "ticket", "tickets", "reservation", "seats", "seat",
    "need a train", "want a train", "travel to", "going to", "reserve"
]


def extract_booking_intent_and_entities(message: str) -> tuple[bool, dict[str, str]]:
    """
    Detect booking_request intent and extract only the entities actually provided.
    Never invents missing values.
    """
    text = message.strip()
    lowered = text.lower()

    is_booking = any(kw in lowered for kw in BOOKING_KEYWORDS)
    if not is_booking:
        return False, {}

    prefill: dict[str, str] = {}

    # Extract Stations using known station entities to prevent matching stop words
    for s in KNOWN_STATIONS:
        if re.search(rf"\b(?:from|departing(?:\s+from)?)\s+{re.escape(s)}\b", text, re.IGNORECASE):
            prefill["from_station"] = s
        if re.search(rf"\b(?:to|towards)\s+{re.escape(s)}\b", text, re.IGNORECASE):
            prefill["to_station"] = s

    # Extract Date
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if iso_match:
        prefill["travel_date"] = iso_match.group(1)
    else:
        # Match pattern like "3rd December", "3 December", "December 3"
        month_map = {
            "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
            "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
        }
        day_month = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b", lowered)
        month_day = re.search(r"\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})(?:st|nd|rd|th)?\b", lowered)
        
        if day_month:
            d = int(day_month.group(1))
            m = month_map[day_month.group(2)]
            y = 2026 # Active system year
            try:
                prefill["travel_date"] = date(y, m, d).isoformat()
            except ValueError:
                pass
        elif month_day:
            m = month_map[month_day.group(1)]
            d = int(month_day.group(2))
            y = 2026
            try:
                prefill["travel_date"] = date(y, m, d).isoformat()
            except ValueError:
                pass
        elif "tomorrow" in lowered:
            prefill["travel_date"] = (date.today() + timedelta(days=1)).isoformat()
        elif "today" in lowered:
            prefill["travel_date"] = date.today().isoformat()

    return True, prefill


CANCELLATION_KEYWORDS = [
    "cancel", "cancellation", "refund", "cancel booking", "cancel my ticket",
    "drop booking", "cancel reservation"
]


def extract_cancellation_intent_and_entities(message: str) -> tuple[bool, dict[str, str]]:
    """
    Detect cancel_booking intent and extract booking reference and original reason.
    Preserves original passenger reason.
    """
    text = message.strip()
    lowered = text.lower()

    is_canc = any(kw in lowered for kw in CANCELLATION_KEYWORDS)
    if not is_canc:
        return False, {}

    entities: dict[str, str] = {}

    # Extract Booking Reference (RS-XXXXX)
    ref_match = re.search(r"\b(RS-[A-Za-z0-9]{4,10})\b", text, re.IGNORECASE)
    if ref_match:
        entities["booking_reference"] = ref_match.group(1).upper()

    # Extract Reason (preserving exact wording)
    reason_match = re.search(r"\b(?:because|due to|as|reason:)\s+(.+)$", text, re.IGNORECASE)
    if reason_match:
        entities["reason"] = reason_match.group(1).strip()
    else:
        # If no explicit conjunction, strip leading command tokens
        cleaned = re.sub(
            r"^(?:please\s+)?(?:cancel\s+(?:my\s+)?(?:booking|ticket|reservation)?(?:\s+RS-[A-Za-z0-9]{4,10})?)\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        entities["reason"] = cleaned if cleaned else text

    return True, entities


# ---------------------------------------------------------------------------
# Static Web Routes
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def get_index():
    if HTML_FILE.is_file():
        return FileResponse(HTML_FILE)
    raise HTTPException(status_code=404, detail="index.html not found")


@app.get("/booking", include_in_schema=False)
def get_booking_page():
    if HTML_FILE.is_file():
        return FileResponse(HTML_FILE)
    raise HTTPException(status_code=404, detail="index.html not found")


@app.get("/admin", include_in_schema=False)
def get_admin_page():
    if HTML_FILE.is_file():
        return FileResponse(HTML_FILE)
    raise HTTPException(status_code=404, detail="index.html not found")


@app.get("/admin/cancellations", include_in_schema=False)
def get_admin_cancellations_page():
    if HTML_FILE.is_file():
        return FileResponse(HTML_FILE)
    raise HTTPException(status_code=404, detail="index.html not found")


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/chat", tags=["passenger"])
async def chat_endpoint(payload: ChatInput) -> dict[str, Any]:
    """
    Passenger Assistant Chat Endpoint.
    Detects cancel_booking or booking_request intent.
    Returns assistant message and structured action card.
    """
    # 1. Check for Cancellation Intent first
    is_canc, canc_info = extract_cancellation_intent_and_entities(payload.message)
    if is_canc:
        booking_ref = canc_info.get("booking_reference", "")
        reason = canc_info.get("reason", payload.message)
        return {
            "reply": (
                f"I have prepared your cancellation request for booking **{booking_ref or 'Reference Required'}** "
                f"with reason: *\"{reason}\"*. Please review the confirmation card below and click **Send Cancellation Request**."
            ),
            "intent": "cancel_booking",
            "cancellation": {
                "booking_reference": booking_ref,
                "reason": reason,
            },
            "action": {
                "type": "cancellation_confirmation_card",
                "label": "Send Cancellation Request",
                "booking_reference": booking_ref,
                "reason": reason,
            },
        }

    # 2. Check for Booking Request Intent
    is_booking, prefill = extract_booking_intent_and_entities(payload.message)

    if is_booking:
        params = []
        if "from_station" in prefill:
            params.append(f"from={prefill['from_station']}")
        if "to_station" in prefill:
            params.append(f"to={prefill['to_station']}")
        if "travel_date" in prefill:
            params.append(f"date={prefill['travel_date']}")

        query_str = f"?{'&'.join(params)}" if params else ""
        booking_url = f"/booking{query_str}"

        # Generate intelligent contextual assistant reply
        details_list = []
        if "from_station" in prefill:
            details_list.append(f"from **{prefill['from_station']}**")
        if "to_station" in prefill:
            details_list.append(f"to **{prefill['to_station']}**")
        if "travel_date" in prefill:
            details_list.append(f"on **{prefill['travel_date']}**")

        if details_list:
            reply = (
                f"I found your booking request {' '.join(details_list)}. "
                "Click the button below to proceed to the reservation desk with these details pre-filled."
            )
        else:
            reply = (
                "I can certainly help you book a train ticket! "
                "Click the button below to open the booking page and select your stations and date."
            )

        return {
            "reply": reply,
            "intent": "booking_request",
            "prefill": prefill,
            "action": {
                "type": "continue_to_booking",
                "label": "Continue to Booking ➔",
                "url": booking_url,
            },
        }

    # General assistance fallback
    return {
        "reply": (
            "Welcome to RailSense AI. I can assist with train bookings, live schedules, and route inquiries. "
            "For example, try saying: *'I need to book a train from Colombo to Kandy on 3rd December.'*"
        ),
        "intent": "general_inquiry",
        "prefill": {},
        "action": None,
    }


@app.get("/api/booking-options", tags=["booking"])
async def booking_options_proxy(
    from_station: str = Query(..., min_length=1),
    to_station: str = Query(..., min_length=1),
    travel_date: str = Query(..., min_length=1),
) -> JSONResponse:
    """
    Proxy available schedule queries to the authoritative Booking Agent.
    Never invents mock train data.
    """
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(
                f"{BOOKING_AGENT_URL}/booking-options",
                params={
                    "from_station": from_station,
                    "to_station": to_station,
                    "travel_date": travel_date,
                },
            )
            if resp.status_code == 200:
                return JSONResponse(status_code=200, content=resp.json())
            return JSONResponse(status_code=resp.status_code, content=resp.json())
    except (httpx.ConnectError, httpx.TimeoutException):
        # Fallback to direct DB query if booking agent service is not running on separate port
        try:
            sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
            from database.database import SessionLocal
            from booking.availability import get_schedules_for_route
            d = date.fromisoformat(travel_date)
            with SessionLocal() as db:
                options = get_schedules_for_route(db, from_station, to_station, d)
                return JSONResponse(status_code=200, content=options)
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"error": "Booking service is temporarily unavailable."},
            )
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "Booking service is temporarily unavailable."},
        )


@app.post("/api/bookings/confirm", tags=["booking"])
async def confirm_booking_endpoint(req: ConfirmBookingInput) -> JSONResponse:
    """
    Secure Server-Side Booking Submission:
    1. Validates form data.
    2. Generates trusted inter-agent JWT (JWT_SECRET_KEY never leaves server).
    3. Builds AgentMessage envelope (sender: passenger-agent -> receiver: booking-agent).
    4. Posts to Central Agent Communication Hub (/messages).
    5. Translates error responses to clean, user-friendly messages.
    """
    # 1. Validation of required fields
    if not req.from_station.strip() or not req.to_station.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "Please complete all booking details."},
        )
    if not req.travel_date.strip() or not req.train_id.strip() or not req.seat_class.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "Please complete all booking details."},
        )

    # 2. Server-side trusted JWT token generation
    now = datetime.now(timezone.utc)
    token_claims = {
        "sub": "passenger-agent",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=3600)).timestamp()),
    }
    server_jwt = jwt.encode(token_claims, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    # 3. Construct AgentMessage envelope
    message_id = f"MSG-WEB-{uuid.uuid4().hex[:8]}"
    envelope = {
        "message_id": message_id,
        "sender_agent": "passenger-agent",
        "receiver_agent": "booking-agent",
        "intent": "booking_request",
        "auth_token": f"Bearer {server_jwt}",
        "timestamp": now.isoformat(),
        "payload": {
            "from_station": req.from_station.strip(),
            "to_station": req.to_station.strip(),
            "travel_date": req.travel_date.strip(),
            "train_id": req.train_id.strip(),
            "seat_class": req.seat_class.strip(),
            "passenger_count": req.passenger_count,
            "passenger_email": str(req.passenger_email).strip() if req.passenger_email else None,
            "user_id": req.user_id or "guest_passenger",
            "passengers": req.passengers,
        },
    }

    # 4. Dispatch through Communication Hub
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{HUB_URL}/messages",
                json=envelope,
                headers={"Authorization": f"Bearer {server_jwt}"},
            )

        data = resp.json()

        if resp.status_code == 200:
            b_info = data.get("response", {}).get("booking", {})
            if data.get("response", {}).get("status") == "pending_fraud_review" or b_info.get("status") == "PENDING_FRAUD_REVIEW":
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": True,
                        "pending_review": True,
                        "status": "PENDING_FRAUD_REVIEW",
                        "case_reference": b_info.get("case_reference") or data.get("response", {}).get("case_reference"),
                        "risk_level": b_info.get("risk_level") or data.get("response", {}).get("risk_level"),
                        "reasons": b_info.get("reasons") or data.get("response", {}).get("reasons"),
                        "message": "Your booking request requires security review.",
                        "booking": b_info,
                    },
                )
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "booking": {
                        "booking_reference": b_info.get("booking_reference"),
                        "from_station": b_info.get("from_station"),
                        "to_station": b_info.get("to_station"),
                        "travel_date": b_info.get("travel_date"),
                        "train_id": b_info.get("train_id"),
                        "seat_class": b_info.get("seat_class"),
                        "passenger_count": b_info.get("passenger_count"),
                        "fare": b_info.get("fare"),
                        "status": b_info.get("status"),
                    },
                },
            )

        # Handle mapped downstream errors cleanly
        detail_msg = str(data.get("detail", "")).lower()
        if "duplicate_nic_in_booking" in detail_msg:
            return JSONResponse(
                status_code=400,
                content={"error": "Duplicate NIC found in booking. Each passenger must provide a unique NIC."},
            )
        if "duplicate_active_ticket" in detail_msg:
            return JSONResponse(
                status_code=409,
                content={"error": "A passenger already holds a confirmed ticket for this train and date."},
            )
        if "conflicting_active_journey" in detail_msg:
            return JSONResponse(
                status_code=409,
                content={"error": "A passenger already has an active confirmed journey overlapping this time."},
            )
        if "invalid_nic" in detail_msg or "invalid sri lankan nic" in detail_msg:
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid Sri Lankan NIC provided. Must be 9 digits + V/X or 12 digits."},
            )
        if "not enough" in detail_msg or "seats" in detail_msg or resp.status_code == 409:
            return JSONResponse(
                status_code=409,
                content={"error": "Not enough seats are available."},
            )
        if "schedule" in detail_msg or "train" in detail_msg or resp.status_code == 404:
            return JSONResponse(
                status_code=404,
                content={"error": "No train is available for this route/date."},
            )
        if resp.status_code == 422:
            return JSONResponse(
                status_code=400,
                content={"error": "Please complete all booking details."},
            )

        return JSONResponse(
            status_code=503,
            content={"error": "Booking service is temporarily unavailable."},
        )

    except httpx.ConnectError:
        # In case the standalone Hub process is not running, dispatch directly through in-memory BookingService
        try:
            sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
            from database.database import SessionLocal
            from booking.service import BookingService
            from schemas.booking import BookingRequest, PassengerDetail
            from booking.exceptions import (
                ConflictingActiveJourneyError,
                DuplicateActiveTicketError,
                DuplicateNICInBookingError,
                InvalidBookingError,
                ScheduleNotFoundError,
                SeatsUnavailableError,
                TrainNotFoundError,
            )

            passengers_list = None
            if req.passengers:
                passengers_list = [PassengerDetail(**p) for p in req.passengers]

            b_req = BookingRequest(
                from_station=req.from_station.strip(),
                to_station=req.to_station.strip(),
                travel_date=date.fromisoformat(req.travel_date.strip()),
                train_id=req.train_id.strip(),
                seat_class=req.seat_class.strip(),
                passenger_count=req.passenger_count,
                passenger_email=str(req.passenger_email).strip() if req.passenger_email else None,
                user_id=req.user_id or "guest_passenger",
                passengers=passengers_list,
            )
            with SessionLocal() as db:
                service = BookingService(db)
                b_res = service.process_booking(b_req)
                if b_res.status == "PENDING_FRAUD_REVIEW":
                    return JSONResponse(
                        status_code=200,
                        content={
                            "success": True,
                            "pending_review": True,
                            "status": "PENDING_FRAUD_REVIEW",
                            "case_reference": b_res.case_reference,
                            "risk_level": b_res.risk_level,
                            "reasons": b_res.reasons,
                            "message": "Your booking request requires security review.",
                            "booking": {
                                "booking_reference": None,
                                "case_reference": b_res.case_reference,
                                "from_station": b_res.from_station,
                                "to_station": b_res.to_station,
                                "travel_date": b_res.travel_date.isoformat(),
                                "train_id": b_res.train_id,
                                "seat_class": b_res.seat_class,
                                "passenger_count": b_res.passenger_count,
                                "passenger_email": b_res.passenger_email,
                                "fare": f"{b_res.fare:.2f}",
                                "status": "PENDING_FRAUD_REVIEW",
                            },
                        },
                    )
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": True,
                        "booking": {
                            "booking_reference": b_res.booking_reference,
                            "from_station": b_res.from_station,
                            "to_station": b_res.to_station,
                            "travel_date": b_res.travel_date.isoformat(),
                            "train_id": b_res.train_id,
                            "seat_class": b_res.seat_class,
                            "passenger_count": b_res.passenger_count,
                            "passenger_email": b_res.passenger_email,
                            "fare": f"{b_res.fare:.2f}",
                            "status": b_res.status,
                        },
                    },
                )
        except SeatsUnavailableError:
            return JSONResponse(
                status_code=409,
                content={"error": "Not enough seats are available."},
            )
        except (DuplicateActiveTicketError, ConflictingActiveJourneyError) as exc:
            return JSONResponse(
                status_code=409,
                content={"error": str(exc)},
            )
        except (DuplicateNICInBookingError, InvalidBookingError) as exc:
            return JSONResponse(
                status_code=400,
                content={"error": str(exc)},
            )
        except (ScheduleNotFoundError, TrainNotFoundError):
            return JSONResponse(
                status_code=404,
                content={"error": "No train is available for this route/date."},
            )
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"error": "Booking service is temporarily unavailable."},
            )


# ---------------------------------------------------------------------------
# Cancellation API Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/cancellations/confirm", tags=["cancellation"])
async def confirm_cancellation_endpoint(req: ConfirmCancellationInput) -> JSONResponse:
    """
    Secure Server-Side Cancellation Submission:
    1. Validates form data (booking_reference, reason).
    2. Generates trusted inter-agent JWT (JWT_SECRET_KEY never leaves server).
    3. Builds AgentMessage envelope (sender: passenger-agent -> receiver: booking-agent, intent: cancel_booking).
    4. Posts to Central Agent Communication Hub (/messages).
    5. Fallback directly through in-memory CancellationService if Hub process is offline.
    """
    clean_ref = req.booking_reference.strip().upper()
    clean_reason = req.reason.strip()

    if not clean_ref:
        return JSONResponse(
            status_code=400,
            content={"error": "Please provide a valid booking reference."},
        )
    if not clean_reason or len(clean_reason) < 3:
        return JSONResponse(
            status_code=400,
            content={"error": "Please provide a valid cancellation reason (minimum 3 characters)."},
        )

    # Server-side trusted JWT token generation
    now = datetime.now(timezone.utc)
    token_claims = {
        "sub": "passenger-agent",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=3600)).timestamp()),
    }
    server_jwt = jwt.encode(token_claims, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    # Construct AgentMessage envelope
    message_id = f"MSG-CN-{uuid.uuid4().hex[:8]}"
    envelope = {
        "message_id": message_id,
        "sender_agent": "passenger-agent",
        "receiver_agent": "booking-agent",
        "intent": "cancel_booking",
        "auth_token": f"Bearer {server_jwt}",
        "timestamp": now.isoformat(),
        "payload": {
            "booking_reference": clean_ref,
            "reason": clean_reason,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{HUB_URL}/messages",
                json=envelope,
                headers={"Authorization": f"Bearer {server_jwt}"},
            )

        data = resp.json()

        if resp.status_code == 200:
            c_info = data.get("response", {}).get("cancellation", {})
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "cancellation": c_info,
                },
            )

        detail_msg = str(data.get("detail", "")).lower()
        print(f"[Cancellation API] Hub response: status={resp.status_code}, detail='{data.get('detail')}'")

        if "not exist" in detail_msg or "not found" in detail_msg or "404" in detail_msg or resp.status_code == 404:
            return JSONResponse(
                status_code=404,
                content={"error": f"Booking '{clean_ref}' does not exist."},
            )
        if "already cancelled" in detail_msg or "already pending" in detail_msg or "409" in detail_msg or resp.status_code == 409:
            return JSONResponse(
                status_code=409,
                content={"error": f"Booking '{clean_ref}' is already cancelled or has a pending review."},
            )

        err_msg = data.get("detail") or "Cancellation service is temporarily unavailable."
        return JSONResponse(
            status_code=503,
            content={"error": str(err_msg)},
        )

    except (httpx.ConnectError, httpx.TimeoutException):
        # Fallback to direct DB query if hub service is not running on separate port or times out
        try:
            sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
            from database.database import SessionLocal
            from cancellation.service import (
                CancellationService,
                BookingNotFoundError,
                BookingAlreadyCancelledError,
                CancellationAlreadyPendingError,
                CancellationError,
            )

            with SessionLocal() as db:
                service = CancellationService(db)
                c_info = service.process_cancellation_request(
                    booking_reference=clean_ref,
                    reason=clean_reason,
                )
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": True,
                        "cancellation": c_info,
                    },
                )
        except BookingNotFoundError:
            return JSONResponse(
                status_code=404,
                content={"error": f"Booking '{clean_ref}' does not exist."},
            )
        except (BookingAlreadyCancelledError, CancellationAlreadyPendingError) as exc:
            return JSONResponse(
                status_code=409,
                content={"error": str(exc.message)},
            )
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"error": "Cancellation service is temporarily unavailable."},
            )


# ---------------------------------------------------------------------------
# Admin Review API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/admin/cancellations", tags=["admin"])
async def list_admin_cancellations(status: str | None = None) -> JSONResponse:
    """
    List cancellation cases for Admin Dashboard review.
    """
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(
                f"{BOOKING_AGENT_URL}/cancellations",
                params={"status": status} if status else {},
            )
            if resp.status_code == 200:
                return JSONResponse(status_code=200, content=resp.json())
    except Exception:
        pass

    # Direct database fallback
    try:
        sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
        from database.database import SessionLocal
        from cancellation.service import CancellationService
        with SessionLocal() as db:
            service = CancellationService(db)
            cases = service.list_cancellation_cases(status_filter=status)
            return JSONResponse(status_code=200, content=cases)
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Failed to load cancellation cases."})


@app.post("/api/admin/cancellations/{case_reference}/review", tags=["admin"])
async def review_admin_cancellation(
    case_reference: str,
    payload: AdminReviewActionInput,
) -> JSONResponse:
    """
    Execute human administrator review:
    - APPROVE: transitions Booking.status -> CANCELLED and CancellationRequest.status -> APPROVED
    - REJECT: keeps Booking.status as CONFIRMED and transitions CancellationRequest.status -> REJECTED
    """
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{BOOKING_AGENT_URL}/internal/cancellations/{case_reference}/review",
                json={"decision": payload.decision, "admin_reason": payload.admin_reason},
            )
            if resp.status_code == 200:
                return JSONResponse(status_code=200, content=resp.json())
            return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception:
        pass

    # Direct database fallback
    try:
        sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
        from database.database import SessionLocal
        from cancellation.service import CancellationService, CancellationError
        with SessionLocal() as db:
            service = CancellationService(db)
            res = service.review_cancellation(
                case_reference=case_reference,
                decision=payload.decision,
                admin_reason=payload.admin_reason,
            )
            return JSONResponse(status_code=200, content=res)
    except CancellationError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": "Failed to process review decision."})


class AdminNLPPreviewReq(BaseModel):
    reason: str = Field(..., description="Administrator rejection text to analyze")


@app.post("/api/admin/cancellations/nlp-preview", tags=["admin"])
async def preview_cancellation_nlp(payload: AdminNLPPreviewReq) -> JSONResponse:
    """
    Analyze proposed rejection reason with NLP for real-time frontend feedback.
    """
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{BOOKING_AGENT_URL}/internal/cancellations/nlp-preview",
                json={"reason": payload.reason},
            )
            if resp.status_code == 200:
                return JSONResponse(status_code=200, content=resp.json())
    except Exception:
        pass

    # Fallback to direct import
    try:
        sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
        from cancellation.nlp import analyze_admin_rejection_reason
        res = analyze_admin_rejection_reason(payload.reason)
        return JSONResponse(status_code=200, content=res)
    except Exception:
        return JSONResponse(
            status_code=200,
            content={
                "raw_reason": payload.reason,
                "rejection_category": "ADMINISTRATIVE_DISCRETION",
                "category_label": "Administrative Discretion",
                "policy_citations": [],
                "time_references": [],
                "tone": "Standard Administrative Review",
                "polished_explanation": f"Rejected by railway administration: {payload.reason}",
            },
        )


# ---------------------------------------------------------------------------
# Admin Fraud Review Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/admin/fraud-reviews", tags=["admin"])
async def list_admin_fraud_reviews(status: str | None = None) -> JSONResponse:
    """
    List fraud review cases for Admin Console adjudication.
    """
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(
                f"{BOOKING_AGENT_URL}/internal/fraud-reviews",
                params={"status": status} if status else {},
            )
            if resp.status_code == 200:
                return JSONResponse(status_code=200, content=resp.json())
    except Exception:
        pass

    # Direct database fallback
    try:
        sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
        from database.database import SessionLocal
        from fraud.review_service import FraudReviewService
        with SessionLocal() as db:
            service = FraudReviewService(db)
            cases = service.list_cases(status_filter=status)
            return JSONResponse(status_code=200, content=cases)
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Failed to load fraud review cases."})


@app.post("/api/admin/fraud-reviews/{case_reference}/review", tags=["admin"])
async def review_admin_fraud_case(
    case_reference: str,
    payload: AdminReviewActionInput,
) -> JSONResponse:
    """
    Adjudicate a flagged booking (APPROVE or REJECT):
    - APPROVE: Re-checks train active, schedule, seat availability (409 if full),
      and NIC duplicate/conflicts, then confirms ticket.
    - REJECT: Updates FraudReview to REJECTED with reason; no ticket is created.
    """
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{BOOKING_AGENT_URL}/internal/fraud-reviews/{case_reference}/review",
                json={
                    "decision": payload.decision,
                    "admin_reason": payload.admin_reason,
                },
            )
            return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception:
        pass

    # Direct database fallback
    try:
        sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
        from database.database import SessionLocal
        from fraud.review_service import FraudReviewError, FraudReviewService
        from booking.exceptions import (
            ConflictingActiveJourneyError,
            DuplicateActiveTicketError,
            SeatsUnavailableError,
        )

        with SessionLocal() as db:
            service = FraudReviewService(db)
            res = service.review_case(
                case_reference=case_reference,
                decision=payload.decision,
                admin_reason=payload.admin_reason,
            )
            return JSONResponse(status_code=200, content=res)
    except SeatsUnavailableError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})
    except (DuplicateActiveTicketError, ConflictingActiveJourneyError) as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})
    except FraudReviewError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": f"Failed to adjudicate review: {exc}"})


# ---------------------------------------------------------------------------
# CLI Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    print(f"Starting RailSense Unified Frontend on http://localhost:{port}")
    uvicorn.run("serve:app", host="0.0.0.0", port=port, reload=True)
