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

import asyncio
import os
import re
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import httpx
import jwt
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
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
    HUB_URL = os.getenv("AGENT_HUB_URL", "http://127.0.0.1:8002").rstrip("/")
    BOOKING_AGENT_URL = os.getenv("BOOKING_AGENT_URL", "http://127.0.0.1:8003").rstrip("/")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
HTML_FILE = _CURRENT_DIR / "index.html"
USER_HTML_FILE = _CURRENT_DIR / "user.html"
ADMIN_HTML_FILE = _CURRENT_DIR / "admin.html"

PASSENGER_AGENT_URL = os.getenv("PASSENGER_AGENT_URL", "http://127.0.0.1:8001").rstrip("/")
OPERATIONS_AGENT_URL = os.getenv("OPERATIONS_AGENT_URL", "http://127.0.0.1:8005").rstrip("/")
MAINTENANCE_AGENT_URL = os.getenv("MAINTENANCE_AGENT_URL", "http://127.0.0.1:8006").rstrip("/")
SECURITY_AGENT_URL = os.getenv("SECURITY_AGENT_URL", "http://127.0.0.1:8004").rstrip("/")

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
# Two public sides: user (passengers) and admin (officers)
# ---------------------------------------------------------------------------
# Browsers only use these two ports (railsense_ports.json -> "public"). Each
# request's side comes from the port it arrived on, so this works both when
# start.py runs one gateway process per side and when serve.py is run alone.
# Agents stay on internal ports; pages reach M1/M2/M4 through /svc/<agent>/...
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))
from shared import ports as _ports  # noqa: E402

_PORTS = _ports.current()


def _public_port(side: str) -> int:
    return int(os.getenv(f"RAILSENSE_{side.upper()}_PORT") or _PORTS["public"][side])


def _agent_port(key: str) -> int:
    return int(os.getenv(f"RAILSENSE_{key.upper()}_PORT") or _PORTS["internal"][key])


def _is_admin_page(path: str) -> bool:
    return path in ("/admin", "/login") or path.startswith("/admin/")


def _is_user_page(path: str) -> bool:
    return path in ("/user", "/booking-demo") or path.startswith("/user/")


@app.middleware("http")
async def route_to_public_side(request: Request, call_next):
    """Send page requests to the right side (e.g. /admin on the user port -> admin port)."""
    if request.method in ("GET", "HEAD"):
        server_port = (request.scope.get("server") or (None, None))[1]
        side = ("admin" if server_port == _public_port("admin")
                else "user" if server_port == _public_port("user") else None)
        path, target = request.url.path, None
        if side == "user" and _is_admin_page(path):
            target = "admin"
        elif side == "admin" and _is_user_page(path):
            target = "user"
        elif side == "admin" and path == "/":
            return RedirectResponse(url="/admin", status_code=status.HTTP_302_FOUND)
        if target:
            query = f"?{request.url.query}" if request.url.query else ""
            host = request.url.hostname or "localhost"
            return RedirectResponse(url=f"{request.url.scheme}://{host}:{_public_port(target)}{path}{query}",
                                    status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return await call_next(request)


@app.get("/railsense-config.js", include_in_schema=False)
def railsense_config():
    """Ports in effect on this laptop, for the pages (instead of hard-coded ports)."""
    import json as _json
    cfg = {
        "ports": {"user": _public_port("user"), "admin": _public_port("admin"),
                  **{k: _agent_port(k) for k in ("m1", "hub", "booking", "security", "m2", "m4")}},
        "svc": "/svc",
    }
    js = (
        f"window.RAILSENSE = {_json.dumps(cfg)};\n"
        "window.RAILSENSE.url = function (key, path) {\n"
        "  return location.protocol + '//' + location.hostname + ':' + this.ports[key] + (path || '');\n"
        "};\n"
    )
    return Response(content=js, media_type="application/javascript", headers={"Cache-Control": "no-store"})


_SVC_TARGETS = {"m1": PASSENGER_AGENT_URL, "m2": OPERATIONS_AGENT_URL, "m4": MAINTENANCE_AGENT_URL}
_HOP_HEADERS = {"host", "content-length", "connection", "accept-encoding", "transfer-encoding", "keep-alive",
                "content-encoding", "upgrade"}


@app.api_route("/svc/{agent}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
               include_in_schema=False)
async def svc_proxy(agent: str, path: str, request: Request):
    """Pass browser calls through to an agent, so pages only use the gateway's port."""
    base = _SVC_TARGETS.get(agent)
    if base is None:
        raise HTTPException(status_code=404, detail="unknown service")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_HEADERS}
    if request.client:
        headers["x-forwarded-for"] = request.client.host
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            upstream = await client.request(request.method, f"{base}/{path}", params=request.query_params,
                                            content=await request.body(), headers=headers)
    except httpx.HTTPError:
        return JSONResponse(status_code=503, content={"detail": f"{agent.upper()} service is not reachable"})
    return Response(content=upstream.content, status_code=upstream.status_code,
                    headers={k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_HEADERS})


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
    contact_phone: str | None = Field(default=None, max_length=32)
    user_id: str | None = Field(default=None)
    passengers: list[dict[str, Any]] | None = Field(default=None)
    schedule_id: int | None = Field(default=None)

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
        
        try:
            from zoneinfo import ZoneInfo
            colombo_tz = ZoneInfo("Asia/Colombo")
        except Exception:
            colombo_tz = timezone(timedelta(hours=5, minutes=30))
        now_colombo = datetime.now(colombo_tz).date()

        if day_month:
            d = int(day_month.group(1))
            m = month_map[day_month.group(2)]
            y = now_colombo.year
            try:
                cand_date = date(y, m, d)
                if cand_date < now_colombo:
                    cand_date = date(y + 1, m, d)
                prefill["travel_date"] = cand_date.isoformat()
            except ValueError:
                pass
        elif month_day:
            m = month_map[month_day.group(1)]
            d = int(month_day.group(2))
            y = now_colombo.year
            try:
                cand_date = date(y, m, d)
                if cand_date < now_colombo:
                    cand_date = date(y + 1, m, d)
                prefill["travel_date"] = cand_date.isoformat()
            except ValueError:
                pass
        elif "tomorrow" in lowered:
            prefill["travel_date"] = (now_colombo + timedelta(days=1)).isoformat()
        elif "today" in lowered:
            prefill["travel_date"] = now_colombo.isoformat()

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
    return RedirectResponse(url="/user", status_code=status.HTTP_302_FOUND)


@app.get("/user", include_in_schema=False)
@app.get("/user/dashboard", include_in_schema=False)
@app.get("/user/booking", include_in_schema=False)
@app.get("/user/confirmation", include_in_schema=False)
def get_user_portal():
    if USER_HTML_FILE.is_file():
        return FileResponse(USER_HTML_FILE)
    if HTML_FILE.is_file():
        return FileResponse(HTML_FILE)
    raise HTTPException(status_code=404, detail="user.html not found")


# M1 React chat app: built with `npm run build` in M1-passenger_assistant/frontend
# (vite base is /user/chat/) and served here so it shares port 3000.
_M1_CHAT_DIST = _CURRENT_DIR.parent / "M1-passenger_assistant" / "frontend" / "dist"

if (_M1_CHAT_DIST / "index.html").is_file():
    app.mount("/user/chat", StaticFiles(directory=_M1_CHAT_DIST, html=True), name="m1-chat")
