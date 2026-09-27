"""RailSense Operations Agent: prediction, triage, hub and dashboard APIs.

Endpoints:
    GET  /health              -> liveness check
    POST /predict-delay       -> delay prediction (stubbed until Phase 2 ML model lands)
    GET  /route-status/{id}   -> latest known status for a route
    POST /incident-report     -> summarize and classify a raw staff incident report

"""

from datetime import datetime, timedelta, timezone
from enum import Enum
from collections import Counter
from contextlib import asynccontextmanager
import csv
import json
import re
import time
import logging
import os
import uuid
import asyncio
import threading
import sys
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import bleach
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from ml import predict as delay_model
from nlp import classify_incident as incident_classifier
from nlp import summarize_incident as incident_summarizer
from nlp import passenger_answer
from rag import explanation as explanation_layer
from rag import incident_retriever
import hub_client
import supabase_store
from admin import admin_db
from admin.admin_router import router as admin_router
from admin.admin_auth import ROLE_DISPLAY_NAMES, get_permissions_for_role, require_permission
import incident_map
import live_tracker
from shared.train_repository import TrainRepositoryUnavailable, get_train, resolve_train

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("railsense.operations")
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])


@asynccontextmanager
async def lifespan(_app):
    try:
        incident_retriever._load_root_env()
        # Warm up unconditionally — the embedding model is always needed for
        # predictions, and lazy-loading it blocks the async event loop.
        await asyncio.to_thread(incident_retriever._get_embedding_model)
        logger.info("Warmed RAG embedding model")
    except Exception as exc:
        logger.warning("RAG model warm-up skipped: %s", exc.__class__.__name__)
    try:
        await hub_client.register_with_hub()
        logger.info("Registered with agent Hub")
    except Exception as exc:
        logger.warning("Hub unavailable during startup: %s", exc)
    try:
        admin_db.seed_initial_admin_if_needed()
        logger.info("Bootstrapped M2 operations RBAC admin")
    except Exception as exc:
        logger.warning("RBAC bootstrap skipped: %s", exc)
    yield

app = FastAPI(
    title="M2 — Operations & Delay-Prediction Agent",
    description="RailSense AI · Operations & Delay-Prediction Agent (Member B / M2)",
    version="0.5.0",
    lifespan=lifespan,
)
app.include_router(admin_router)
app.mount("/admin", StaticFiles(directory=Path(__file__).parent / "admin_ui", html=True), name="admin_ui")
# Browser code shared by the Control Room, the Admin Console and the passenger
# portal on :3000 (the incident map), so all three render incidents identically.
app.mount("/shared", StaticFiles(directory=Path(__file__).parent / "ui" / "shared"), name="shared_ui")
app.state.limiter = limiter

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)
# The train catalogue (~3,000 trains) and dashboard aggregates are repetitive
# JSON; gzip cuts them to a fraction of their size on the wire.
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=2048)


@app.middleware("http")
async def revalidate_ui_assets(request: Request, call_next):
    """Make browsers re-check the UI files on every load.

    StaticFiles sends no Cache-Control, so browsers cached index.html / nav.js
    heuristically and kept serving old copies after an update (e.g. without
    the Operations Assistant). `no-cache` still allows the cached copy, but
    only after an ETag revalidation (a cheap 304 when nothing changed).
    """
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith(("/admin/", "/shared/")) and not path.startswith("/admin/api/") or path == "/admin":
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


async def rate_limit_handler(request, exc):
    return __import__("fastapi").responses.JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

AGENT_NAME = "operations-agent"
UI_PATH = Path(__file__).parent / "ui" / "index.html"
DATA_PATH = Path(__file__).parent / "data" / "operations_history.csv"
AUDIT_PATH = Path(__file__).parent / "data" / "audit_log.jsonl"
# Recent in-process prediction results, and delay_alert events retained when
# Supabase is unreachable. Incidents are no longer mirrored here — they live in
# the real incident store (admin_db, Supabase primary / local JSONL fallback).
_predictions: list[dict] = []
_events: list[dict] = []


def _load_history() -> list[dict]:
    if not DATA_PATH.exists():
        return []
    with DATA_PATH.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


HISTORY = _load_history()


def _audit(action: str, request: Request, details: dict) -> None:
    """Append one inter-agent audit event to Supabase and the local JSONL.

    The Audit & Agent Communication Log screen reads these rows, so every
    record carries the full documented shape — message_id, sender_agent,
    receiver_agent, intent, timestamp, outcome — whichever store it lands in.
    Callers pass overrides in `details`; the defaults below describe a local
    (non-hub) action this agent performed on its own behalf.
    """
    details = dict(details)
    sender = details.pop("sender_agent", None) or AGENT_NAME
    receiver = details.pop("receiver_agent", None) or AGENT_NAME
    intent = details.pop("intent", None) or action
    outcome = details.pop("outcome", None) or "success"
    message_id = details.pop("message_id", None) or uuid.uuid4().hex

    record = {
        "message_id": message_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "intent": intent,
        "sender_agent": sender,
        "receiver_agent": receiver,
        "outcome": outcome,
        "client": get_remote_address(request),
        **details,
    }
    try:
        with AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
    except OSError as exc:
        logger.warning("Could not write audit record: %s", exc)

    if not supabase_store.insert_audit(action, get_remote_address(request), record):
        logger.info("Supabase audit unavailable; retained local audit record")


def _record_event(event: dict, destinations: list[str]) -> None:
    _events.append(event | {"published": bool(destinations), "destinations": destinations})
    if not supabase_store.insert_event(event, destinations):
        logger.info("Supabase events unavailable; retained in-memory event")


async def _persist_prediction_side_effects(
    request: Request,
    route: str,
    train_id: str,
    delay: float,
    model_version: str,
) -> None:
    alert = await hub_client.publish_delay_alert(route, train_id, delay)
    if alert.get("event"):
        await asyncio.to_thread(_record_event, alert["event"], alert.get("destinations", []))
    await asyncio.to_thread(
        _audit,
        "prediction",
        request,
        {"route": route, "train_id": train_id, "delay": delay, "model": model_version},
    )


def _run_prediction_side_effects(
    request: Request,
    route: str,
    train_id: str,
    delay: float,
    model_version: str,
) -> None:
    asyncio.run(
        _persist_prediction_side_effects(
            request, route, train_id, delay, model_version
        )
    )


def _start_prediction_side_effects(
    request: Request,
    route: str,
    train_id: str,
    delay: float,
    model_version: str,
) -> None:
    threading.Thread(
        target=_run_prediction_side_effects,
        args=(request, route, train_id, delay, model_version),
        daemon=True,
    ).start()


def _metric_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _route_for_station(station: Optional[str]) -> str:
    """Resolve a reported station to a real corridor from the operations corpus.

    Incidents are filed against a station, but the retrieval corpus is keyed by
    route. Rather than labelling live reports with a placeholder, look the
    station up in the historical data and use the busiest real route serving it.
    """
    if not station:
        return "Unassigned corridor"
    needle = str(station).casefold()
    matches = Counter(
        row.get("route") for row in HISTORY
        if str(row.get("station", "")).casefold() == needle and row.get("route")
    )
    if matches:
        return matches.most_common(1)[0][0]
    for row in HISTORY:
        if needle in str(row.get("route", "")).casefold():
            return row["route"]
    return "Unassigned corridor"


def _index_incident_for_retrieval(record: dict) -> dict:
    """Add a live incident to both retrieval indexes so RAG can cite it.

    pgvector is updated through the same embeddings pipeline the bulk loader
    uses (rag/embed_documents.py); the local TF-IDF index is refreshed so the
    offline path stays in step. Best-effort: indexing failures are reported,
    never raised, so they can't fail incident creation.
    """
    outcome = {"local_tfidf": False, "pgvector": False, "detail": ""}
    try:
        outcome["local_tfidf"] = incident_retriever.add_live_incident(record)
    except Exception as exc:
        outcome["detail"] = f"tfidf: {exc.__class__.__name__}"
        logger.warning("Local incident indexing failed: %s", exc)

    try:
        from rag import embed_documents

        result = embed_documents.embed_incident(record)
        outcome["pgvector"] = result["indexed"]
        if not result["indexed"]:
            outcome["detail"] = (outcome["detail"] + " " + result["reason"]).strip()
    except Exception as exc:
        outcome["detail"] = (outcome["detail"] + f" pgvector: {exc.__class__.__name__}").strip()
        logger.warning("pgvector incident indexing skipped: %s", exc)
    return outcome


def _unindex_incident(incident_id: str) -> dict:
    """Drop a deleted incident from both retrieval indexes."""
    outcome = {"local_tfidf": False, "pgvector": False, "detail": ""}
    try:
        outcome["local_tfidf"] = incident_retriever.remove_live_incident(incident_id)
    except Exception as exc:
        logger.warning("Local incident de-indexing failed: %s", exc)

    try:
        from rag import embed_documents

        result = embed_documents.delete_incident_embedding(incident_id)
        outcome["pgvector"] = result["deleted"]
        if not result["deleted"]:
            outcome["detail"] = result["reason"]
    except Exception as exc:
        outcome["detail"] = f"pgvector: {exc.__class__.__name__}"
        logger.warning("pgvector incident de-indexing skipped: %s", exc)
    return outcome


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class WeatherCondition(str, Enum):
    clear = "clear"
    light_rain = "light_rain"
    heavy_rain = "heavy_rain"
    fog = "fog"
    extreme_heat = "extreme_heat"


class DayType(str, Enum):
    weekday = "weekday"
    weekend = "weekend"
    public_holiday = "public_holiday"


