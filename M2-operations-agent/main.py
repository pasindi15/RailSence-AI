"""
M2 — Operations & Delay-Prediction Agent
FastAPI service scaffold (Phase 1).

Endpoints:
    GET  /health              -> liveness check
    POST /predict-delay       -> delay prediction (stubbed until Phase 2 ML model lands)
    GET  /route-status/{id}   -> latest known status for a route
    POST /incident-report     -> summarize and classify a raw staff incident report

This file intentionally keeps Phase-2/3/4 logic behind clearly marked TODOs so
the service is runnable and demoable end-to-end from day one, and each later
phase only has to fill in one function at a time.
"""

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
import bleach
from pydantic import BaseModel, Field, field_validator

from ml import predict as delay_model
from nlp import classify_incident as incident_classifier
from nlp import summarize_incident as incident_summarizer
from rag import explanation as explanation_layer
from rag import incident_retriever

app = FastAPI(
    title="M2 — Operations & Delay-Prediction Agent",
    description="RailSense AI · Operations & Delay-Prediction Agent (Member B / M2)",
    version="0.1.0",
)

AGENT_NAME = "operations-agent"
UI_PATH = Path(__file__).parent / "ui" / "index.html"


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
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/predict-delay", response_model=DelayPredictionResponse)
def predict_delay(req: DelayPredictionRequest):
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
        return DelayPredictionResponse(
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

    return DelayPredictionResponse(
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


@app.get("/route-status/{route_id}", response_model=RouteStatusResponse)
def route_status(route_id: str):
    """
    Phase 1: returns a static placeholder status.
    Phase 5 TODO: back this with live aggregation from the operations_history
    table / Supabase, and expose it to the Ops dashboard.
    """
    if not route_id or len(route_id) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid route_id")

    return RouteStatusResponse(
        route_id=route_id,
        status="normal",
        active_trains=0,
        average_delay_minutes=0.0,
        last_updated=datetime.now(timezone.utc),
    )


@app.post("/incident-report", response_model=IncidentReportResponse)
def incident_report(req: IncidentReportRequest):
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

    return IncidentReportResponse(
        incident_id=str(uuid.uuid4()),
        train_id=req.train_id,
        station=req.station,
        summary=summarization["summary"],
        classified_type=classification["classified_type"],
        nlp_method=classification["method"],
        received_at=datetime.now(timezone.utc),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