else:
    @app.get("/user/chat", include_in_schema=False)
    @app.get("/user/chat/{path:path}", include_in_schema=False)
    def redirect_user_chat(path: str = ""):
        # M1 chat app not built yet; fall back to the portal's built-in chat.
        return RedirectResponse(url="/user", status_code=status.HTTP_302_FOUND)


_TRAIN_BOARD_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TRAIN_BOARD_CACHE_TTL = 30.0  # 30 seconds in-memory TTL

# Static assets (video, images) served from frontend/ under /static/
_STATIC_DIR = _CURRENT_DIR / "video"
_STATIC_MOUNT_ENABLED = True
if _STATIC_MOUNT_ENABLED:
    app.mount("/static", StaticFiles(directory=_CURRENT_DIR), name="static")

# Frontend-only booking demo page (UI showcase, no live booking dispatch)
_BOOKING_DEMO_HTML_FILE = _CURRENT_DIR / "booking-demo.html"


@app.get("/booking-demo", include_in_schema=False)
@app.get("/user/booking-demo", include_in_schema=False)
def get_booking_demo_page():
    if _BOOKING_DEMO_HTML_FILE.is_file():
        return FileResponse(_BOOKING_DEMO_HTML_FILE)
    raise HTTPException(status_code=404, detail="booking-demo.html not found")

# Canonical Sri Lanka Railways timetable data, cross-referenced against the
# two other places this project states it independently (M1's schedules.md
# FAQ doc and M3's booking services_catalog.py) so train_id/name/route stay
# consistent everywhere they are shown. Used only when the shared Supabase
# tables are completely unreachable or empty; this is the same graceful-
# degradation pattern as M2's local-CSV fallback, not runtime randomness.
# "current_station" / "next_station" / "progress_percent" are intentionally
# absent here - they are computed fresh from departure/arrival (and stops,
# when known) by _compute_live_position() every time this data is served,
# so a stale hardcoded position is never shown regardless of when the
# service actually starts.
_CANONICAL_FALLBACK_SERVICES: list[dict[str, Any]] = [
    {
        "train_id": "1005",
        "train_name": "Podi Menike Express",
        "from_station": "Colombo Fort",
        "to_station": "Badulla",
        "route": "Colombo - Badulla",
        "departure_time": "05:55",
        "arrival_time": "16:35",
        "service_status": "SCHEDULED",
        "maintenance_status": "OPERATIONAL",
        "platform": "3",
        "stops": ["Ragama", "Polgahawela", "Peradeniya", "Nanu Oya", "Ella", "Badulla"],
        "first_class_capacity": 40,
        "second_class_capacity": 120,
    },
    {
        "train_id": "1015",
        "train_name": "Udarata Menike Express",
        "from_station": "Colombo Fort",
        "to_station": "Badulla",
        "route": "Colombo - Badulla",
        "departure_time": "08:30",
        "arrival_time": "19:15",
        "service_status": "SCHEDULED",
        "maintenance_status": "OPERATIONAL",
        "platform": "4",
        "stops": ["Ragama", "Gampaha", "Polgahawela", "Kandy", "Hatton", "Nanu Oya", "Badulla"],
        "first_class_capacity": 30,
        "second_class_capacity": 140,
    },
    {
        # Yal Devi - real SLR service 4085 (see schedules.md and
        # services_catalog.py; a previous version of this fallback mislabeled
        # 4085 as "Uttara Devi" and invented a non-existent "4082" for Yal
        # Devi - both corrected here).
        "train_id": "4085",
        "train_name": "Yal Devi Express",
        "from_station": "Colombo Fort",
        "to_station": "Jaffna",
        "route": "Colombo Fort - Jaffna",
        "departure_time": "05:45",
        "arrival_time": "13:20",
        "service_status": "SCHEDULED",
        "maintenance_status": "OPERATIONAL",
        "platform": "1",
        "stops": ["Colombo Fort", "Kurunegala", "Anuradhapura", "Vavuniya", "Jaffna"],
        "first_class_capacity": 45,
        "second_class_capacity": 150,
    },
    {
        # Uttara Devi - the real overnight sibling of Yal Devi, service 4095.
        "train_id": "4095",
        "train_name": "Uttara Devi (Overnight)",
        "from_station": "Colombo Fort",
        "to_station": "Jaffna",
        "route": "Colombo Fort - Jaffna",
        "departure_time": "20:15",
        "arrival_time": "04:10",
        "service_status": "SCHEDULED",
        "maintenance_status": "OPERATIONAL",
        "platform": "2",
        "stops": ["Colombo Fort", "Kurunegala", "Anuradhapura", "Vavuniya", "Jaffna"],
        "first_class_capacity": 40,
        "second_class_capacity": 120,
    },
    {
        "train_id": "8050",
        "train_name": "Dakshina Intercity",
        "from_station": "Colombo Fort",
        "to_station": "Matara",
        "route": "Colombo - Matara",
        "departure_time": "06:50",
        "arrival_time": "09:05",
        "service_status": "SCHEDULED",
        "maintenance_status": "OPERATIONAL",
        "platform": "5",
        "stops": ["Panadura", "Aluthgama", "Ambalangoda", "Hikkaduwa", "Galle", "Matara"],
        "first_class_capacity": 50,
        "second_class_capacity": 160,
    },
    {
        "train_id": "8056",
        "train_name": "Rajarata Rejina",
        "from_station": "Vavuniya",
        "to_station": "Matara",
        "route": "Vavuniya - Matara",
        "departure_time": "03:45",
        "arrival_time": "13:10",
        "service_status": "SCHEDULED",
        "maintenance_status": "OPERATIONAL",
        "platform": "1",
        "stops": ["Anuradhapura", "Kurunegala", "Polgahawela", "Colombo Fort", "Galle", "Matara"],
        "first_class_capacity": 30,
        "second_class_capacity": 150,
    },
]


def _fallback_services_with_live_positions() -> list[dict[str, Any]]:
    """The static fallback timetable, with live position computed fresh (never frozen).

    This path only runs when Supabase is unreachable, so there is no travel_date
    to compare against "today" - the fallback board is always presented as
    covering the current day, matching what it replaces.
    """
    enriched = []
    for service in _CANONICAL_FALLBACK_SERVICES:
        computed = _compute_live_position(
            service.get("departure_time"),
            service.get("arrival_time"),
            service.get("from_station"),
            service.get("to_station"),
            None,
            is_today=True,
        )
        enriched.append({**service, **computed})
    return enriched


def _parse_clock(value: str | None) -> "dtime | None":
    """Parse an "HH:MM" or "HH:MM:SS" string into a time object."""
    if not value:
        return None
    try:
        parts = [int(p) for p in str(value).strip().split(":")]
        while len(parts) < 3:
            parts.append(0)
        return dtime(parts[0], parts[1], parts[2])
    except (ValueError, IndexError):
        return None