class IncidentClassification(str, Enum):
    """Labels the NLP classifier can assign — the correctable set in the UI.

    Mirrors nlp/classify_incident.CATEGORIES so a controller can only correct a
    classification to a label the model could itself have produced, keeping
    corrected rows usable as evaluation ground truth.
    """

    signal_fault = "signal_fault"
    mechanical = "mechanical"
    weather = "weather"
    track_obstruction = "track_obstruction"
    staffing = "staffing"
    other = "other"


class ReviewStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    corrected = "corrected"


class IncidentType(str, Enum):
    none = "none"
    signal_fault = "signal_fault"
    mechanical = "mechanical"
    weather = "weather"
    track_obstruction = "track_obstruction"
    staffing = "staffing"


def _historical_delay_estimate(
    route: str,
    scheduled_time: datetime,
    station: Optional[str],
    weather: Optional[WeatherCondition],
    day_type: Optional[DayType],
    incident_type: Optional[IncidentType],
) -> tuple[float, int]:
    """Estimate delay from the closest matching records when no model is trained."""
    candidates = HISTORY
    filters = [
        lambda row: row.get("route") == route,
        lambda row: station and row.get("station") == station,
        lambda row: row.get("scheduled_time", "").startswith(f"{scheduled_time.date()}"),
        lambda row: row.get("weather") == weather.value if weather else True,
        lambda row: row.get("day_type") == day_type.value if day_type else True,
        lambda row: row.get("incident_type") == incident_type.value if incident_type else True,
    ]
    for predicate in filters:
        narrowed = [row for row in candidates if predicate(row)]
        if narrowed:
            candidates = narrowed

    delays = sorted(float(row.get("delay_minutes", 0)) for row in candidates)
    if not delays:
        raise HTTPException(status_code=503, detail="No historical operations data is available for this request")
    middle = len(delays) // 2
    estimate = delays[middle] if len(delays) % 2 else (delays[middle - 1] + delays[middle]) / 2
    return round(estimate, 1), len(candidates)


def _find_historical_train(train_id: str, route: str) -> dict | None:
    """Return the latest matching observation for a known train and route."""
    matches = [
        row for row in HISTORY
        if row.get("train_id", "").casefold() == train_id.casefold()
        and row.get("route", "").casefold() == route.casefold()
    ]
    if not matches:
        return None
    return max(matches, key=lambda row: row.get("scheduled_time", ""))


def _canonical_train_or_error(train_id: str) -> dict:
    """Resolve a caller-supplied train id to its canonical registry row.

    Passengers type the service number printed on a timetable ("4082") as
    often as the operational id ("PM-4082"), and the registry holds both
    conventions. resolve_train() accepts either, but refuses to pick when a
    bare number matches more than one train - that case is reported back with
    the candidates so the passenger can be asked which one they meant, rather
    than being given a confident delay figure for the wrong service.
    """
    try:
        train, candidates = resolve_train(train_id)
    except TrainRepositoryUnavailable as exc:
        raise HTTPException(status_code=503, detail="TRAIN_REGISTRY_UNAVAILABLE") from exc
    if train is None and candidates:
        raise HTTPException(
            status_code=409,
            detail=f"TRAIN_ID_AMBIGUOUS: {train_id} matches "
                   f"{', '.join(c.get('train_id', '') for c in candidates)}",
        )
    if train is None or not train.get("active", False):
        raise HTTPException(status_code=404, detail=f"TRAIN_NOT_FOUND: {train_id}")
    return train


class DelayPredictionRequest(BaseModel):
    route: str = Field(..., min_length=3, max_length=120, examples=["Colombo Fort - Kandy"])
    # min_length=1, not 3: the canonical registry holds both prefixed ids
    # (PM-4082) and bare Sri Lanka Railways service numbers as short as two
    # digits (e.g. "50" = Ruhunu Kumari). _canonical_train_or_error() below
    # is the real validation - a bogus short string still 404s there.
    train_id: str = Field(..., min_length=1, max_length=20, examples=["PM-4082", "50"])
    scheduled_time: datetime = Field(..., description="ISO 8601 scheduled departure/arrival time")
    weather: Optional[WeatherCondition] = None
    day_type: Optional[DayType] = None
    station: Optional[str] = Field(None, min_length=2, max_length=80)
    incident_type: Optional[IncidentType] = None

    @field_validator("route", "train_id")
    @classmethod
    def no_control_chars(cls, v: str) -> str:
        if any(ord(ch) < 32 for ch in v):
            raise ValueError("field contains invalid control characters")
        return v.strip()


class DelayPredictionResponse(BaseModel):
    route: str
    train_id: str
    predicted_delay_minutes: float
    confidence: str  # "low" | "medium" | "high"
    explanation: str
    top_contributing_features: list[dict] = []
    similar_past_incidents: list[str] = []
    model_version: str
    retrieval_method: str = "local_tfidf"
    explanation_method: str = "template_grounded"


class RouteStatusResponse(BaseModel):
    route_id: str
    status: str
    active_trains: int
    average_delay_minutes: float
    last_updated: datetime


class IncidentReportRequest(BaseModel):
    train_id: str = Field(..., min_length=1, max_length=20)  # see DelayPredictionRequest.train_id
    station: str = Field(..., min_length=2, max_length=80)
    raw_text: str = Field(..., min_length=5, max_length=2000)

    @field_validator("train_id", "station", "raw_text")
    @classmethod
    def sanitize_text(cls, v: str, info) -> str:
        value = v.strip()
        if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value):
            raise ValueError(f"{info.field_name} contains invalid control characters")

        if info.field_name == "raw_text":
            cleaned = bleach.clean(
                value,
                tags=[],
                attributes={},
                protocols=[],
                strip=True,
                strip_comments=True,
            )
            if cleaned != value:
                raise ValueError("raw_text contains disallowed markup")
            value = cleaned

        return value


class IncidentReportResponse(BaseModel):
    incident_id: str
    train_id: str
    station: str
    summary: str
    classified_type: str
    nlp_method: str  # "rule_based" | "llm" — transparency on how this was produced
    received_at: datetime


class HubMessage(BaseModel):
    message_id: Optional[str] = None
    sender_agent: str = Field(..., min_length=2, max_length=80)
    receiver_agent: str = Field(default=AGENT_NAME, min_length=2, max_length=80)
    intent: str = Field(..., min_length=2, max_length=80)
    payload: dict = Field(default_factory=dict)
    auth_token: Optional[str] = None
    timestamp: Optional[datetime] = None


