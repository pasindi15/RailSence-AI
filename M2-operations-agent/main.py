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
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
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

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("railsense.operations")
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])


@asynccontextmanager
async def lifespan(_app):
    try:
        await hub_client.register_with_hub()
        logger.info("Registered with agent Hub")
    except Exception as exc:
        logger.warning("Hub unavailable during startup: %s", exc)
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
app.add_middleware(SlowAPIMiddleware)


async def rate_limit_handler(request, exc):
    return __import__("fastapi").responses.JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

AGENT_NAME = "operations-agent"
UI_PATH = Path(__file__).parent / "ui" / "index.html"
DATA_PATH = Path(__file__).parent / "data" / "operations_history.csv"
AUDIT_PATH = Path(__file__).parent / "data" / "audit_log.jsonl"
_predictions: list[dict] = []
_incidents: list[dict] = []
_events: list[dict] = []
OPERATION_TYPES = ("trains", "incidents", "risk_zones", "crossings", "alerts", "dispatch_actions")
_operation_store: dict[str, list[dict]] = {
    "trains": [
        {"id": "PM-8056", "name": "Podi Menike", "route": "Colombo Fort - Badulla", "station": "Rambukkana", "lat": 7.254, "lng": 80.403, "speed": 42, "eta": "18:42", "delay": 9, "risk": 78, "status": "watch"},
        {"id": "IC-1001", "name": "Intercity Express", "route": "Colombo Fort - Kandy", "station": "Kadugannawa", "lat": 7.254, "lng": 80.527, "speed": 61, "eta": "18:28", "delay": 2, "risk": 32, "status": "normal"},
        {"id": "DM-8055", "name": "Night Mail", "route": "Colombo Fort - Batticaloa", "station": "Habarana", "lat": 8.034, "lng": 80.752, "speed": 38, "eta": "21:14", "delay": 12, "risk": 86, "status": "critical"},
    ],
    "incidents": [
        {"id": "INC-2408", "type": "wildlife", "title": "Wildlife activity near line", "location": "Habarana - Minneriya", "train_id": "DM-8055", "severity": "critical", "status": "open", "impact": 18, "time": "21:14", "note": "Historical elephant movement during evening hours."},
        {"id": "INC-2407", "type": "person_on_track", "title": "Person reported beside track", "location": "Kelaniya", "train_id": "PM-8056", "severity": "high", "status": "investigating", "impact": 12, "time": "18:09", "note": "Driver alerted; next section held for verification."},
        {"id": "INC-2406", "type": "flood", "title": "Heavy rain and waterlogging", "location": "Kalutara South", "train_id": "UD-8050", "severity": "medium", "status": "monitoring", "impact": 14, "time": "17:52", "note": "Speed restriction active through the low-lying section."},
    ],
    "risk_zones": [
        {"id": "RZ-01", "name": "Habarana wildlife corridor", "kind": "wildlife", "location": "Habarana - Minneriya", "score": 86, "level": "high", "lat": 8.034, "lng": 80.752, "evidence": "17 historical sightings · 19:00-23:00"},
        {"id": "RZ-02", "name": "Kalutara flood plain", "kind": "flood", "location": "Kalutara - Aluthgama", "score": 71, "level": "high", "lat": 6.585, "lng": 79.96, "evidence": "Heavy rain · low-lying track bed"},
        {"id": "RZ-03", "name": "Kelaniya trespass corridor", "kind": "people", "location": "Kelaniya", "score": 64, "level": "watch", "lat": 6.968, "lng": 79.887, "evidence": "Repeated reports near station approaches"},
    ],
    "crossings": [
        {"id": "LC-042", "location": "Gampaha", "status": "high_risk", "vehicles": 23, "train_eta": "02:14", "risk": 82, "gate": "closed", "pedestrians": 4},
        {"id": "LC-018", "location": "Ragama", "status": "normal", "vehicles": 11, "train_eta": "08:40", "risk": 27, "gate": "open", "pedestrians": 1},
        {"id": "LC-067", "location": "Polgahawela", "status": "fault", "vehicles": 18, "train_eta": "04:05", "risk": 74, "gate": "manual", "pedestrians": 7},
    ],
    "alerts": [
        {"id": "ALT-901", "title": "Wildlife risk: Night Mail 8055", "location": "Habarana", "severity": "critical", "status": "active", "age": "2 min", "action": "Reduce speed and notify driver"},
        {"id": "ALT-900", "title": "Flood probability 71%", "location": "Kalutara", "severity": "high", "status": "acknowledged", "age": "8 min", "action": "Maintain 40 km/h restriction"},
        {"id": "ALT-899", "title": "Level crossing malfunction", "location": "Polgahawela", "severity": "medium", "status": "active", "age": "12 min", "action": "Dispatch crossing team"},
    ],
    "dispatch_actions": [
        {"id": "ACT-100", "action": "Alert driver", "owner": "Control desk", "target": "DM-8055", "status": "queued", "priority": "critical", "created": "21:14"},
        {"id": "ACT-099", "action": "Notify station master", "owner": "Operations", "target": "Habarana", "status": "sent", "priority": "high", "created": "21:12"},
    ],
}