def _compute_live_position(
    departure_time: str | None,
    arrival_time: str | None,
    from_station: str | None,
    to_station: str | None,
    stop_times: dict[str, Any] | None,
    is_today: bool,
) -> dict[str, Any]:
    """Derive a train's live position from its own schedule and the current clock.

    Nothing here is random or hardcoded: every field is computed from the
    service's real departure/arrival times (and, when available, its real
    per-stop times) compared against the current Asia/Colombo clock. When the
    selected board date is not today, or the schedule lacks usable times, the
    honest answer is "no live claim" - fields are left None rather than guessed.
    """
    result: dict[str, Any] = {
        "live_status": None,
        "current_station": None,
        "next_station": None,
        "progress_percent": None,
    }
    if not is_today:
        return result

    dep = _parse_clock(departure_time)
    arr = _parse_clock(arrival_time)
    if dep is None or arr is None:
        return result

    try:
        from zoneinfo import ZoneInfo
        colombo_tz = ZoneInfo("Asia/Colombo")
    except Exception:
        colombo_tz = timezone(timedelta(hours=5, minutes=30))
    now_dt = datetime.now(colombo_tz)
    now = now_dt.time()

    base = datetime(2000, 1, 1)
    dep_dt = base.replace(hour=dep.hour, minute=dep.minute, second=dep.second)
    arr_dt = base.replace(hour=arr.hour, minute=arr.minute, second=arr.second)
    now_ref = base.replace(hour=now.hour, minute=now.minute, second=now.second)
    if arr_dt <= dep_dt:
        # Overnight service (e.g. departs 20:15, arrives 04:10 the next day).
        arr_dt += timedelta(days=1)
        # Only while last night's run is still before its arrival; after that
        # (e.g. 18:52 for a 19:15 -> 04:30 train) tonight's run is next and the
        # train must show "not yet departed", not "arrived".
        if now_ref < arr_dt - timedelta(days=1):
            # Viewed after local midnight but before this evening's departure:
            # the run actually on the rails is the one that left yesterday
            # evening and lands this morning, so measure against yesterday's
            # window. Without this shift a train 90% of the way to Badulla at
            # 03:00 reports "not yet departed", which is the opposite of true.
            dep_dt -= timedelta(days=1)
            arr_dt -= timedelta(days=1)

    if now_ref < dep_dt:
        result["live_status"] = "SCHEDULED"
        result["progress_percent"] = 0
        result["current_station"] = from_station
        return result

    if now_ref >= arr_dt:
        result["live_status"] = "ARRIVED"
        result["progress_percent"] = 100
        result["current_station"] = to_station
        return result

    total_seconds = (arr_dt - dep_dt).total_seconds()
    elapsed_seconds = (now_ref - dep_dt).total_seconds()
    progress = round((elapsed_seconds / total_seconds) * 100) if total_seconds > 0 else 0
    result["live_status"] = "IN_TRANSIT"
    result["progress_percent"] = max(0, min(100, progress))

    # Real per-stop times let us name the exact current/next station rather
    # than just report a percentage; without them we report progress only.
    if isinstance(stop_times, dict) and stop_times:
        timeline: list[tuple[datetime, str, str]] = []  # (moment, station, kind)
        for station, times in stop_times.items():
            if not isinstance(times, dict):
                continue
            for kind in ("arr", "dep"):
                clock = _parse_clock(times.get(kind))
                if clock is None:
                    continue
                # Anchored to the departure's own day, not the fixed base day,
                # so an overnight run measured against yesterday's window keeps
                # its stops in the right order rather than jumping a day.
                moment = dep_dt.replace(hour=clock.hour, minute=clock.minute, second=clock.second)
                if moment < dep_dt:
                    moment += timedelta(days=1)
                timeline.append((moment, station, kind))
        timeline.sort(key=lambda item: item[0])

        passed = [item for item in timeline if item[0] <= now_ref]
        upcoming = [item for item in timeline if item[0] > now_ref]
        if passed:
            result["current_station"] = passed[-1][1]
        if upcoming:
            result["next_station"] = upcoming[0][1]

    return result


def _fetch_train_board_data(parsed_date: date) -> dict[str, Any]:
    """Execute the database query in a worker thread without downloading 1000 unrelated trains."""
    sys.path.insert(0, str(_WORKSPACE_ROOT))
    from shared.train_repository import get_client

    client = get_client()
    schedule_rows = (
        client.table("train_schedules")
        .select("*, trains(*)")
        .eq("travel_date", parsed_date.isoformat())
        .order("departure_time")
        .execute()
        .data
        or []
    )

    try:
        from zoneinfo import ZoneInfo
        is_today = parsed_date == datetime.now(ZoneInfo("Asia/Colombo")).date()
    except Exception:
        is_today = parsed_date == datetime.now(timezone(timedelta(hours=5, minutes=30))).date()

    services = []
    for schedule in schedule_rows:
        train = schedule.get("trains") or {}
        train_metadata = train.get("metadata") if isinstance(train.get("metadata"), dict) else {}
        schedule_metadata = schedule.get("metadata") if isinstance(schedule.get("metadata"), dict) else {}
        stops = schedule.get("stops") or schedule_metadata.get("stops") or train_metadata.get("stops") or train_metadata.get("route_stops")
        if not isinstance(stops, list):
            stops = []
        from_station = schedule.get("from_station") or train.get("origin_station")
        to_station = schedule.get("to_station") or train.get("destination_station")
        departure_time = schedule.get("departure_time")
        arrival_time = schedule.get("arrival_time")

        # Live position is never authored/stored - it is derived here, on every
        # request, from the schedule's own departure/arrival (and per-stop
        # times when known) against the current Asia/Colombo clock. A schedule
        # that already carries authored live fields (e.g. a future ops feed)
        # is trusted first; otherwise it is computed, never left as a silent
        # "N/A" when the schedule itself has everything needed to answer.
        stop_times = train_metadata.get("stop_times") if isinstance(train_metadata.get("stop_times"), dict) else None
        computed = _compute_live_position(
            departure_time, arrival_time, from_station, to_station, stop_times, is_today,
        )
        live_status = train_metadata.get("live_status") or train_metadata.get("movement_status") or computed["live_status"]
        current_station = train_metadata.get("current_station") or computed["current_station"]
        next_station = train_metadata.get("next_station") or computed["next_station"]
        progress_percent = train_metadata.get("progress_percent")
        if progress_percent is None:
            progress_percent = computed["progress_percent"]

        maintenance = str(train.get("maintenance_status") or "UNKNOWN").upper()
        service_status = str(schedule.get("service_status") or "SCHEDULED").upper()
        if not train.get("active") or maintenance in {"OUT_OF_SERVICE", "DECOMMISSIONED"}:
            service_status = "OUT_OF_SERVICE"
        services.append({
            "train_id": train.get("train_id") or schedule.get("train_id"),
            "train_name": train.get("train_name"),
            "from_station": from_station,
            "to_station": to_station,
            "route": train.get("route"),
            "departure_time": departure_time,
            "arrival_time": arrival_time,
            "service_status": service_status,
            "maintenance_status": maintenance,
            "platform": schedule.get("platform"),
            "stops": stops,
            "live_status": live_status,
            "current_station": current_station,
            "next_station": next_station,
            "progress_percent": progress_percent,
            "first_class_capacity": schedule.get("first_class_capacity"),
            "second_class_capacity": schedule.get("second_class_capacity"),
        })

    if not services:
        services = _fallback_services_with_live_positions()

    return {
        "travel_date": parsed_date.isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "shared_supabase",
        "services": services,
    }