@app.post("/internal/messages")
async def receive_internal_message(request: Request, message: HubMessage):
    """Accept messages forwarded by the central hub.

    This is the contract that the shared Agent Hub uses when it routes traffic to
    a destination agent via {base_url}/internal/messages. M3 validates and
    authenticates first, so this endpoint only needs to process the forwarded
    payload and respond in the same shape the hub expects.
    """
    if message.receiver_agent not in (AGENT_NAME, "operations-agent"):
        raise HTTPException(status_code=400, detail="unsupported receiver agent")

    if message.intent == "delay_check":
        return await hub_message(request, message)

    if message.intent in {"booking_request", "cancel_booking"}:
        return JSONResponse(
            status_code=202,
            content={
                "message_id": message.message_id or uuid.uuid4().hex,
                "sender_agent": AGENT_NAME,
                "receiver_agent": message.sender_agent,
                "intent": "ack",
                "payload": {"status": "received", "accepted_intent": message.intent},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    raise HTTPException(status_code=400, detail="unsupported hub intent")


def _read_audit_count() -> int:
    try:
        return sum(1 for _ in AUDIT_PATH.open(encoding="utf-8"))
    except OSError:
        return 0


def _history_route_stats(history: list[dict] | None = None) -> list[dict]:
    history = HISTORY if history is None else history
    grouped: dict[str, list[dict]] = {}
    for row in history:
        grouped.setdefault(row.get("route", "Unknown"), []).append(row)
    result = []
    for route, rows in grouped.items():
        delays = [float(row.get("delay_minutes", 0)) for row in rows]
        incident_count = sum(row.get("incident_type") != "none" for row in rows)
        average = sum(delays) / len(delays) if delays else 0
        result.append({"route": route, "trips": len(rows), "average_delay": round(average, 1), "max_delay": round(max(delays, default=0), 1), "incident_rate": round(incident_count / len(rows) * 100, 1), "status": "critical" if average >= 10 else "watch" if average >= 5 else "normal"})
    return sorted(result, key=lambda item: item["average_delay"], reverse=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(UI_PATH)

@app.get("/health")
def health():
    return {
        "status": "ok",
        "agent": AGENT_NAME,
        "hub_configured": hub_client.HUB_BASE_URL != "http://localhost:8000" or bool(hub_client.HUB_AUTH_TOKEN),
        "history_records": len(HISTORY),
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/dashboard")
def dashboard_data():
    """Single aggregate behind the consolidated Control Room dashboard.

    Network KPIs, the route delay heatmap and the hourly delay-pressure curve
    were three separate panels making three calls; they are now one section
    served by this one query. Every number is computed from the live
    operations corpus (Supabase when reachable, data/operations_history.csv
    otherwise) or from a committed evaluation artifact — nothing is synthesised
    here. `data_source.offline` tells the UI to show the offline banner rather
    than passing stale data off as live.
    """
    supabase_history = supabase_store.fetch_history()
    offline = supabase_history is None
    history = supabase_history if supabase_history else HISTORY

    route_stats = _history_route_stats(history)
    delays = [float(row.get("delay_minutes", 0)) for row in history]
    incident_counts = Counter(
        row.get("incident_type", "other") for row in history if row.get("incident_type") != "none"
    )

    hour_groups: dict[int, list[float]] = {hour: [] for hour in range(24)}
    for row in history:
        try:
            hour = datetime.fromisoformat(str(row["scheduled_time"]).replace("Z", "+00:00")).hour
            hour_groups[hour].append(float(row.get("delay_minutes", 0)))
        except (KeyError, ValueError):
            continue
    hourly = [
        {"hour": hour, "average_delay": round(sum(values) / len(values), 1) if values else 0,
         "samples": len(values)}
        for hour, values in hour_groups.items()
    ]

    eval_dir = Path(__file__).parent / "evaluation"
    ml_metrics = _metric_file(eval_dir / "ml" / "delay_model_metrics.json")
    nlp_metrics = _metric_file(eval_dir / "nlp" / "classification_metrics.json")
    rag_metrics = _metric_file(eval_dir / "rag" / "retrieval_metrics.json")
    robustness = _metric_file(eval_dir / "nlp" / "out_of_template_robustness_check.json")

    recent_events = supabase_store.fetch_recent_events(50)
    events_offline = recent_events is None
    events = recent_events if recent_events is not None else list(reversed(_events[-50:]))
    audit_total = supabase_store.count_rows("audit_events")
    if audit_total is None:
        audit_total = _read_audit_count()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": {
            "history": "supabase" if not offline else "local_csv",
            "events": "supabase" if not events_offline else "in_memory",
            "offline": offline,
        },
        "overview": {
            "trips": len(history),
            "average_delay": round(sum(delays) / len(delays), 1) if delays else 0,
            "on_time_rate": round(sum(delay <= 5 for delay in delays) / len(delays) * 100, 1) if delays else 0,
            "active_alerts": len([e for e in events if e.get("event_type") == "delay_alert"]),
            "audit_events": audit_total,
            "routes_monitored": len(route_stats),
        },
        "routes": route_stats,
        "hourly": hourly,
        "incident_mix": [{"type": key, "count": value} for key, value in incident_counts.most_common()],
        "feature_importance": delay_model.get_all_features()[:8],
        "ml_metrics": ml_metrics,
        "nlp_metrics": nlp_metrics,
        "rag_metrics": rag_metrics,
        "robustness": robustness,
        "events": events[:12],
        "hub": {
            "configured": bool(os.getenv("HUB_BASE_URL")),
            "endpoint": hub_client.HUB_BASE_URL,
            "alert_threshold_minutes": hub_client.DELAY_ALERT_THRESHOLD_MINUTES,
        },
    }


def _route_options(history: list[dict]) -> list[dict]:
    """Group the operations corpus into route -> {trains, stations}.

    Stations are ordered along the corridor: the origin and destination named
    in the route string bracket the intermediate stops, which sit between them
    alphabetically. Train ids come from the same corpus the model was trained
    on, and every one of them is seeded into the shared canonical registry.
    """
    grouped: dict[str, dict[str, set]] = {}
    for row in history:
        route = row.get("route")
        if not route:
            continue
        bucket = grouped.setdefault(route, {"trains": set(), "stations": set()})
        if row.get("train_id"):
            bucket["trains"].add(str(row["train_id"]))
        if row.get("station"):
            bucket["stations"].add(str(row["station"]))

    options = []
    for route, bucket in grouped.items():
        ends = [part.strip() for part in route.split(" - ")]
        origin, destination = ends[0], ends[-1]
        stations = bucket["stations"]
        middle = sorted(s for s in stations if s not in (origin, destination))
        ordered = ([origin] if origin in stations else []) + middle + (
            [destination] if destination in stations and destination != origin else [])
        options.append({
            "route": route,
            "trains": sorted(bucket["trains"]),
            "stations": ordered,
        })
    return sorted(options, key=lambda item: item["route"])


@app.get("/api/route-options")
def route_options():
    """Route -> train ids and stations, feeding the prediction form dropdowns."""
    supabase_history = supabase_store.fetch_history()
    history = supabase_history if supabase_history else HISTORY
    return {
        "source": "supabase" if supabase_history else "local_csv",
        "routes": _route_options(history),
    }


class PassengerServiceContext(BaseModel):
    """Today's-board snapshot of the train the passenger clicked on."""
    train_id: str = Field(..., min_length=1, max_length=20)
    train_name: Optional[str] = Field(None, max_length=80)
    route: Optional[str] = Field(None, max_length=120)
    from_station: Optional[str] = Field(None, max_length=80)
    to_station: Optional[str] = Field(None, max_length=80)
    departure_time: Optional[str] = Field(None, max_length=8)
    arrival_time: Optional[str] = Field(None, max_length=8)
    service_status: Optional[str] = Field(None, max_length=30)
    maintenance_status: Optional[str] = Field(None, max_length=30)
    live_status: Optional[str] = Field(None, max_length=30)
    current_station: Optional[str] = Field(None, max_length=80)
    next_station: Optional[str] = Field(None, max_length=80)
    progress_percent: Optional[float] = None
    stops: list[str] = Field(default_factory=list, max_length=40)


class PassengerAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=300)
    mode: Optional[str] = Field(None, pattern="^(delay|operations)$")
    service: PassengerServiceContext


def _corridor_for(route: Optional[str], origin: Optional[str], destination: Optional[str]) -> Optional[str]:
    """Map a board route ("Colombo - Jaffna") onto a corridor the model knows."""
    known = {row.get("route") for row in HISTORY if row.get("route")}
    if route in known:
        return route
    route_end = route.split(" - ")[-1].strip() if route and " - " in route else None
    for station in (route_end, destination, origin):
        if not station:
            continue
        needle = station.casefold()
        for corridor in sorted(known):
            if corridor.casefold().split(" - ")[-1] == needle:
                return corridor
        for corridor in sorted(known):
            if needle in corridor.casefold():
                return corridor
    return None


def _passenger_delay_estimate(ctx: PassengerServiceContext, corridor: Optional[str]) -> Optional[dict]:
    """Delay estimate for a passenger question, without prediction side effects."""
    if not corridor:
        return None
    try:
        train, _ = resolve_train(ctx.train_id)
        canonical_id = (train or {}).get("train_id") or ctx.train_id
    except TrainRepositoryUnavailable:
        canonical_id = ctx.train_id
    observed = _find_historical_train(canonical_id, corridor)
    if observed:
        return {"minutes": float(observed.get("delay_minutes") or 0), "confidence": "high",
                "corridor": corridor, "method": "historical_record"}

    known_stations = {row.get("station") for row in HISTORY if row.get("route") == corridor}
    station = next((s for s in (ctx.current_station, ctx.from_station) if s in known_stations), None)
    departure = datetime.now(timezone.utc)
    try:
        departure = datetime.strptime(ctx.departure_time or "", "%H:%M:%S")
    except ValueError:
        pass
    day_type = "weekend" if datetime.now().weekday() >= 5 else "weekday"
    try:
        if delay_model.is_model_available():
            result = delay_model.predict_delay(route=corridor, scheduled_hour=departure.hour,
                                               day_type=day_type, station=station)
            minutes = result["predicted_delay_minutes"]
            confidence = "medium" if abs(minutes) < 20 else "low"
        else:
            minutes, samples = _historical_delay_estimate(corridor, datetime.now(), station, None, None, None)
            confidence = "low" if samples < 10 else "medium"
    except Exception:
        logger.exception("passenger delay estimate failed")
        return None
    return {"minutes": float(minutes), "confidence": confidence, "corridor": corridor, "method": "model"}


def _todays_incidents(ctx: PassengerServiceContext) -> list[dict]:
    """Incident reports filed in the last 24h that touch this train or its stations."""
    try:
        rows = admin_db.list_incidents(limit=100).get("rows", [])
    except Exception:
        return []
    stations = {s.casefold() for s in [ctx.from_station, ctx.to_station, ctx.current_station,
                                       ctx.next_station, *ctx.stops] if s}
    cutoff = datetime.now(timezone.utc).timestamp() - 24 * 3600
    matches = []
    for row in rows:
        try:
            received = datetime.fromisoformat(str(row.get("received_at")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        same_train = str(row.get("train_id", "")).casefold() == ctx.train_id.casefold()
        on_route = str(row.get("station", "")).casefold() in stations
        if received >= cutoff and (same_train or on_route):
            matches.append(row)
    return matches[:3]


STATIONS = live_tracker.StationIndex(incident_map.STATION_LOCATIONS)
_IMPACT_CACHE: dict[tuple, dict] = {}


def _incident_impact(incident: dict, corridor: Optional[str]) -> dict:
    """How long a verified incident is likely to hold a train (IR over the corpus).

    The incident's own words are the query: the most similar past incidents on
    the same corridor/type are retrieved (TF-IDF, local and deterministic) and
    the median of their recorded delays is the estimate. Cached per incident.
    """
    key = (incident.get("id"), incident.get("summary"), corridor)
    if key in _IMPACT_CACHE:
        return _IMPACT_CACHE[key]
    kind = incident.get("incident_type") or "other"
    query = " ".join(filter(None, [incident.get("summary"), kind.replace("_", " "), incident.get("station")]))
    minutes, samples = 0.0, 0
    try:
        hits = incident_retriever.retrieve_similar_incidents(
            query, top_k=5, route=corridor, station=incident.get("station"),
            incident_type=kind if kind != "other" else None, use_cloud=False)["incidents"]
        same = [h for h in hits if h["incident_type"] == kind] or hits
        delays = sorted(float(h["delay_minutes"]) for h in same)
        if delays:
            mid = len(delays) // 2
            minutes = delays[mid] if len(delays) % 2 else (delays[mid - 1] + delays[mid]) / 2
            samples = len(delays)
    except Exception:
        logger.exception("incident impact retrieval failed")
    if not samples:
        typed = [float(r.get("delay_minutes") or 0) for r in HISTORY if r.get("incident_type") == kind]
        if typed:
            typed.sort()
            minutes, samples = typed[len(typed) // 2], len(typed)
    result = {"minutes": round(minutes, 1), "samples": samples,
              "basis": f"{samples} similar past incident{'s' if samples != 1 else ''}" if samples else ""}
    _IMPACT_CACHE[key] = result
    return result


def _live_journey(ctx: PassengerServiceContext, corridor: Optional[str], estimate: Optional[dict]) -> Optional[dict]:
    """Server-side timetable + position; the board's own live fields are not trusted."""
    try:
        incidents = MAP_FEED.get().get("incidents", [])
    except Exception:
        incidents = []
    try:
        return live_tracker.compute_live(
            ctx.model_dump(), STATIONS, incidents,
            impact_for=lambda inc, _label: _incident_impact(inc, corridor),
            baseline_minutes=float(estimate["minutes"]) if estimate else 0.0,
        )
    except Exception:
        logger.exception("live journey computation failed")
        return None


@app.post("/passenger/ask")
@limiter.limit("30/minute")
def passenger_ask(request: Request, req: PassengerAskRequest):
    """Friendly, grounded answer to a passenger's question about one train.

    Powers the Delay / Operations popup on the user portal. The question is
    classified by nlp/passenger_answer.detect_intent() (keyword rules, TF-IDF
    fallback) and any station it names is extracted. The answer is built from
    a server-side live journey (live_tracker: per-station timetable, position
    on the Asia/Colombo clock, delays from verified map incidents on this
    train's path, each sized by retrieving similar past incidents), the delay
    model, retrieved incident precedent and today's incident reports.
    Booking/fare questions come back with handoff=true for the Booking flow.
    """
    question = bleach.clean(req.question, tags=[], strip=True).strip()
    default = "delay" if req.mode == "delay" else "status"
    intent = passenger_answer.detect_intent(question, default=default)
    ctx = req.service
    if intent == "handoff":
        return passenger_answer.compose_answer(intent, ctx.model_dump(), None, [], [])

    answer = _answer_for_service(question, intent, ctx)
    answer.pop("_live_full", None)
    return answer


def _answer_for_service(question: str, intent: str, ctx: PassengerServiceContext) -> dict:
    """Shared by the popup and the chat assistant: live journey + NLP + IR answer."""
    corridor = _corridor_for(ctx.route, ctx.from_station, ctx.to_station)
    estimate = _passenger_delay_estimate(ctx, corridor)
    live = _live_journey(ctx, corridor, estimate)
    if live:
        # The board's position can be stale or wrong (e.g. an overnight train
        # shown "arrived" before it has even left); the live journey wins.
        ctx = ctx.model_copy(update={
            "live_status": "IN_TRANSIT" if live["status"] == "AT_STATION" else live["status"],
            "current_station": live["current_station"],
            "next_station": live["next_station"],
            "progress_percent": live["progress_percent"],
        })
    station = None
    if live:
        station = live_tracker.find_station_mention(
            question, [r["station"] for r in live["timeline"]], STATIONS)
    live_incidents = _todays_incidents(ctx)
    precedent: list[dict] = []
    if intent == "reason" and corridor:
        causes = " ".join(d["incident_type"].replace("_", " ") for d in (live or {}).get("disruptions", []))
        try:
            precedent = incident_retriever.retrieve_similar_incidents(
                f"{question} {causes} {corridor} delay", top_k=2, route=corridor)["incidents"]
        except Exception:
            precedent = []

    answer = passenger_answer.compose_answer(intent, ctx.model_dump(), estimate, live_incidents, precedent,
                                             live=live, station=station)
    answer["train_id"] = ctx.train_id
    answer["corridor"] = corridor
    answer["station"] = station
    answer["_live_full"] = live
    return answer


# ------------------------------------------------ free-text chat questions

_BOARD_CACHE: dict[str, tuple[float, list[dict]]] = {}
BOARD_CACHE_TTL_SECONDS = 60


def _board_services(day) -> list[dict]:
    """The day's services from the shared Supabase timetable (train_schedules + trains).

    Same source and shape as the passenger board; cached for a minute. Raises
    when the store is unreachable so the caller can decline instead of guessing.
    """
    key = day.isoformat()
    hit = _BOARD_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < BOARD_CACHE_TTL_SECONDS:
        return hit[1]
    from shared.train_repository import get_client
    rows = (get_client().table("train_schedules").select("*, trains(*)")
            .eq("travel_date", key).order("departure_time").execute().data or [])
    services = []
    for sched in rows:
        train = sched.get("trains") or {}
        meta_t = train.get("metadata") if isinstance(train.get("metadata"), dict) else {}
        meta_s = sched.get("metadata") if isinstance(sched.get("metadata"), dict) else {}
        stops = sched.get("stops") or meta_s.get("stops") or meta_t.get("stops") or meta_t.get("route_stops")
        maintenance = str(train.get("maintenance_status") or "UNKNOWN").upper()
        status = str(sched.get("service_status") or "SCHEDULED").upper()
        if train and (not train.get("active") or maintenance in {"OUT_OF_SERVICE", "DECOMMISSIONED"}):
            status = "OUT_OF_SERVICE"
        services.append({
            "train_id": str(train.get("train_id") or sched.get("train_id") or ""),
            "train_name": train.get("train_name"),
            "route": train.get("route"),
            "from_station": sched.get("from_station") or train.get("origin_station"),
            "to_station": sched.get("to_station") or train.get("destination_station"),
            "departure_time": str(sched.get("departure_time") or "")[:8] or None,
            "arrival_time": str(sched.get("arrival_time") or "")[:8] or None,
            "service_status": status,
            "maintenance_status": maintenance,
            "platform": sched.get("platform"),
            "stops": [str(x) for x in stops] if isinstance(stops, list) else [],
        })
    _BOARD_CACHE[key] = (time.monotonic(), services)
    return services


def _service_ctx(row: dict) -> PassengerServiceContext:
    fields = PassengerServiceContext.model_fields
    data = {k: v for k, v in row.items() if k in fields and v not in (None, "")}
    data["stops"] = (row.get("stops") or [])[:40]
    return PassengerServiceContext(**data)


def _plain(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", str(text))


def _answer_text(answer: dict) -> str:
    """Popup answer -> plain chat text (headline, paragraphs, timetable)."""
    lines = [answer.get("headline") or ""]
    lines += [_plain(p) for p in answer.get("paragraphs") or []]
    for row in answer.get("timeline") or []:
        mark = {"passed": "✓", "current": "●"}.get(row["state"], "•")
        when = row["scheduled"] if row["expected"] == row["scheduled"] else f"{row['expected']} (sched {row['scheduled']})"
        why = f" — +{round(row['delay'])} min: {row['why']}" if row.get("why") else ""
        lines.append(f"{mark} {row['station']}: {when}{why}")
    return "\n".join(line for line in lines if line).strip()


def _resolve_train(parsed, board: list[dict]) -> list[dict]:
    if parsed.train_id:
        want = parsed.train_id.casefold()
        rows = [r for r in board if r["train_id"].casefold() == want]
        if not rows:
            try:
                train, _ = resolve_train(parsed.train_id)
                canonical = (train or {}).get("train_id")
                rows = [r for r in board if canonical and r["train_id"] == canonical]
            except Exception:
                rows = []
        return rows
    if parsed.train_number:
        return [r for r in board if r["train_id"] == parsed.train_number
                or r["train_id"].split("-")[-1] == parsed.train_number]
    return [r for r in board if r["train_id"] in parsed.train_name_matches]


def _journey_options(parsed, board: list[dict], day, now: datetime) -> list[dict]:
    """Services on the board that serve origin -> destination inside the time window."""
    today = day == now.date()
    incidents = []
    if today:
        try:
            incidents = MAP_FEED.get().get("incidents", [])
        except Exception:
            incidents = []
    options = []
    for row in board:
        if row["service_status"] == "OUT_OF_SERVICE":
            continue
        f_origin = 0.0
        if parsed.origin:
            f_origin = live_tracker.station_fraction(row, parsed.origin, STATIONS)
            if f_origin is None:
                continue
        f_dest = 1.0
        if parsed.destination:
            f_dest = live_tracker.station_fraction(row, parsed.destination, STATIONS)
            if f_dest is None:
                continue
        if f_dest <= f_origin:
            continue  # wrong direction
        dep = live_tracker.parse_clock(row.get("departure_time"))
        if dep is None:
            continue
        corridor = _corridor_for(row.get("route"), row.get("from_station"), row.get("to_station"))
        run_day_start = datetime.combine(day, dep, tzinfo=live_tracker.LOCAL_TZ)
        # Another day is timed as if seen just before it departs, with no live incidents.
        live = live_tracker.compute_live(
            row, STATIONS, incidents if today else [],
            impact_for=lambda inc, _l, c=corridor: _incident_impact(inc, c),
            now=now if today else run_day_start - timedelta(minutes=1))
        if not live:
            continue
        if datetime.fromisoformat(live["run_start"]).date() != day:
            # an overnight run still finishing from yesterday; list today's departure instead
            live = live_tracker.compute_live(row, STATIONS, [], impact_for=lambda *_: {},
                                             now=run_day_start - timedelta(minutes=1))
        board_at = live_tracker.passage_at(live, f_origin)
        reach = live_tracker.passage_at(live, f_dest)
        clock = board_at["scheduled_dt"].time()
        if parsed.after and clock < parsed.after:
            continue
        if parsed.before and clock > parsed.before:
            continue
        if not parsed.after and not parsed.before and today and board_at["expected_dt"] < now:
            continue  # already left the boarding point
        options.append({"row": row, "live": live, "board": board_at, "reach": reach, "f_dest": f_dest})
    options.sort(key=lambda o: o["board"]["scheduled_dt"])
    return options


def _describe_option(o: dict, parsed, today: bool) -> str:
    row, live, b, r = o["row"], o["live"], o["board"], o["reach"]
    name = _service_label(row)
    board_station = parsed.origin or live["timeline"][0]["station"]
    dest_station = parsed.destination or live["timeline"][-1]["station"]
    text = f"• {name}: leaves {board_station} {b['expected']}, reaches {dest_station} around {r['expected']}"
    if r["delay_minutes"] > 2:
        text += f" (about {r['delay_minutes']} min late"
        reasons = [d for d in live["disruptions"] if d.get("affects_this_run") and d["fraction"] <= o["f_dest"]]
        if reasons:
            text += ": " + ", ".join(f"{passenger_answer._cause(d['incident_type'])} near {d['station']}"
                                     for d in reasons)
        text += ")"
    if row.get("platform"):
        text += f", platform {row['platform']}"
    if today and live["status"] in ("IN_TRANSIT", "AT_STATION"):
        text += f". Running now, between {live['last_station']} and {live['next_station']}"
    return text + "."


def _service_label(row: dict) -> str:
    name = str(row.get("train_name") or "").strip()
    if not name or name.lower().startswith("historical"):
        return f"Train {row['train_id']}"
    return f"{name} ({row['train_id']})"


def _window_text(parsed) -> str:
    fmt = lambda t: t.strftime("%H:%M")
    if parsed.after and parsed.before:
        return f" between {fmt(parsed.after)} and {fmt(parsed.before)}"
    if parsed.after:
        return f" after {fmt(parsed.after)}"
    if parsed.before:
        return f" before {fmt(parsed.before)}"
    return ""


class PassengerQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=400)
    language: Optional[str] = Field(None, max_length=8)


@app.post("/passenger/query")
@limiter.limit("60/minute")
def passenger_query(request: Request, req: PassengerQueryRequest):
    """Free-text operations question from the passenger chat (Choo / M1).

    NLP (nlp/passenger_query.parse): intent, time window, date, stations with
    origin/destination roles, and the train by id, number or name. Data: the
    day's real timetable from Supabase, the live journey (live_tracker) and
    today's verified map incidents, each sized by IR over past incidents.
    Returns handled=false when it isn't an operations question (fares,
    bookings...) so the caller can answer it another way.
    """
    from dataclasses import replace
    from nlp import passenger_query as pq

    question = bleach.clean(req.question, tags=[], strip=True).strip()
    now = live_tracker.local_now()
    try:
        board_today = _board_services(now.date())
    except Exception as exc:
        logger.warning("passenger query: timetable unavailable: %s", exc)
        return {"handled": False, "reason": "timetable_unavailable"}

    names = STATIONS.names() + [r[k] for r in board_today for k in ("from_station", "to_station") if r.get(k)]
    parsed = pq.parse(question, names, board_today)
    parsed.origin = STATIONS.canonical(parsed.origin) if parsed.origin else None
    parsed.destination = STATIONS.canonical(parsed.destination) if parsed.destination else None
    parsed.stations = [STATIONS.canonical(s) for s in parsed.stations]
    base = {"handled": True, "intent": parsed.intent, "entities": {
        "train_id": parsed.train_id or parsed.train_number, "train_name_matches": parsed.train_name_matches,
        "origin": parsed.origin, "destination": parsed.destination, "stations": parsed.stations,
        "after": parsed.after.strftime("%H:%M") if parsed.after else None,
        "before": parsed.before.strftime("%H:%M") if parsed.before else None,
        "day_offset": parsed.day_offset}}
    if parsed.intent == "handoff":
        return {**base, "handled": False, "reason": "booking_or_fare"}
    # Only railway questions: a named train, or railway wording. "Weather in
    # London" or "restaurants in Colombo" are left to the caller's notice.
    railway_words = re.search(r"\b(trains?|rail\w*|station|platform|line|delay\w*|late|services?|arriv\w*|"
                              r"depart\w*|incidents?|alerts?|timetable|schedule|running|night mail)\b",
                              question, re.I)
    if not (parsed.train_id or parsed.train_number or parsed.train_name_matches or railway_words):
        return {**base, "handled": False, "reason": "not_a_railway_question"}

    day = now.date() + timedelta(days=parsed.day_offset)
    try:
        board = board_today if parsed.day_offset == 0 else _board_services(day)
    except Exception:
        return {"handled": False, "reason": "timetable_unavailable"}
    when = "today" if parsed.day_offset == 0 else "tomorrow"

    # 1. A specific train -> the same live answer the popup gives.
    trains = _resolve_train(parsed, board)
    if trains:
        if parsed.stations and len(trains) > 1:
            narrowed = [t for t in trains if all(
                live_tracker.station_fraction(t, s, STATIONS) is not None for s in parsed.stations)]
            trains = narrowed or trains
        answers = []
        for row in trains[:2]:
            intent = "status" if parsed.intent == "greeting" else parsed.intent
            ans = _answer_for_service(question, intent, _service_ctx(row))
            ans.pop("_live_full", None)
            answers.append(ans)
        if len(answers) > 1:
            reply = "\n\n".join(
                f"{_service_label(row)}, {row.get('from_station')} → {row.get('to_station')} "
                f"(departs {str(row.get('departure_time') or '')[:5]}):\n{_answer_text(a)}"
                for row, a in zip(trains, answers))
        else:
            reply = _answer_text(answers[0])
        if len(trains) > 2:
            reply += (f"\n\n{len(trains) - 2} more service(s) share that name {when}; "
                      "ask with the train number for another.")
        return {**base, "kind": "train", "train_ids": [t["train_id"] for t in trains[:2]], "reply": reply,
                "answers": answers, "sources": sorted({s for a in answers for s in a.get("sources", [])})}
    if parsed.train_id or parsed.train_number:
        ref = parsed.train_id or parsed.train_number
        return {**base, "kind": "train_not_running",
                "reply": f"I can't find train {ref} on {when}'s timetable. Check the number, or tell me where "
                         "you're travelling to and I'll list the trains that go there.",
                "sources": [f"{when.capitalize()}'s timetable"]}

    # 2. "Is there a train to X after 19:15?" -> search the timetable.
    if parsed.find_trains:
        options = _journey_options(parsed, board, day, now)
        route_txt = " ".join(filter(None, [f"from {parsed.origin}" if parsed.origin else "",
                                           f"to {parsed.destination}" if parsed.destination else ""]))
        window = _window_text(parsed)
        if options:
            count = f"{len(options)} train{'s' if len(options) > 1 else ''}"
            head = f"Yes, {count} {route_txt} {when}{window}:" if route_txt else f"{count} {when}{window}:"
            lines = [" ".join(head.split())] + [_describe_option(o, parsed, parsed.day_offset == 0)
                                                 for o in options[:5]]
            if len(options) > 5:
                lines.append(f"…and {len(options) - 5} more.")
            lines.append("Times at stations between the first and last stop are estimated from distance "
                         "along the line" + ("; they include today's verified delays." if parsed.day_offset == 0
                                             else "."))
        else:
            lines = [" ".join(f"There's no train {route_txt} {when}{window} on the timetable.".split())]
            if parsed.day_offset == 0:
                try:
                    tomorrow = now.date() + timedelta(days=1)
                    nxt = _journey_options(replace(parsed, after=None, before=None),
                                           _board_services(tomorrow), tomorrow, now)
                except Exception:
                    nxt = []
                if nxt:
                    lines.append("The first options tomorrow:")
                    lines += [_describe_option(o, parsed, False) for o in nxt[:3]]
        return {**base, "kind": "journey_search", "reply": "\n".join(lines),
                "options": [{"train_id": o["row"]["train_id"], "train_name": o["row"].get("train_name"),
                             "board_time": o["board"]["expected"], "arrival_time": o["reach"]["expected"],
                             "delay_minutes": o["reach"]["delay_minutes"]} for o in options[:10]],
                "sources": [f"{when.capitalize()}'s timetable", "Live position", "Verified incident map"]}

    # 3. Incidents / alerts on the network or on a named line.
    if parsed.intent in ("incidents", "reason"):
        feed = MAP_FEED.get().get("incidents", [])
        if parsed.stations:
            lines_with = [set(stations) for stations in live_tracker.CORRIDOR_STATIONS.values()
                          if any(s in stations for s in parsed.stations)]
            feed = [i for i in feed if i.get("station") in parsed.stations
                    or any(i.get("station") in line for line in lines_with)]
        where = f" on the line through {', '.join(parsed.stations)}" if parsed.stations else " on the network"
        if not feed:
            reply = f"No verified incidents{where} today, so trains there are running to their normal schedule."
        else:
            out = [f"{len(feed)} verified incident{'s' if len(feed) > 1 else ''}{where} today:"]
            for inc in feed[:6]:
                impact = _incident_impact(inc, _route_for_station(inc.get("station")))
                extra = (f"; similar past incidents held trains about {impact['minutes']:.0f} min"
                         if impact["minutes"] else "")
                out.append(f"• {passenger_answer._cause(inc.get('incident_type')).capitalize()} at "
                           f"{inc.get('station')}{extra}. {inc.get('summary') or ''}".strip())
            reply = "\n".join(out)
        return {**base, "kind": "incidents", "reply": reply,
                "sources": ["Verified incident map", "Similar past incidents (IR)"]}

    # 4. "Which trains are delayed / running now?" -> network overview from live journeys.
    if parsed.delay_overview or (parsed.intent in ("delay", "location", "status") and not parsed.stations):
        running, delayed = [], []
        for row in board_today:
            if row["service_status"] == "OUT_OF_SERVICE":
                continue
            ans = _answer_for_service("status", "status", _service_ctx(row))
            live = ans.get("_live_full")
            if not live:
                continue
            label = _service_label(row)
            dest = live["timeline"][-1]["station"]
            if live["status"] in ("IN_TRANSIT", "AT_STATION"):
                where = (f"at {live['at_station']}" if live["at_station"]
                         else f"between {live['last_station']} and {live['next_station']}")
                running.append(f"• {label}: {where}, due at {dest} {live['expected_arrival']}")
            if live["status"] != "ARRIVED" and live["delay_minutes"] > 2:
                delayed.append(f"• {label}: about {live['delay_minutes']} min late, expected at {dest} "
                               f"{live['expected_arrival']}")
        parts = [(f"It's {now.strftime('%H:%M')}. Trains running right now:\n" + "\n".join(running))
                 if running else f"It's {now.strftime('%H:%M')} and no train is on the move right now."]
        parts.append(("Expected to run late:\n" + "\n".join(delayed)) if delayed else
                     "No train still to run today is expected to be more than a couple of minutes late.")
        asks_position = any(k in question.casefold() for k in ("running now", "right now", "on the move",
                                                                  "currently", "where are"))
        if (parsed.delay_overview or parsed.intent == "delay") and not asks_position:
            parts.reverse()
        reply = "\n".join(parts)
        reply += "\nAsk about one train by name or number (e.g. \"where is the Night Mail?\") for its full timetable."
        return {**base, "kind": "overview", "reply": reply,
                "sources": ["Today's timetable", "Live position", "RailSense delay model", "Verified incident map"]}

    return {**base, "handled": False, "reason": "not_an_operations_question"}


def _compute_prediction(req: DelayPredictionRequest) -> DelayPredictionResponse:
    """Pure prediction: no Hub alert, no audit, no in-memory log.

    Shared by POST /predict-delay (which adds those side effects) and the
    admin Operations Assistant, whose questions must never broadcast a
    delay_alert to the other agents.

    Phase 2: serves predictions from the trained GradientBoostingRegressor
    (ml/train_delay_model.py), with feature importances attached.

    Falls back to a labelled heuristic only if delay_model.pkl hasn't been
    trained yet, so the endpoint never hard-fails during setup.

    Phase 4: retrieves similar historical incidents and composes a grounded
    explanation. The local TF-IDF index is always available; configured
    Supabase pgvector and Anthropic credentials are used automatically.
    """
    canonical_train = _canonical_train_or_error(req.train_id)
    # Everything downstream - the operations-history lookup, the explanation
    # text and the response body - must speak the registry's own id, not the
    # shorthand the passenger happened to type. Without this, "4082" would
    # miss every PM-4082 row in HISTORY and the reply would quote a train id
    # that no other agent can resolve.
    req.train_id = canonical_train.get("train_id") or req.train_id
    query_parts = [req.route]
    if req.station:
        query_parts.append(req.station)
    if req.weather:
        query_parts.append(req.weather.value)
    if req.incident_type and req.incident_type != IncidentType.none:
        query_parts.append(req.incident_type.value.replace("_", " "))
    historical_train = _find_historical_train(req.train_id, req.route)
    if historical_train:
        observed_delay = round(float(historical_train.get("delay_minutes", 0)), 1)
        incident_note = str(historical_train.get("incident_note", "")).strip()
        citations = incident_retriever.format_incident_citations([historical_train])
        explanation = (
            f"Historical observation for {req.train_id}: {observed_delay} minutes on "
            f"{req.route}."
        )
        if incident_note:
            explanation += f" Recorded operational cause: {incident_note}"
        response = DelayPredictionResponse(
            route=req.route,
            train_id=req.train_id,
            predicted_delay_minutes=observed_delay,
            confidence="high",
            explanation=explanation,
            top_contributing_features=[
                {"feature": "historical_train_observation", "importance": 1.0}
            ],
            similar_past_incidents=citations,
            model_version="historical-observation-v1",
            retrieval_method="historical_record",
            explanation_method="historical_record",
        )
        return response

    retrieval = incident_retriever.retrieve_similar_incidents(
        " ".join(query_parts),
        top_k=3,
        route=req.route,
        station=req.station,
        incident_type=req.incident_type.value if req.incident_type else None,
    )
    incidents = retrieval["incidents"]
    citations = incident_retriever.format_incident_citations(incidents)
    prefer_llm = bool(__import__("os").getenv("ANTHROPIC_API_KEY"))

    if not delay_model.is_model_available():
        baseline, historical_sample_size = _historical_delay_estimate(
            req.route,
            req.scheduled_time,
            req.station,
            req.weather,
            req.day_type,
            req.incident_type,
        )

        grounded = explanation_layer.compose_explanation(
            req.route, baseline, [], incidents, prefer_llm=prefer_llm
        )
        response = DelayPredictionResponse(
            route=req.route,
            train_id=req.train_id,
            predicted_delay_minutes=round(baseline, 1),
            confidence="low" if historical_sample_size < 10 else "medium",
            explanation=grounded["explanation"],
            top_contributing_features=[],
            similar_past_incidents=citations,
            model_version="historical-median-v1",
            retrieval_method=retrieval["method"],
            explanation_method=grounded["method"],
        )
        return response

    result = delay_model.predict_delay(
        route=req.route,
        scheduled_hour=req.scheduled_time.hour,
        weather=req.weather.value if req.weather else None,
        day_type=req.day_type.value if req.day_type else None,
        station=req.station,
        incident_type=req.incident_type.value if req.incident_type else None,
    )

    top_features = result["top_features"]
    grounded = explanation_layer.compose_explanation(
        req.route,
        result["predicted_delay_minutes"],
        top_features,
        incidents,
        prefer_llm=prefer_llm,
    )

    confidence = "medium" if abs(result["predicted_delay_minutes"]) < 20 else "low"

    response = DelayPredictionResponse(
        route=req.route,
        train_id=req.train_id,
        predicted_delay_minutes=result["predicted_delay_minutes"],
        confidence=confidence,
        explanation=grounded["explanation"],
        top_contributing_features=top_features,
        similar_past_incidents=citations,
        model_version=result["model_version"],
        retrieval_method=retrieval["method"],
        explanation_method=grounded["method"],
    )
    return response


@app.post("/predict-delay", response_model=DelayPredictionResponse)
@limiter.limit("30/minute")
async def predict_delay(request: Request, req: DelayPredictionRequest):
    """Delay prediction with its operational side effects (Hub alert + audit)."""
    response = _compute_prediction(req)
    _predictions.append(response.model_dump())
    _start_prediction_side_effects(
        request, response.route, response.train_id,
        response.predicted_delay_minutes, response.model_version,
    )
    return response


@app.get("/route-status/{route_id}", response_model=RouteStatusResponse)
def route_status(route_id: str):
    if not route_id or len(route_id) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid route_id")
    matching = [row for row in HISTORY if row.get("route", "").casefold() == route_id.casefold()]
    delays = [float(row.get("delay_minutes", 0)) for row in matching]
    average = sum(delays) / len(delays) if delays else 0
    return RouteStatusResponse(
        route_id=route_id,
        status="critical" if average >= 10 else "watch" if average >= 5 else "normal",
        active_trains=len({row.get("train_id") for row in matching}),
        average_delay_minutes=round(average, 1),
        last_updated=datetime.now(timezone.utc),
    )


@app.post("/incident-report", response_model=IncidentReportResponse)
def incident_report(request: Request, req: IncidentReportRequest):
    """
    Phase 3: runs real summarization + classification on the sanitized
    incident text.

    Uses a rule-based baseline by default (deterministic, no API cost,
    directly evaluable against the dataset's ground-truth incident_type
    labels — see nlp/evaluate_nlp.py). If ANTHROPIC_API_KEY is set, an
    LLM-based mode is available (not the default here, to keep this
    endpoint fast/free for iteration — Phase 4 is where the LLM becomes
    central, for the explanation layer).

    The request/response contract is unchanged. What is new behind it: the
    row is persisted through admin_db (Supabase primary, local JSONL
    fallback) instead of Supabase-only, and the incident is fed into the
    embeddings pipeline so RAG can retrieve it as precedent from now on.
    """
    classification = incident_classifier.classify_incident(req.raw_text)
    summarization = incident_summarizer.summarize_incident(req.raw_text)

    response = IncidentReportResponse(
        incident_id=str(uuid.uuid4()),
        train_id=req.train_id,
        station=req.station,
        summary=summarization["summary"],
        classified_type=classification["classified_type"],
        nlp_method=classification["method"],
        received_at=datetime.now(timezone.utc),
    )

    stored = admin_db.create_incident({
        "incident_id": response.incident_id,
        "train_id": response.train_id,
        "station": response.station,
        "raw_text": req.raw_text,
        "summary": response.summary,
        "classified_type": response.classified_type,
        "nlp_method": response.nlp_method,
        "review_status": "pending",
        "received_at": response.received_at.isoformat(),
    })

    _index_incident_for_retrieval({
        "record_id": response.incident_id,
        "route": _route_for_station(response.station),
        "station": response.station,
        "incident_type": response.classified_type,
        "delay_minutes": 0.0,
        "incident_note": req.raw_text,
    })

    _audit("incident_report", request, {
        "incident_id": response.incident_id,
        "train_id": req.train_id,
        "station": req.station,
        "classified_type": response.classified_type,
        "nlp_method": response.nlp_method,
        "intent": "incident_triage",
        "outcome": f"created:{stored['source']}",
    })
    return response


@app.get("/incidents")
def list_incidents(
    request: Request,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    review_status: Optional[str] = None,
    classified_type: Optional[str] = None,
    search: Optional[str] = None,
):
    """Paginated live read of triaged incidents for the Incident Management screen.

    Additive to the API surface — POST /incident-report is untouched. Rows
    come from Supabase `incident_reports` when reachable and the local JSONL
    mirror otherwise; `offline` drives the UI's offline-mode banner.
    """
    result = admin_db.list_incidents(
        limit=limit,
        offset=offset,
        review_status=review_status,
        classified_type=classified_type,
        search=search,
    )
    return {
        "rows": result["rows"],
        "count": result["count"],
        "limit": limit,
        "offset": offset,
        "source": result["source"],
        "offline": result["source"] != "supabase",
    }


class IncidentUpdateRequest(BaseModel):
    """Controller correction to a triaged incident. Both fields are optional."""

    classified_type: Optional[IncidentClassification] = None
    summary: Optional[str] = Field(None, min_length=3, max_length=600)
    review_status: Optional[ReviewStatus] = None

    @field_validator("summary")
    @classmethod
    def sanitize_summary(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip()
        if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value):
            raise ValueError("summary contains invalid control characters")
        cleaned = bleach.clean(value, tags=[], attributes={}, protocols=[], strip=True, strip_comments=True)
        if cleaned != value:
            raise ValueError("summary contains disallowed markup")
        return cleaned


# ---------------------------------------------------------------------------
# Incident map: admin review workflow + verified-only public feed
# ---------------------------------------------------------------------------

MAP_FEED = incident_map.MapFeed(
    lambda: admin_db.list_incidents(limit=500, review_status=incident_map.VERIFIED)
)


def _review_incident(request: Request, incident_id: str, officer: dict, decision: str) -> dict:
    existing = admin_db.get_incident(incident_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"INCIDENT_NOT_FOUND: {incident_id}")
    now = datetime.now(timezone.utc)
    patch = {
        "review_status": decision,
        "reviewed_by": officer.get("email") or officer.get("name") or officer.get("sub"),
        "reviewed_at": now.timestamp(),
        "verified_at": now.isoformat() if decision == incident_map.VERIFIED else None,
    }
    result = admin_db.update_incident(incident_id, patch)
    if result["row"] is None:
        raise HTTPException(status_code=500, detail=result.get("error", "incident review failed"))
    MAP_FEED.invalidate()
    mapped_station = incident_map.canonical_station(existing.get("station"))
    _audit(f"incident_{'approve' if decision == incident_map.VERIFIED else 'reject'}", request, {
        "incident_id": incident_id,
        "reviewed_by": patch["reviewed_by"],
        "intent": "incident_review",
        "outcome": f"{decision}:{result['source']}",
    })
    return {
        "incident": result["row"],
        "source": result["source"],
        "offline": result["source"] != "supabase",
        "write_error": result.get("error"),
        # Tells the reviewer when an approval cannot be placed on the map.
        "mapped": decision == incident_map.VERIFIED and mapped_station is not None,
        "station": mapped_station or existing.get("station"),
    }


@app.post("/incidents/{incident_id}/approve")
def approve_incident(request: Request, incident_id: str,
                     officer: dict = Depends(require_permission("m2.incidents.review"))):
    """Admin approval: PENDING/corrected -> VERIFIED, which publishes it to the map."""
    return _review_incident(request, incident_id, officer, incident_map.VERIFIED)


@app.post("/incidents/{incident_id}/reject")
def reject_incident(request: Request, incident_id: str,
                    officer: dict = Depends(require_permission("m2.incidents.review"))):
    """Admin rejection: the incident never appears on any map."""
    return _review_incident(request, incident_id, officer, "rejected")


@app.get("/api/incidents/map-feed")
def incident_map_feed(response: Response):
    """VERIFIED incidents only, allowlisted fields only (safe for passengers).

    Polled every ~5 s by all three maps. Never raises: when the incident store
    is unreachable the last known feed is returned with stale=true.
    """
    response.headers["Cache-Control"] = "no-store"
    return MAP_FEED.get()


_TRAIN_CATALOG: dict = {"at": 0.0, "payload": None}
TRAIN_CATALOG_TTL_SECONDS = 300


def _registry_trains() -> list[dict]:
    """Active trains from the shared canonical registry (read-only)."""
    from shared import train_repository
    client = train_repository.get_client()
    rows, start = [], 0
    while True:
        page = (client.table("trains")
                .select("train_id,train_name,route,origin_station,destination_station,active")
                .eq("active", True).range(start, start + 999).execute().data or [])
        rows.extend(page)
        if len(page) < 1000:
            return rows
        start += 1000


def _build_train_catalog() -> dict:
    """Train picker data: id, human name and the stations each train serves.

    Registry rows seeded from the operations corpus carry placeholder names
    ("Historical IC-1036"); those are sent with name=None so the picker leads
    with real service names (Podi Menike, Yal Devi Express…) people remember.
    """
    source = "registry"
    try:
        trains = _registry_trains()
    except Exception as exc:
        logger.warning("train registry unavailable for picker, using corpus: %s", exc)
        source = "local_corpus"
        from shared import train_repository
        trains = list(train_repository._LOCAL_TRAINS.values())
        known = {t["train_id"] for t in trains}
        for row in HISTORY:
            if row.get("train_id") and row["train_id"] not in known:
                known.add(row["train_id"])
                trains.append({"train_id": row["train_id"], "train_name": None, "route": row.get("route")})

    # Stations are sent once per corridor, not repeated on ~3,000 trains.
    corridor_stations = {o["route"]: o["stations"] for o in _route_options(HISTORY)}

    catalog = []
    for t in trains:
        train_id = str(t.get("train_id") or "").strip()
        if not train_id:
            continue
        name = (t.get("train_name") or "").strip() or None
        if name and name.lower().startswith("historical "):
            name = None
        corridor = _corridor_for(t.get("route"), t.get("origin_station"), t.get("destination_station"))
        item = {"train_id": train_id, "name": name, "route": t.get("route") or corridor}
        if corridor and corridor != item["route"]:
            item["corridor"] = corridor  # e.g. "Colombo - Badulla" -> "Colombo Fort - Badulla"
        catalog.append(item)
    catalog.sort(key=lambda t: (t["name"] is None, (t["name"] or "").lower(), t["train_id"]))
    return {"source": source, "corridor_stations": corridor_stations, "trains": catalog}


@app.get("/api/trains")
def train_catalog():
    """Trains for the incident form's picker (named services first)."""
    now = datetime.now(timezone.utc).timestamp()
    if _TRAIN_CATALOG["payload"] is None or now - _TRAIN_CATALOG["at"] > TRAIN_CATALOG_TTL_SECONDS:
        _TRAIN_CATALOG["payload"] = _build_train_catalog()
        _TRAIN_CATALOG["at"] = now
    return _TRAIN_CATALOG["payload"]


@app.get("/api/stations")
def stations():
    """Corpus stations with map coordinates (incident form + map bounds)."""
    return {"stations": incident_map.station_list()}


@app.patch("/incidents/{incident_id}")
def update_incident(request: Request, incident_id: str, req: IncidentUpdateRequest):
    """Write a controller's correction back to the incident's DB row."""
    patch = {k: v for k, v in req.model_dump(exclude_none=True).items()}
    if not patch:
        raise HTTPException(status_code=400, detail="no fields supplied to update")
    patch = {k: (v.value if isinstance(v, Enum) else v) for k, v in patch.items()}
    patch.setdefault("review_status", "corrected")
    # ReviewStatus cannot be "verified", so any edit takes a verified incident
    # off the public map until an administrator approves the corrected text.
    patch["verified_at"] = None
    # incident_reports.reviewed_at is `double precision` (see admin/admin_schema.sql),
    # so this must be a Unix timestamp — an ISO string makes Postgres reject the whole
    # update, which would silently demote the write to the local fallback store.
    patch["reviewed_at"] = datetime.now(timezone.utc).timestamp()

    existing = admin_db.get_incident(incident_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"INCIDENT_NOT_FOUND: {incident_id}")

    result = admin_db.update_incident(incident_id, patch)
    if result["row"] is None:
        raise HTTPException(status_code=500, detail=result.get("error", "incident update failed"))
    MAP_FEED.invalidate()

    # Keep the retrieval corpus consistent with the corrected classification.
    _index_incident_for_retrieval({
        "record_id": incident_id,
        "route": _route_for_station(result["row"].get("station")),
        "station": result["row"].get("station"),
        "incident_type": result["row"].get("classified_type"),
        "delay_minutes": 0.0,
        "incident_note": result["row"].get("raw_text") or result["row"].get("summary") or "",
    })

    _audit("incident_update", request, {
        "incident_id": incident_id,
        "changed_fields": sorted(patch.keys()),
        "classified_type": result["row"].get("classified_type"),
        "intent": "incident_correction",
        "outcome": f"updated:{result['source']}",
    })
    return {
        "incident": result["row"],
        "source": result["source"],
        "offline": result["source"] != "supabase",
        # Set when Supabase was reachable but rejected the write, so the UI can
        # say "rejected" instead of mislabelling it as offline mode.
        "write_error": result.get("error"),
    }


@app.delete("/incidents/{incident_id}")
def delete_incident(request: Request, incident_id: str):
    """Delete an incident and its embedding, so RAG never cites a ghost record."""
    existing = admin_db.get_incident(incident_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"INCIDENT_NOT_FOUND: {incident_id}")

    result = admin_db.delete_incident(incident_id)
    if not result["deleted"]:
        raise HTTPException(status_code=500, detail="incident delete failed")
    MAP_FEED.invalidate()

    embedding_result = _unindex_incident(incident_id)

    _audit("incident_delete", request, {
        "incident_id": incident_id,
        "classified_type": existing.get("classified_type"),
        "embedding_removed": embedding_result,
        "intent": "incident_deletion",
        "outcome": f"deleted:{result['source']}",
    })
    return {
        "deleted": incident_id,
        "source": result["source"],
        "embedding_removed": embedding_result,
        "offline": result["source"] != "supabase",
    }


@app.post("/hub/message")
async def hub_message(request: Request, message: HubMessage):
    """Receive a Passenger Agent delay_check through the shared Hub."""
    if message.intent != "delay_check":
        raise HTTPException(status_code=400, detail="unsupported hub intent")
    payload = message.payload or {}
    
    raw_text = str(payload.get("raw_text", ""))

    # Resolve the train identifier, keeping the anti-fabrication guard: M2 only
    # answers for a train the passenger's own words actually name, never for a
    # placeholder an upstream fallback invented.
    #
    # Two accepted forms, because the canonical registry holds both conventions:
    #   1. Prefixed ids seeded from operations history -> PM-8056, IC-8746
    #   2. Bare Sri Lanka Railways service numbers     -> 4085, 50, 1005
    # A bare number is too ambiguous to pattern-match out of free text (it would
    # also catch times, seat counts and dates), so it is accepted only when the
    # caller supplied that exact id AND it appears as a standalone token in the
    # passenger's text - the same "evidenced in raw_text" rule as before.
    train_id = payload.get("train_id")
    import re

    match = re.search(r"\b[A-Z]{2,12}-\d{3,5}\b", raw_text, re.IGNORECASE)
    if match:
        train_id = match.group(0)
    else:
        supplied = str(train_id).strip() if train_id else ""
        evidenced = bool(
            supplied
            and re.search(rf"(?<![\w-]){re.escape(supplied)}(?![\w-])", raw_text, re.IGNORECASE)
        )
        if not evidenced:
            raise HTTPException(status_code=422, detail="delay_check requires a train identifier")
        train_id = supplied

    # Resolved before the route so the registry's own route can stand in when
    # the passenger named a train but no stations ("delay of 4082 train"). This
    # also surfaces an unknown/ambiguous id as a 404/409 the passenger can act
    # on, instead of the confusing "requires a route" 422 that used to come
    # first for a question that clearly named its train.
    canonical_train = _canonical_train_or_error(train_id)
    train_id = canonical_train.get("train_id") or train_id

    # Prefer entities in the original passenger text so M2 never answers for a
    # fabricated route or train supplied by an upstream fallback.
    route = payload.get("route")
    stations = payload.get("stations")
    if isinstance(stations, list):
        stations = [str(item).strip() for item in stations if str(item).strip()]
    else:
        stations = []
    known_stations = sorted(
        {station for row in HISTORY for station in (row.get("route", "").split(" - ")) if station},
        key=len,
        reverse=True,
    )
    text_stations = [station for station in known_stations if station.casefold() in raw_text.casefold()]
    route_stations = text_stations[:2] if len(text_stations) >= 2 else stations[:2]
    if len(route_stations) >= 2:
        route = f"{route_stations[0]} - {route_stations[1]}"
    if not route or not str(route).strip():
        # Not a guess: this is the route the shared registry records for the
        # very train the passenger named.
        route = canonical_train.get("route") or ""
        if not str(route).strip():
            origin = canonical_train.get("origin_station")
            destination = canonical_train.get("destination_station")
            if origin and destination:
                route = f"{origin} - {destination}"
    if not route or not str(route).strip():
        raise HTTPException(status_code=422, detail="delay_check requires a route with origin and destination")

    scheduled_time = payload.get("scheduled_time")
    if not scheduled_time and payload.get("time"):
        try:
            scheduled_time = datetime.combine(
                datetime.now(timezone.utc).date(),
                datetime.strptime(str(payload["time"]), "%H:%M").time(),
                tzinfo=timezone.utc,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="time must use HH:MM format") from exc
    scheduled_time = scheduled_time or datetime.now(timezone.utc)
    if isinstance(scheduled_time, str):
        try:
            scheduled_time = datetime.fromisoformat(scheduled_time.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="scheduled_time must be ISO-8601") from exc
    day_type = payload.get("day_type") or ("weekend" if scheduled_time.weekday() >= 5 else "weekday")

    try:
        prediction_request = DelayPredictionRequest(
            route=route,
            train_id=train_id,
            scheduled_time=scheduled_time,
            weather=payload.get("weather"),
            day_type=day_type,
            station=payload.get("station"),
            incident_type=payload.get("incident_type", "none"),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid delay_check payload: {exc}") from exc

    response = await predict_delay(request, prediction_request)
    resp_dict = response.model_dump()
    resp_dict["reason"] = response.explanation
    resp_dict["similar_incident"] = (
        response.similar_past_incidents[0]
        if response.similar_past_incidents
        else "No historical incident precedent"
    )

    result = {
        "message_id": message.message_id or uuid.uuid4().hex,
        "sender_agent": AGENT_NAME,
        "receiver_agent": message.sender_agent,
        "intent": "delay_check_response",
        "payload": resp_dict,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _audit(
        "hub_delay_check",
        request,
        {
            "sender_agent": message.sender_agent,
            "route": prediction_request.route,
            "train_id": prediction_request.train_id,
            "delay": response.predicted_delay_minutes,
        },
    )
    return result


# ---------------------------------------------------------------------------
# Admin Operations Assistant (floating chatbot in the Admin Console)
# ---------------------------------------------------------------------------
import ops_agent  # noqa: E402
from ops_agent_tools import build_tools  # noqa: E402

_OPS_TOOLS, _ops_known_routes, _ops_coverage = build_tools(sys.modules[__name__])
OPS_AGENT = ops_agent.OpsAgent(_OPS_TOOLS, _ops_known_routes, coverage=_ops_coverage)
OPS_HISTORY = ops_agent.QueryHistory(admin_db.get_client)


class OpsAgentAskRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)
    # Accepted for API compatibility only: identity always comes from the
    # signed officer token, so one admin can never write another's history.
    session_user_id: Optional[str] = Field(None, max_length=120)


def _officer_id(officer: dict) -> str:
    return str(officer.get("sub") or officer.get("email") or "unknown")


def _officer_access(officer: dict) -> tuple[str, set[str]]:
    role = officer.get("role", "")
    return role, set(get_permissions_for_role(role))


@app.get("/api/ops-agent/capabilities")
def ops_agent_capabilities(officer: dict = Depends(require_permission("m2.assistant.use"))):
    """What this officer's role may ask; the widget uses it for examples and help."""
    role, permissions = _officer_access(officer)
    return {"role": role, "role_display": ROLE_DISPLAY_NAMES.get(role, role),
            **OPS_AGENT.capabilities(permissions)}


@app.post("/api/ops-agent/ask")
@limiter.limit("20/minute")
def ops_agent_ask(request: Request, req: OpsAgentAskRequest,
                  officer: dict = Depends(require_permission("m2.assistant.use"))):
    """Answer an officer's question by calling M2's own data tools (never free-form).

    The tools offered to the model are filtered by the officer's role, so an
    operations engineer asking about admin-only data gets a clear
    "restricted" reply instead of an answer.
    """
    user_id = _officer_id(officer)
    if req.session_user_id and req.session_user_id != user_id:
        raise HTTPException(status_code=403, detail="session_user_id does not match the signed-in officer")
    question = bleach.clean(req.question, tags=[], strip=True).strip()
    if len(question) < 2:
        raise HTTPException(status_code=400, detail="question is empty")

    role, permissions = _officer_access(officer)
    result = OPS_AGENT.ask(question, permissions=permissions, role=role)
    stored = OPS_HISTORY.record(user_id, question, result)
    _audit("ops_agent_query", request, {
        "admin_user_id": user_id,
        "tools": [c["tool"] for c in result["tool_calls_made"]],
        "answer_method": result["answer_method"],
        "answer_type": result["answer_type"],
        "role": role,
        "intent": "ops_agent_query",
        "outcome": f"answered:{stored['stored']}",
    })
    return {**result, "id": stored["row"]["id"], "question": question,
            "created_at": stored["row"]["created_at"], "stored": stored["stored"]}


@app.get("/api/ops-agent/history")
def ops_agent_history(user_id: Optional[str] = None,
                      limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                      officer: dict = Depends(require_permission("m2.assistant.use"))):
    """This officer's own past questions, newest first (feeds the history rail)."""
    own_id = _officer_id(officer)
    if user_id and user_id != own_id:
        raise HTTPException(status_code=403, detail="History is private to each officer")
    return OPS_HISTORY.list(own_id, limit=limit, offset=offset)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8005"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