def _load_history() -> list[dict]:
    if not DATA_PATH.exists():
        return []
    with DATA_PATH.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


HISTORY = _load_history()


def _audit(action: str, request: Request, details: dict) -> None:
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "action": action, "client": get_remote_address(request), **details}
    try:
        with AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning("Could not write audit record: %s", exc)
    if not supabase_store.insert_audit(action, get_remote_address(request), details):
        logger.info("Supabase audit unavailable; retained local audit record")


def _record_event(event: dict, destinations: list[str]) -> None:
    _events.append(event | {"published": bool(destinations), "destinations": destinations})
    if not supabase_store.insert_event(event, destinations):
        logger.info("Supabase events unavailable; retained in-memory event")


def _metric_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _operations_payload() -> dict[str, list[dict]]:
    result = {}
    for entity_type in OPERATION_TYPES:
        result[entity_type] = supabase_store.fetch_entities(entity_type)
        if result[entity_type] is None:
            result[entity_type] = list(_operation_store[entity_type])
    return result


def _validate_operation_type(entity_type: str) -> str:
    if entity_type not in OPERATION_TYPES:
        raise HTTPException(status_code=404, detail="Unknown operation resource")
    return entity_type


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


class IncidentType(str, Enum):
    none = "none"
    signal_fault = "signal_fault"
    mechanical = "mechanical"
    weather = "weather"
    track_obstruction = "track_obstruction"
    staffing = "staffing"


class DelayPredictionRequest(BaseModel):
    route: str = Field(..., min_length=3, max_length=120, examples=["Colombo Fort - Kandy"])
    train_id: str = Field(..., min_length=3, max_length=20, examples=["PM-4082"])
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
    train_id: str = Field(..., min_length=3, max_length=20)
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


def _recent_feed() -> list[dict]:
    generated = [{"id": item.get("record_id"), "route": item.get("route"), "station": item.get("station"), "type": item.get("incident_type"), "summary": item.get("incident_note"), "time": item.get("scheduled_time")} for item in HISTORY if item.get("incident_type") != "none"]
    return list(reversed(_incidents[-8:])) + list(reversed(generated[-8:]))[: max(0, 8 - len(_incidents))]


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
    history = supabase_store.fetch_history() or HISTORY
    route_stats = _history_route_stats(history)
    delays = [float(row.get("delay_minutes", 0)) for row in history]
    incident_counts = Counter(row.get("incident_type", "other") for row in history if row.get("incident_type") != "none")
    hour_groups: dict[int, list[float]] = {hour: [] for hour in range(24)}
    for row in history:
        try:
            hour = datetime.fromisoformat(row["scheduled_time"]).hour
            hour_groups[hour].append(float(row.get("delay_minutes", 0)))
        except (KeyError, ValueError):
            continue
    hourly = [{"hour": hour, "average_delay": round(sum(values) / len(values), 1) if values else 0} for hour, values in hour_groups.items()]
    ml_metrics = _metric_file(Path(__file__).parent / "evaluation" / "ml" / "delay_model_metrics.json")
    nlp_metrics = _metric_file(Path(__file__).parent / "evaluation" / "nlp" / "classification_metrics.json")
    robustness = _metric_file(Path(__file__).parent / "evaluation" / "nlp" / "out_of_template_robustness_check.json")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overview": {"trips": len(history), "average_delay": round(sum(delays) / len(delays), 1) if delays else 0, "on_time_rate": round(sum(delay <= 5 for delay in delays) / len(delays) * 100, 1) if delays else 0, "active_alerts": len([event for event in (supabase_store.fetch_recent_events(50) or _events) if event.get("event_type") == "delay_alert"]), "audit_events": supabase_store.count_rows("audit_events") or _read_audit_count()},
        "routes": route_stats,
        "hourly": hourly,
        "incident_mix": [{"type": key, "count": value} for key, value in incident_counts.most_common()],
        "feature_importance": delay_model.get_top_features(6),
        "ml_metrics": ml_metrics,
        "nlp_metrics": nlp_metrics,
        "robustness": robustness,
        "feed": _recent_feed(),
        "events": (supabase_store.fetch_recent_events(12) or list(reversed(_events[-12:]))),
        "hub": {"configured": bool(os.getenv("HUB_BASE_URL")), "endpoint": hub_client.HUB_BASE_URL, "alert_threshold_minutes": hub_client.DELAY_ALERT_THRESHOLD_MINUTES},
        "operations": _operations_payload(),
    }


@app.get("/api/operations")
def operations_data():
    return {"generated_at": datetime.now(timezone.utc).isoformat(), **_operations_payload()}