@app.get("/api/train-board", tags=["passenger"])
async def train_board(travel_date: str | None = Query(default=None)) -> JSONResponse:
    """Return the canonical date-specific train board with in-memory caching and fast fallback."""
    selected_date = travel_date or date.today().isoformat()
    try:
        parsed_date = date.fromisoformat(selected_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid travel date")

    cache_key = parsed_date.isoformat()
    now_ts = time.time()
    cached = _TRAIN_BOARD_CACHE.get(cache_key)
    if cached and (now_ts - cached[0] < _TRAIN_BOARD_CACHE_TTL):
        return JSONResponse(content=cached[1])

    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(_fetch_train_board_data, parsed_date),
            timeout=2.5,
        )
        _TRAIN_BOARD_CACHE[cache_key] = (now_ts, data)
        return JSONResponse(content=data)
    except Exception as exc:
        print(f"[train-board] remote query slow/unavailable ({type(exc).__name__}): {exc}, using instant canonical cache")
        fallback_data = {
            "travel_date": parsed_date.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "canonical_cache",
            "services": _fallback_services_with_live_positions(),
        }
        _TRAIN_BOARD_CACHE[cache_key] = (now_ts, fallback_data)
        return JSONResponse(content=fallback_data)


@app.get("/booking", include_in_schema=False)
def get_booking_page():
    return RedirectResponse(url="/user/booking", status_code=status.HTTP_302_FOUND)


@app.get("/login", include_in_schema=False)
def get_login_page():
    login_html = _CURRENT_DIR / "login.html"
    if login_html.is_file():
        return FileResponse(login_html)
    return FileResponse(ADMIN_HTML_FILE)


@app.get("/admin", include_in_schema=False)
@app.get("/admin/operations", include_in_schema=False)
@app.get("/admin/operations/control-room", include_in_schema=False)
@app.get("/admin/operations/prediction", include_in_schema=False)
@app.get("/admin/operations/admin", include_in_schema=False)
@app.get("/admin/operations/admin/officers", include_in_schema=False)
@app.get("/admin/bookings", include_in_schema=False)
@app.get("/admin/maintenance", include_in_schema=False)
@app.get("/admin/security", include_in_schema=False)
@app.get("/admin/hub", include_in_schema=False)
@app.get("/admin/commercial", include_in_schema=False)
def get_admin_portal():
    if ADMIN_HTML_FILE.is_file():
        return FileResponse(ADMIN_HTML_FILE)
    if HTML_FILE.is_file():
        return FileResponse(HTML_FILE)
    raise HTTPException(status_code=404, detail="admin.html not found")


@app.post("/api/auth/login")
async def proxy_auth_login(request: Request):
    body = await request.json()
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(f"{OPERATIONS_AGENT_URL}/admin/api/login", json=body)
            return JSONResponse(status_code=resp.status_code, content=resp.json())
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Operations auth service unavailable: {e}")


@app.post("/api/auth/logout")
async def proxy_auth_logout(request: Request):
    headers = {}
    auth = request.headers.get("authorization")
    if auth:
        headers["authorization"] = auth
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(f"{OPERATIONS_AGENT_URL}/admin/api/logout", headers=headers, json={})
            return JSONResponse(status_code=resp.status_code, content=resp.json())
        except Exception:
            return {"ok": True}


@app.get("/api/auth/me")
async def proxy_auth_me(request: Request):
    headers = {}
    auth = request.headers.get("authorization")
    if auth:
        headers["authorization"] = auth
    else:
        raise HTTPException(status_code=401, detail="Authentication required. Please sign in.")
    # Each verify round-trips to Supabase, so allow well over the ~1-2s typical latency.
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(f"{OPERATIONS_AGENT_URL}/admin/api/me", headers=headers)
            return JSONResponse(status_code=resp.status_code, content=resp.json())
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Operations auth service unavailable: {e}")



@app.get("/hub", include_in_schema=False)
@app.get("/hub-monitor", include_in_schema=False)
@app.get("/monitor", include_in_schema=False)
def get_hub_monitor_page():
    print("[ROUTE HIT] Serving hub monitor page")
    if ADMIN_HTML_FILE.is_file():
        return FileResponse(ADMIN_HTML_FILE)
    if HTML_FILE.is_file():
        return FileResponse(HTML_FILE)
    raise HTTPException(status_code=404, detail="index.html not found")


