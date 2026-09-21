"""RailSense Operations Agent: prediction, triage, hub and dashboard APIs.

Endpoints:
    GET  /health              -> liveness check
    POST /predict-delay       -> delay prediction (stubbed until Phase 2 ML model lands)
    GET  /route-status/{id}   -> latest known status for a route
    POST /incident-report     -> summarize and classify a raw staff incident report

"""

from datetime import datetime, timezone
from enum import Enum
from collections import Counter
from contextlib import asynccontextmanager
import csv
import json
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

from fastapi import FastAPI, HTTPException, Query, Request, status
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
from rag import explanation as explanation_layer
from rag import incident_retriever
import hub_client
import supabase_store
from admin import admin_db
from admin.admin_router import router as admin_router
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


@app.post("/predict-delay", response_model=DelayPredictionResponse)
@limiter.limit("30/minute")
async def predict_delay(request: Request, req: DelayPredictionRequest):
    """
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
        _predictions.append(response.model_dump())
        _start_prediction_side_effects(
            request, req.route, req.train_id, observed_delay, response.model_version
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
        _predictions.append(response.model_dump())
        _start_prediction_side_effects(
            request,
            req.route,
            req.train_id,
            response.predicted_delay_minutes,
            response.model_version,
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
    _predictions.append(response.model_dump())
    _start_prediction_side_effects(
        request,
        req.route,
        req.train_id,
        response.predicted_delay_minutes,
        response.model_version,
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


@app.patch("/incidents/{incident_id}")
def update_incident(request: Request, incident_id: str, req: IncidentUpdateRequest):
    """Write a controller's correction back to the incident's DB row."""
    patch = {k: v for k, v in req.model_dump(exclude_none=True).items()}
    if not patch:
        raise HTTPException(status_code=400, detail="no fields supplied to update")
    patch = {k: (v.value if isinstance(v, Enum) else v) for k, v in patch.items()}
    patch.setdefault("review_status", "corrected")
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


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8005"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