@app.post("/api/operations/{entity_type}")
def create_operation(entity_type: str, payload: dict = Body(...)):
    entity_type = _validate_operation_type(entity_type)
    entity = {"id": payload.get("id") or f"{entity_type[:3].upper()}-{uuid.uuid4().hex[:6].upper()}", **payload}
    if not supabase_store.insert_entity(entity_type, entity):
        _operation_store[entity_type].insert(0, entity)
    return entity


@app.patch("/api/operations/{entity_type}/{entity_id}")
def update_operation(entity_type: str, entity_id: str, payload: dict = Body(...)):
    entity_type = _validate_operation_type(entity_type)
    updated = supabase_store.update_entity(entity_type, entity_id, payload)
    if updated is None:
        matches = [item for item in _operation_store[entity_type] if item.get("id") == entity_id]
        if not matches:
            raise HTTPException(status_code=404, detail="Operation entity not found")
        matches[0].update(payload)
        updated = matches[0]
    return updated


@app.delete("/api/operations/{entity_type}/{entity_id}")
def delete_operation(entity_type: str, entity_id: str):
    entity_type = _validate_operation_type(entity_type)
    if not supabase_store.delete_entity(entity_type, entity_id):
        before = len(_operation_store[entity_type])
        _operation_store[entity_type] = [item for item in _operation_store[entity_type] if item.get("id") != entity_id]
        if len(_operation_store[entity_type]) == before:
            raise HTTPException(status_code=404, detail="Operation entity not found")
    return {"deleted": entity_id, "entity_type": entity_type}


@app.get("/api/events")
def events():
    return {"events": list(reversed(_events[-50:]))}


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
    query_parts = [req.route]
    if req.station:
        query_parts.append(req.station)
    if req.weather:
        query_parts.append(req.weather.value)
    if req.incident_type and req.incident_type != IncidentType.none:
        query_parts.append(req.incident_type.value.replace("_", " "))
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
        baseline = 4.0
        if req.weather in (WeatherCondition.heavy_rain, WeatherCondition.fog):
            baseline += 6.0
        elif req.weather == WeatherCondition.light_rain:
            baseline += 2.0
        if req.day_type == DayType.public_holiday:
            baseline += 3.0

        grounded = explanation_layer.compose_explanation(
            req.route, baseline, [], incidents, prefer_llm=prefer_llm
        )
        response = DelayPredictionResponse(
            route=req.route,
            train_id=req.train_id,
            predicted_delay_minutes=round(baseline, 1),
            confidence="low",
            explanation=grounded["explanation"],
            top_contributing_features=[],
            similar_past_incidents=citations,
            model_version="phase1-heuristic-v0",
            retrieval_method=retrieval["method"],
            explanation_method=grounded["method"],
        )
        _predictions.append(response.model_dump())
        alert = await hub_client.publish_delay_alert(req.route, req.train_id, response.predicted_delay_minutes)
        if alert.get("event"):
            await asyncio.to_thread(_record_event, alert["event"], alert.get("destinations", []))
        await asyncio.to_thread(_audit, "prediction", request, {"route": req.route, "train_id": req.train_id, "delay": response.predicted_delay_minutes, "model": response.model_version})
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
    alert = await hub_client.publish_delay_alert(req.route, req.train_id, response.predicted_delay_minutes)
    if alert.get("event"):
        await asyncio.to_thread(_record_event, alert["event"], alert.get("destinations", []))
    await asyncio.to_thread(_audit, "prediction", request, {"route": req.route, "train_id": req.train_id, "delay": response.predicted_delay_minutes, "model": response.model_version})
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
    """
    import uuid

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
    _incidents.append({"id": response.incident_id, "route": "Live report", "station": response.station, "type": response.classified_type, "summary": response.summary, "time": response.received_at.isoformat()})
    admin_db.insert_row("incident_reports", {
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
    _audit("incident_report", request, {"incident_id": response.incident_id, "train_id": req.train_id, "classified_type": response.classified_type})
    return response


@app.post("/hub/message")
async def hub_message(request: Request, message: HubMessage):
    """Receive a Passenger Agent delay_check through the shared Hub."""
    if message.intent != "delay_check":
        raise HTTPException(status_code=400, detail="unsupported hub intent")
    payload = message.payload
    try:
        prediction_request = DelayPredictionRequest(
            route=payload["route"],
            train_id=payload["train_id"],
            scheduled_time=payload.get("scheduled_time", datetime.now(timezone.utc)),
            weather=payload.get("weather"),
            day_type=payload.get("day_type", "weekday"),
            station=payload.get("station"),
            incident_type=payload.get("incident_type", "none"),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid delay_check payload: {exc}") from exc
    response = await predict_delay(request, prediction_request)
    result = {"message_id": message.message_id or uuid.uuid4().hex, "sender_agent": AGENT_NAME, "receiver_agent": message.sender_agent, "intent": "delay_check_response", "payload": response.model_dump(), "timestamp": datetime.now(timezone.utc).isoformat()}
    _audit("hub_delay_check", request, {"sender_agent": message.sender_agent, "route": prediction_request.route, "train_id": prediction_request.train_id})
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