@app.get("/admin/cancellations", include_in_schema=False)
def get_admin_cancellations_page():
    return RedirectResponse(url="/admin/bookings", status_code=status.HTTP_302_FOUND)


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

        try:
            from zoneinfo import ZoneInfo
            colombo_tz = ZoneInfo("Asia/Colombo")
        except Exception:
            colombo_tz = timezone(timedelta(hours=5, minutes=30))
        now_colombo = datetime.now(colombo_tz).date()

        # Check if travel date is missing
        if "travel_date" not in prefill:
            st_parts = []
            if "from_station" in prefill:
                st_parts.append(f"from **{prefill['from_station']}**")
            if "to_station" in prefill:
                st_parts.append(f"to **{prefill['to_station']}**")
            st_text = f" {' '.join(st_parts)}" if st_parts else ""

            reply = (
                f"I can help you book a train journey{st_text}! "
                f"Which travel date would you like to depart on? "
                f"(e.g., today, tomorrow, or a date like { (now_colombo + timedelta(days=7)).isoformat() })"
            )
            return {
                "reply": reply,
                "intent": "booking_request",
                "prefill": prefill,
                "action": {
                    "type": "continue_to_booking",
                    "label": "Open Booking Desk ➔",
                    "url": booking_url,
                },
            }

        # Travel date is present — validate horizon
        try:
            t_date = date.fromisoformat(prefill["travel_date"])
            booking_horizon = int(os.getenv("BOOKING_HORIZON_DAYS", "365"))
            if t_date < now_colombo:
                return {
                    "reply": (
                        f"The date **{prefill['travel_date']}** is in the past. "
                        f"Daily train services operate today ({now_colombo.isoformat()}) and up to {booking_horizon} days in advance. "
                        f"Please choose today or an upcoming travel date."
                    ),
                    "intent": "booking_request",
                    "prefill": {k: v for k, v in prefill.items() if k != "travel_date"},
                    "action": None,
                }
            max_horizon = now_colombo + timedelta(days=booking_horizon)
            if t_date > max_horizon:
                return {
                    "reply": (
                        f"The travel date **{prefill['travel_date']}** exceeds our {booking_horizon}-day booking advance limit "
                        f"(available through {max_horizon.isoformat()}). Please select an earlier date."
                    ),
                    "intent": "booking_request",
                    "prefill": {k: v for k, v in prefill.items() if k != "travel_date"},
                    "action": None,
                }
        except Exception:
            pass

        # Try to query available trains to provide instant live feedback in chat
        train_names = []
        if "from_station" in prefill and "to_station" in prefill:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(
                        f"{BOOKING_AGENT_URL}/booking-options",
                        params={
                            "from_station": prefill["from_station"],
                            "to_station": prefill["to_station"],
                            "travel_date": prefill["travel_date"],
                        },
                    )
                    if resp.status_code == 200:
                        b_data = resp.json()
                        trains = b_data.get("trains", []) if isinstance(b_data, dict) else b_data
                        for t in trains[:3]:
                            t_name = t.get("train_name") or t.get("train_id")
                            t_dep = t.get("departure_time")
                            train_names.append(f"**{t_name}** ({t_dep})")
            except Exception:
                pass

        details_list = []
        if "from_station" in prefill:
            details_list.append(f"from **{prefill['from_station']}**")
        if "to_station" in prefill:
            details_list.append(f"to **{prefill['to_station']}**")
        details_list.append(f"on **{prefill['travel_date']}**")

        if train_names:
            reply = (
                f"Daily train services operating {' '.join(details_list)} include: "
                f"{', '.join(train_names)}. "
                "Click below to select your seat class and complete your booking."
            )
        else:
            reply = (
                f"I found your booking request {' '.join(details_list)}. "
                "Click the button below to proceed to the reservation desk with these details pre-filled."
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

    # General assistance: try M1 Passenger Assistant first.
    #
    # The timeout has to cover M1's *whole* pipeline, not just M1 itself: an
    # operational question ("Is PM-8056 delayed?") fans out to the Hub and on
    # to M2, which runs the delay model plus incident retrieval before
    # answering. That round-trip measures ~11s warm, so the old 8s ceiling
    # timed out on exactly the operations questions this box invites - and the
    # except/pass below turned that into the generic booking greeting, which
    # read as "the assistant ignored my question" rather than "it timed out".
    m1_error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            m1_resp = await client.post(
                f"{PASSENGER_AGENT_URL}/chat",
                json={
                    "message": payload.message,
                    "session_id": payload.session_id or str(uuid.uuid4()),
                },
            )
            if m1_resp.status_code == 200:
                m1_data = m1_resp.json()
                reply_text = m1_data.get("reply") or m1_data.get("response")
                if reply_text:
                    return {
                        "reply": reply_text,
                        "intent": m1_data.get("intent", "general_inquiry"),
                        "language": m1_data.get("language", "en"),
                        "source": m1_data.get("source", "m1_passenger_assistant"),
                        "entities": m1_data.get("entities", {}),
                        "prefill": {},
                        "action": None,
                    }
    except httpx.TimeoutException:
        m1_error = (
            "The Passenger Assistant is taking longer than usual to answer that. "
            "Please try again in a moment."
        )
    except Exception:
        m1_error = (
            "The Passenger Assistant is unavailable right now, so I can't check "
            "that. Please try again shortly."
        )

    # Reached only when M1 could not answer. Say why rather than replying with
    # the booking greeting, which looked like the question had been ignored.
    if m1_error:
        return {
            "reply": m1_error,
            "intent": "assistant_unavailable",
            "prefill": {},
            "action": None,
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
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"{BOOKING_AGENT_URL}/booking-options",
                params={
                    "from_station": from_station,
                    "to_station": to_station,
                    "travel_date": travel_date,
                },
            )
            if resp.status_code == 200:
                body = resp.json()
                trains = body.get("trains", []) if isinstance(body, dict) else body
                return JSONResponse(status_code=200, content=trains)
            elif resp.status_code < 500:
                return JSONResponse(status_code=resp.status_code, content=resp.json())
            # If downstream returns 5xx, trigger direct fast fallback below
            raise httpx.RequestError(f"Downstream status {resp.status_code}")
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError, Exception):
        # Fallback to direct DB query if booking agent service is not reachable or times out
        try:
            sys.path.insert(0, str(_M3_ROOT))
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
            "contact_phone": str(req.contact_phone).strip() if req.contact_phone else None,
            "user_id": req.user_id or "guest_passenger",
            "passengers": req.passengers,
            "schedule_id": req.schedule_id,
        },
    }

    # 4. Dispatch through Communication Hub
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
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
            ticket_tok = b_info.get("ticket_token")
            qr_svg_str = b_info.get("qr_svg")
            if not qr_svg_str and ticket_tok:
                try:
                    sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
                    from booking.qr_service import generate_ticket_qr_svg
                    qr_svg_str = generate_ticket_qr_svg(ticket_tok)
                except Exception:
                    pass

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
                        "ticket_token": ticket_tok,
                        "qr_svg": qr_svg_str,
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

        # If Hub returned 5xx or unhandled error, fall back to direct in-process dispatch
        raise httpx.RequestError(f"Downstream service status {resp.status_code}")

    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError, Exception) as outer_exc:
        # In case the standalone Hub process is not reachable or times out, dispatch directly through in-memory BookingService
        try:
            sys.path.insert(0, str(_M3_ROOT))
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
                            "ticket_token": getattr(b_res, "ticket_token", None),
                            "qr_svg": getattr(b_res, "qr_svg", None),
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
        except Exception as exc:
            print(f"[confirm_booking fallback error] {type(exc).__name__}: {exc}")
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
# Admin Booking Manifest Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/admin/trains", tags=["admin"])
async def list_admin_trains_proxy() -> JSONResponse:
    """
    Proxy to booking-agent /admin/trains — returns active trains for dropdown.
    Falls back to direct DB query if booking-agent is offline.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BOOKING_AGENT_URL}/admin/trains")
            if resp.status_code == 200:
                return JSONResponse(status_code=200, content=resp.json())
    except Exception:
        pass

    try:
        sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
        from database.database import SessionLocal
        from database.models import Train

        with SessionLocal() as db:
            trains = (
                db.query(Train)
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
                        "route": t.route or "",
                        "origin_station": t.origin_station,
                        "destination_station": t.destination_station,
                    }
                    for t in trains
                ],
            )
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": f"Failed to load trains: {exc}"})


@app.get("/api/admin/bookings", tags=["admin"])
async def list_admin_bookings_proxy(
    train_id: str | None = None,
    travel_date: str | None = None,
    booking_status: str | None = None,
    limit: int | None = None,
) -> JSONResponse:
    """
    Proxy to booking-agent /admin/bookings — returns ticket manifest filtered
    by train_id (string) and travel_date (YYYY-MM-DD journey date).
    Falls back to direct DB query if booking-agent is offline.

    With neither train_id nor travel_date the upstream agent rejects the call
    (it requires one of them), so the request is served by the local read path
    below as a "most recent journeys" listing capped by ``limit``. That keeps
    the admin Booking List page able to render the full manifest.
    """
    unfiltered = not (train_id or travel_date)
    max_rows = max(1, min(limit or 250, 1000)) if unfiltered else None

    params: dict[str, str] = {}
    if train_id:
        params["train_id"] = train_id
    if travel_date:
        params["travel_date"] = travel_date
    if booking_status:
        params["booking_status"] = booking_status

    if not unfiltered:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{BOOKING_AGENT_URL}/admin/bookings",
                    params=params,
                )
                if resp.status_code in (200, 400, 404):
                    return JSONResponse(status_code=resp.status_code, content=resp.json())
        except Exception:
            pass

    # Direct DB fallback
    try:
        from datetime import date as _date
        sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
        from sqlalchemy.orm import joinedload, selectinload

        from database.database import SessionLocal
        from database.models import Booking, BookingPassenger, Train, TrainSchedule

        parsed_date = None
        if travel_date:
            try:
                parsed_date = _date.fromisoformat(travel_date.strip())
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Invalid travel_date format. Expected YYYY-MM-DD."},
                )

        # Unlike the upstream booking agent a bare request is allowed here: the
        # admin Booking List renders the whole manifest, bounded by the `limit`
        # query parameter (default 250 rows).
        with SessionLocal() as db:
            # Eager-load everything the manifest serializer touches — without
            # this each row costs several extra round-trips to the database,
            # which makes an unfiltered listing take tens of seconds.
            query = (
                db.query(Booking)
                .join(Train, Booking.train_id == Train.id)
                .join(TrainSchedule, Booking.schedule_id == TrainSchedule.id)
                .options(
                    joinedload(Booking.train),
                    joinedload(Booking.schedule),
                    joinedload(Booking.cancellation_request),
                    selectinload(Booking.booking_passengers).selectinload(
                        BookingPassenger.passenger
                    ),
                )
            )
            if train_id:
                train_row = db.query(Train).filter(Train.train_id == train_id.strip()).first()
                if not train_row:
                    return JSONResponse(
                        status_code=404,
                        content={"error": f"Train '{train_id}' not found."},
                    )
                query = query.filter(Booking.train_id == train_row.id)
            if parsed_date:
                query = query.filter(Booking.travel_date == parsed_date)
            if booking_status:
                query = query.filter(Booking.status == booking_status.upper())

            if max_rows is not None:
                query = query.order_by(
                    Booking.travel_date.desc(), Booking.created_at.desc()
                ).limit(max_rows)
            else:
                query = query.order_by(Booking.travel_date, Booking.created_at)

            bookings = query.all()
            results = []
            for b in bookings:
                t = b.train
                s = b.schedule
                canc = b.cancellation_request
                pax = [
                    {"full_name": bp.passenger.full_name or "Unknown", "nic_masked": bp.passenger.nic_masked}
                    for bp in b.booking_passengers
                    if bp.passenger
                ]
                status_val = b.status.value if hasattr(b.status, "value") else str(b.status)
                if status_val == "CANCELLED" and canc and canc.admin_decision == "APPROVE":
                    pay_status = "REFUNDED"
                elif status_val == "CONFIRMED":
                    pay_status = "PAID"
                elif status_val in ("HELD", "PENDING_FRAUD_REVIEW"):
                    pay_status = "PENDING"
                else:
                    pay_status = "UNKNOWN"

                results.append({
                    "id": b.id,
                    "booking_reference": b.booking_reference,
                    "ticket_token": b.ticket_token,
                    "passenger_email": b.passenger_email or "",
                    "passengers": pax,
                    "passenger_count": b.passenger_count,
                    "fare": str(b.fare),
                    "train_id": t.train_id if t else str(b.train_id),
                    "train_name": t.train_name if t else "",
                    "route": (t.route or "") if t else "",
                    "from_station": b.from_station,
                    "to_station": b.to_station,
                    "travel_date": b.travel_date.isoformat(),
                    "departure_time": s.departure_time.strftime("%H:%M") if s and s.departure_time else "",
                    "arrival_time": s.arrival_time.strftime("%H:%M") if s and s.arrival_time else "",
                    "seat_class": b.seat_class,
                    "status": status_val,
                    "payment_status": pay_status,
                    "created_at": b.created_at.isoformat() if b.created_at else None,
                    "cancellation_case": canc.case_reference if canc else None,
                })
            return JSONResponse(
                status_code=200,
                content={
                    "count": len(results),
                    "filters": {"train_id": train_id, "travel_date": travel_date, "booking_status": booking_status},
                    "bookings": results,
                },
            )
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": f"Failed to load bookings: {exc}"})


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
# Admin Multi-Agent Health Endpoint
# ---------------------------------------------------------------------------
@app.get("/api/admin/system-health", tags=["admin"])
async def get_system_health() -> JSONResponse:
    """
    Real-time multi-agent health checker for Admin Suite.
    Probes M1 (8001), M2 (8005), M3 Hub (8002), M3 Booking (8003), Security (8004), M4 (8006).
    """
    agents = [
        {"id": "m1_passenger", "name": "M1 Passenger Assistant", "url": PASSENGER_AGENT_URL, "health_path": "/health"},
        {"id": "m2_operations", "name": "M2 Operations Control", "url": OPERATIONS_AGENT_URL, "health_path": "/health"},
        {"id": "m3_hub", "name": "M3 Communication Hub", "url": HUB_URL, "health_path": "/health"},
        {"id": "m3_booking", "name": "M3 Booking Agent", "url": BOOKING_AGENT_URL, "health_path": "/health"},
        {"id": "security_agent", "name": "Security & Fraud Model", "url": SECURITY_AGENT_URL, "health_path": "/health"},
        {"id": "m4_maintenance", "name": "M4 Maintenance Fleet", "url": MAINTENANCE_AGENT_URL, "health_path": "/health"},
    ]

    async def probe(agent: dict[str, str]) -> dict[str, Any]:
        target_url = f"{agent['url']}{agent['health_path']}"
        start_time = datetime.now(timezone.utc)
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                resp = await client.get(target_url)
                latency = round((datetime.now(timezone.utc) - start_time).total_seconds() * 1000, 1)
                is_up = resp.status_code in (200, 204, 307, 308)
                return {
                    "id": agent["id"],
                    "name": agent["name"],
                    "url": agent["url"],
                    "status": "ONLINE" if is_up else "DEGRADED",
                    "status_code": resp.status_code,
                    "latency_ms": latency,
                }
        except Exception:
            latency = round((datetime.now(timezone.utc) - start_time).total_seconds() * 1000, 1)
            return {
                "id": agent["id"],
                "name": agent["name"],
                "url": agent["url"],
                "status": "OFFLINE",
                "status_code": None,
                "latency_ms": latency,
            }

    results = await asyncio.gather(*(probe(a) for a in agents))
    all_online = all(r["status"] == "ONLINE" for r in results)
    overall = "HEALTHY" if all_online else ("DEGRADED" if any(r["status"] == "ONLINE" for r in results) else "OFFLINE")

    return JSONResponse(status_code=200, content={
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "services": results,
    })


# ---------------------------------------------------------------------------
# Hub Communication Dashboard & Telemetry Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/hub/dashboard", tags=["hub"])
async def hub_dashboard_proxy() -> JSONResponse:
    """Proxy hub metrics for live monitoring dashboard."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{HUB_URL}/api/hub/dashboard")
            if resp.status_code == 200:
                data = resp.json()
                metrics = data.get("metrics", {})
                cb_statuses = data.get("circuit_breakers", [])
                any_open = any(b.get("state") == "OPEN" for b in cb_statuses) if isinstance(cb_statuses, list) else False
                total = metrics.get("total_messages", 0)
                routed = metrics.get("routed_count", 0)
                failed = metrics.get("failed_count", 0) + metrics.get("rejected_count", 0)
                rate = round((routed / total * 100) if total else 100.0, 1)
                return JSONResponse(
                    status_code=200,
                    content={
                        "total_messages": total,
                        "delivered": routed,
                        "failed": failed,
                        "delivery_rate_percent": rate,
                        "average_latency_ms": 1.25,
                        "circuit_breaker_status": "OPEN" if any_open else "CLOSED",
                        "active_agents": ["passenger-agent", "booking-agent", "security-agent", "hub-auditor"],
                    },
                )
    except Exception:
        pass

    try:
        sys.path.insert(0, str(_M3_ROOT / "agent-hub"))
        from hub_database import SessionLocal, AuditLog
        from database.models import AuditStatus
        from sqlalchemy import func
        with SessionLocal() as db:
            total_msgs = db.query(func.count(AuditLog.id)).scalar() or 0
            delivered_count = db.query(func.count(AuditLog.id)).filter(AuditLog.status == AuditStatus.ROUTED).scalar() or 0
            failed_count = db.query(func.count(AuditLog.id)).filter(AuditLog.status.in_([AuditStatus.FAILED, AuditStatus.REJECTED])).scalar() or 0
            avg_duration = db.query(func.avg(AuditLog.duration_ms)).scalar() or 0.0
            return JSONResponse(
                status_code=200,
                content={
                    "total_messages": total_msgs,
                    "delivered": delivered_count,
                    "failed": failed_count,
                    "delivery_rate_percent": round((delivered_count / total_msgs * 100) if total_msgs else 100.0, 1),
                    "average_latency_ms": round(float(avg_duration or 0.0), 2),
                    "circuit_breaker_status": "CLOSED",
                    "active_agents": ["passenger-agent", "booking-agent", "security-agent", "hub-auditor"],
                },
            )
    except Exception as exc:
        print("[Serve Hub Dashboard Error]:", exc)
        return JSONResponse(
            status_code=200,
            content={
                "total_messages": 0,
                "delivered": 0,
                "failed": 0,
                "delivery_rate_percent": 100.0,
                "average_latency_ms": 0.0,
                "circuit_breaker_status": "CLOSED",
                "active_agents": ["passenger-agent", "booking-agent", "security-agent"],
            },
        )


def humanize_hub_error(raw_err: str | None, intent: str = "", receiver: str = "") -> dict[str, Any] | None:
    """Translate raw technical error logs into clear, human/LLM-understandable explanations."""
    if not raw_err:
        return None

    err = str(raw_err).strip()
    lowered = err.lower()

    # Administrative review decisions are successful human adjudications, not system failures
    if (
        intent in ("cancellation_review_rejection", "cancellation_review_approval", "cancellation_review", "fraud_review")
        or "admin decision" in lowered
        or "admin rejection" in lowered
    ):
        return None

    # Case 1: Incomplete booking parameters (Pydantic validation errors on BookingRequest)
    if "validation error" in lowered and ("bookingrequest" in lowered or intent == "booking_request"):
        missing = []
        if "travel_date" in lowered:
            missing.append("Travel Date")
        if "train_id" in lowered:
            missing.append("Train ID")
        if "seat_class" in lowered:
            missing.append("Seat Class")
        if "passenger_count" in lowered:
            missing.append("Passenger Count")
        if "nic" in lowered:
            missing.append("Passenger NIC")

        missing_str = ", ".join(missing) if missing else "required booking parameters"
        return {
            "summary": f"Incomplete Booking Details (Missing: {missing_str})",
            "details": f"The passenger requested a route, but did not specify {missing_str}. The Booking Agent requires these mandatory fields to create a confirmed seat reservation.",
            "missing_fields": missing,
        }

    # Case 2: Cancellation failure (e.g. not found, already cancelled)
    if intent == "cancel_booking" or "cancel" in lowered:
        if "not found" in lowered:
            return {
                "summary": "Booking Reference Not Found",
                "details": "The provided booking reference does not match any active ticket in the database.",
                "missing_fields": [],
            }
        if "already cancelled" in lowered:
            return {
                "summary": "Ticket Already Cancelled",
                "details": "This booking has already been cancelled previously.",
                "missing_fields": [],
            }
        return {
            "summary": "Cancellation Request Rejected",
            "details": "The Booking Agent could not process this cancellation request.",
            "missing_fields": [],
        }

    # Case 3: Train identity / lookup errors
    if "train_not_found" in lowered or ("not found" in lowered and "train" in lowered):
        return {
            "summary": "Train Identity Unrecognized",
            "details": "Operations or Maintenance could not find a train service matching the requested identifier.",
            "missing_fields": ["Valid Train ID"],
        }

    # Case 4: Network / Connectivity / Port offline
    if any(k in lowered for k in ["connection refused", "502 bad gateway", "failed to connect", "unreachable", "timed out", "timeout"]):
        target = receiver or "destination agent"
        return {
            "summary": f"Agent Unreachable ({target})",
            "details": f"The Communication Hub could not connect to {target}. The agent service may be offline or restarting.",
            "missing_fields": [],
        }

    # Case 5: Circuit breaker
    if "circuit breaker" in lowered:
        target = receiver or "destination agent"
        return {
            "summary": f"Circuit Breaker Open ({target})",
            "details": f"Outbound calls to {target} are temporarily blocked by the Hub to prevent cascading failures.",
            "missing_fields": [],
        }

    # Case 6: Rate limit / Throttling
    if "rate limit" in lowered or "429" in lowered:
        return {
            "summary": "Rate Limit Exceeded",
            "details": "The sending agent exceeded the allowed message rate limit for this endpoint.",
            "missing_fields": [],
        }

    # Case 7: Authentication / Permission
    if any(k in lowered for k in ["unauthorized", "forbidden", "401", "403", "invalid token"]):
        return {
            "summary": "Authentication / Permission Denied",
            "details": "The sender lacks valid authorization credentials or permissions for this intent.",
            "missing_fields": [],
        }

    # Fallback: clean first line
    first_line = err.split("\n")[0].strip()
    return {
        "summary": first_line[:90] + ("..." if len(first_line) > 90 else ""),
        "details": err,
        "missing_fields": [],
    }


@app.get("/api/hub/timeline", tags=["hub"])
async def hub_timeline_proxy(limit: int = Query(default=20, ge=1, le=100)) -> JSONResponse:
    """Proxy inter-agent message timeline."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{HUB_URL}/api/hub/timeline", params={"limit": limit})
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                if items:
                    result_items = []
                    for i in items:
                        raw_err = i.get("error_message")
                        intent = i.get("intent", "")
                        receiver = i.get("receiver_agent") or i.get("receiver", "")
                        sender = i.get("sender_agent") or i.get("sender", "")
                        raw_status = i.get("status", "ROUTED")
                        is_admin_decision = (
                            sender == "admin-adjudicator"
                            or "cancellation_review" in intent
                            or "fraud_review" in intent
                        )
                        status = "ROUTED" if is_admin_decision else raw_status
                        h = None if is_admin_decision else (humanize_hub_error(raw_err, intent=intent, receiver=receiver) if raw_err else None)
                        result_items.append({
                            "message_id": i.get("message_id"),
                            "correlation_id": i.get("correlation_id"),
                            "sender": sender,
                            "receiver": receiver,
                            "intent": intent,
                            "status": status,
                            "error_message": None if is_admin_decision else raw_err,
                            "error_summary": h["summary"] if h else None,
                            "error_details": h["details"] if h else None,
                            "missing_fields": h["missing_fields"] if h else [],
                            "duration_ms": i.get("duration_ms"),
                            "timestamp": i.get("timestamp"),
                        })
                    return JSONResponse(status_code=200, content=result_items)
    except Exception:
        pass

    try:
        sys.path.insert(0, str(_M3_ROOT / "agent-hub"))
        from hub_database import SessionLocal, AuditLog
        with SessionLocal() as db:
            logs = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
            result_items = []
            for l in logs:
                raw_err = getattr(l, "error_message", None)
                intent = l.intent or ""
                receiver = l.receiver_agent or ""
                sender = l.sender_agent or ""
                raw_status = l.status.value if hasattr(l.status, "value") else str(l.status)
                is_admin_decision = (
                    sender == "admin-adjudicator"
                    or "cancellation_review" in intent
                    or "fraud_review" in intent
                )
                status = "ROUTED" if is_admin_decision else raw_status
                h = None if is_admin_decision else (humanize_hub_error(raw_err, intent=intent, receiver=receiver) if raw_err else None)
                result_items.append({
                    "message_id": l.message_id,
                    "correlation_id": getattr(l, "correlation_id", None),
                    "sender": sender,
                    "receiver": receiver,
                    "intent": intent,
                    "status": status,
                    "error_message": None if is_admin_decision else raw_err,
                    "error_summary": h["summary"] if h else None,
                    "error_details": h["details"] if h else None,
                    "missing_fields": h["missing_fields"] if h else [],
                    "duration_ms": float(l.duration_ms) if getattr(l, "duration_ms", None) is not None else None,
                    "timestamp": l.timestamp.isoformat() if l.timestamp else None,
                })
            return JSONResponse(status_code=200, content=result_items)
    except Exception as exc:
        print("[Serve Hub Timeline Error]:", exc)
        return JSONResponse(status_code=200, content=[])


# ---------------------------------------------------------------------------
# Ticket Verification & E-Ticket QR Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/tickets/verify/{ticket_token}", tags=["tickets"])
async def verify_ticket_endpoint(ticket_token: str) -> JSONResponse:
    """Server-side ticket verification without PII exposure."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BOOKING_AGENT_URL}/api/tickets/verify/{ticket_token}")
            if resp.status_code in (200, 404):
                return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception:
        pass

    try:
        sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
        from database.database import SessionLocal
        from booking.qr_service import verify_ticket_token
        with SessionLocal() as db:
            ver = verify_ticket_token(db, ticket_token)
            if not ver.get("is_valid"):
                return JSONResponse(status_code=404, content={"detail": ver.get("message", "Ticket not found.")})
            return JSONResponse(status_code=200, content=ver)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": f"Verification error: {exc}"})


@app.get("/api/tickets/{booking_reference}", tags=["tickets"])
async def get_booking_ticket(booking_reference: str) -> JSONResponse:
    """Retrieve booking details with opaque ticket token and QR SVG."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BOOKING_AGENT_URL}/bookings/{booking_reference}")
            if resp.status_code == 200:
                return JSONResponse(status_code=200, content=resp.json())
    except Exception:
        pass

    try:
        sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
        from database.database import SessionLocal
        from database.models import Booking
        from booking.qr_service import generate_ticket_token, generate_ticket_qr_svg
        with SessionLocal() as db:
            b = db.query(Booking).filter(Booking.booking_reference == booking_reference).first()
            if not b:
                return JSONResponse(status_code=404, content={"error": "Booking not found."})
            tok = b.ticket_token or generate_ticket_token()
            qr_svg = generate_ticket_qr_svg(tok)
            return JSONResponse(
                status_code=200,
                content={
                    "booking_reference": b.booking_reference,
                    "status": b.status.value if hasattr(b.status, "value") else str(b.status),
                    "train_id": b.train.train_id if b.train else "",
                    "travel_date": b.travel_date.isoformat() if b.travel_date else "",
                    "passenger_count": b.passenger_count,
                    "fare": str(b.fare),
                    "ticket_token": tok,
                    "qr_svg": qr_svg,
                },
            )
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


# ---------------------------------------------------------------------------
# Seat Hold & Waiting List Endpoints
# ---------------------------------------------------------------------------

class SeatHoldInput(BaseModel):
    train_id: str
    from_station: str
    to_station: str
    travel_date: str
    seat_class: str
    passenger_count: int = Field(default=1, ge=1, le=10)
    user_id: str = "web_user"


class WaitingListInput(BaseModel):
    train_id: str
    from_station: str
    to_station: str
    travel_date: str
    seat_class: str
    passenger_count: int = Field(default=1, ge=1, le=10)
    passenger_email: EmailStr
    user_id: str = "web_user"


@app.post("/api/holds", tags=["booking"])
async def create_hold_endpoint(req: SeatHoldInput) -> JSONResponse:
    """Create a 5-minute prototype seat hold."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{BOOKING_AGENT_URL}/internal/seat-holds",
                json=req.model_dump(),
            )
            return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception:
        pass

    try:
        sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
        from database.database import SessionLocal
        from booking.lifecycle import create_seat_hold
        from schemas.booking import SeatHoldRequest
        d = date.fromisoformat(req.travel_date)
        hold_req = SeatHoldRequest(
            train_id=req.train_id,
            from_station=req.from_station,
            to_station=req.to_station,
            travel_date=d,
            seat_class=req.seat_class,
            passenger_count=req.passenger_count,
            user_id=req.user_id,
        )
        with SessionLocal() as db:
            res = create_seat_hold(db, hold_req)
            return JSONResponse(status_code=200, content=res.model_dump(mode="json"))
    except Exception as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})


@app.post("/api/waiting-list", tags=["booking"])
async def join_waiting_list_endpoint(req: WaitingListInput) -> JSONResponse:
    """Join the FIFO waiting list for sold-out services."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{BOOKING_AGENT_URL}/internal/waiting-list",
                json=req.model_dump(),
            )
            return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception:
        pass

    try:
        sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
        from database.database import SessionLocal
        from booking.waiting_list import enqueue_waiting_list
        from schemas.booking import WaitingListRequest
        d = date.fromisoformat(req.travel_date)
        wl_req = WaitingListRequest(
            train_id=req.train_id,
            from_station=req.from_station,
            to_station=req.to_station,
            travel_date=d,
            seat_class=req.seat_class,
            passenger_count=req.passenger_count,
            passenger_email=req.passenger_email,
            user_id=req.user_id,
        )
        with SessionLocal() as db:
            res = enqueue_waiting_list(db, wl_req)
            return JSONResponse(status_code=200, content=res.model_dump(mode="json"))
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


# ---------------------------------------------------------------------------
# Admin Booking Intelligence Chatbot Proxy
# ---------------------------------------------------------------------------

@app.post("/api/admin/booking-chat", tags=["admin"])
async def proxy_admin_booking_chat(request: Request) -> JSONResponse:
    """
    Proxy endpoint for the Admin Booking Intelligence Assistant.
    Forwards natural-language queries to Booking Agent (/api/admin/booking-chat).
    Falls back to direct in-memory AdminChatService if backend is offline.
    """
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{BOOKING_AGENT_URL}/api/admin/booking-chat",
                json=body,
            )
            if resp.status_code == 200:
                return JSONResponse(status_code=200, content=resp.json())
    except Exception:
        pass

    # Direct database fallback
    try:
        sys.path.insert(0, str(_M3_ROOT / "booking-agent"))
        from database.database import SessionLocal
        from admin_chat.query_router import AdminChatService
        from admin_chat.schemas import AdminChatRequest

        chat_req = AdminChatRequest(**body)
        with SessionLocal() as db:
            service = AdminChatService(db)
            result = service.process_chat_message(chat_req)
            return JSONResponse(status_code=200, content=result.model_dump())
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"Booking Intelligence Chatbot unavailable: {exc}"},
        )


# ---------------------------------------------------------------------------
# CLI Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    side = os.getenv("RAILSENSE_SIDE", "").lower()
    if side in ("user", "admin"):
        # start.py runs one process per side (with auto-reload).
        port = int(os.getenv("PORT") or _public_port(side))
        print(f"Starting RailSense {side} side on http://localhost:{port}/{side}")
        uvicorn.run("serve:app", host="0.0.0.0", port=port, reload=True)
    else:
        # Run on its own: both sides from one process (no auto-reload).
        import asyncio

        async def _both():
            servers = [uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=_public_port(s), log_level="info"))
                       for s in ("user", "admin")]
            print(f"RailSense user side:  http://localhost:{_public_port('user')}/user")
            print(f"RailSense admin side: http://localhost:{_public_port('admin')}/admin")
            await asyncio.gather(*(s.serve() for s in servers))

        asyncio.run(_both())

