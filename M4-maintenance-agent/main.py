"""RailSense Maintenance Agent: asset health, NLP triage, manual RAG, and dashboard APIs.

Endpoints:
    GET  /health                    -> liveness check
    GET  /                          -> maintenance dashboard frontend
    GET  /chat-ui                   -> maintenance engineer chatbot frontend
    POST /chat                      -> RAG-powered engineer chatbot (manual Q&A)
    POST /asset-health              -> predict asset health + manual-grounded recommendation
    GET  /asset-status/{asset_id}   -> current status of a specific asset
    POST /maintenance-report        -> NLP processing of technician free-text report
    GET  /manual-search             -> RAG search through equipment manuals
    POST /hub/message               -> receive maintenance_check from the Agent Hub
    GET  /api/dashboard             -> aggregated dashboard data
    GET  /api/assets                -> all assets with health status
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import csv
import json
import logging
import os
import uuid
from typing import Any, Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import bleach
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from ml import predict as health_model
from nlp import extract_notes as note_extractor
from nlp import summarize_report as report_summarizer
from rag import manual_retriever
from rag import recommendation as rec_layer
from rag import chatbot as engineer_chatbot
import hub_client
import supabase_store

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("railsense.maintenance")
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])

AGENT_DIR = Path(__file__).parent
DATA_PATH = AGENT_DIR / "data" / "assets_history.csv"
AUDIT_LOG = AGENT_DIR / "data" / "audit_log.jsonl"
UI_DIR = AGENT_DIR / "ui"

_in_memory_events: list[dict] = []
_in_memory_reports: list[dict] = []


@asynccontextmanager
async def lifespan(_app):
    try:
        await hub_client.register_with_hub()
        logger.info("Registered with agent Hub")
    except Exception as exc:
        logger.warning("Hub unavailable at startup: %s", exc)
    yield


app = FastAPI(
    title="M4 — Maintenance & Asset Intelligence Agent",
    description="RailSense AI · Maintenance & Asset Intelligence Agent (Member D / M4)",
    version="1.0.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# Serve train images — place images in ui/trains/<name>.jpg
_trains_dir = UI_DIR / "trains"
_trains_dir.mkdir(exist_ok=True)
app.mount("/trains", StaticFiles(directory=str(_trains_dir)), name="trains")

app.add_exception_handler(
    RateLimitExceeded,
    lambda req, exc: JSONResponse({"detail": "Rate limit exceeded."}, status_code=429),
)


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class AssetHealthRequest(BaseModel):
    asset_id: str = Field(..., min_length=1, max_length=50)
    asset_type: str = Field(..., min_length=1, max_length=50)
    days_since_service: int = Field(0, ge=0, le=3650)
    fault_count_30d: int = Field(0, ge=0, le=100)
    sensors: dict[str, Any] = Field(default_factory=dict)

    @field_validator("asset_type")
    @classmethod
    def validate_asset_type(cls, v: str) -> str:
        allowed = {
            "diesel_engine", "electric_loco", "bogie", "brake_system",
            "signal_unit", "track_section", "level_crossing", "platform_gate",
        }
        if v not in allowed:
            raise ValueError(f"asset_type must be one of: {', '.join(sorted(allowed))}")
        return v


class MaintenanceReportRequest(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    asset_id: str = Field(..., min_length=1, max_length=50)
    asset_type: str = Field(..., min_length=1, max_length=50)
    station: str = Field(..., min_length=1, max_length=100)
    text: str = Field(..., min_length=5, max_length=2000)
    technician_id: Optional[str] = Field(None, max_length=50)

    @field_validator("text")
    @classmethod
    def sanitize_text(cls, v: str) -> str:
        cleaned = bleach.clean(v, tags=[], strip=True)
        for ch in "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f":
            cleaned = cleaned.replace(ch, "")
        if len(cleaned) < 5:
            raise ValueError("Report text is too short after sanitization.")
        return cleaned


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    asset_type: Optional[str] = Field("", max_length=50)
    history: list[ChatTurn] = Field(default_factory=list)

    @field_validator("message")
    @classmethod
    def sanitize_message(cls, v: str) -> str:
        cleaned = bleach.clean(v, tags=[], strip=True)
        if len(cleaned) < 1:
            raise ValueError("Message is empty after sanitization.")
        return cleaned


class HubMessageRequest(BaseModel):
    message_id: str
    sender_agent: str
    receiver_agent: str = "maintenance-agent"
    intent: str
    payload: dict[str, Any] = Field(default_factory=dict)
    auth_token: str = ""
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _write_audit(action: str, client_ip: str, details: dict[str, Any]) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "agent": "maintenance-agent",
        "client": client_ip,
        **details,
    }
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    supabase_store.insert_audit(action, client_ip, details)


def _load_csv_history() -> list[dict]:
    if not DATA_PATH.exists():
        return []
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _get_history() -> list[dict]:
    rows = supabase_store.fetch_assets_history()
    if rows is not None:
        return rows
    return _load_csv_history()


def _dashboard_aggregates(rows: list[dict]) -> dict:
    if not rows:
        return {}
    total = len(rows)
    status_counts: dict[str, int] = {"GREEN": 0, "AMBER": 0, "RED": 0}
    type_counts: dict[str, int] = {}
    scores: list[float] = []
    for r in rows:
        s = str(r.get("health_status", "GREEN"))
        status_counts[s] = status_counts.get(s, 0) + 1
        t = str(r.get("asset_type", "unknown"))
        type_counts[t] = type_counts.get(t, 0) + 1
        try:
            scores.append(float(r.get("health_score", 0)))
        except (ValueError, TypeError):
            pass
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    green_pct = round(status_counts["GREEN"] / total * 100, 1) if total else 0
    return {
        "total_assets": total,
        "avg_health_score": avg_score,
        "assets_healthy_pct": green_pct,
        "status_distribution": status_counts,
        "asset_type_distribution": type_counts,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agent": "maintenance-agent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
async def dashboard_ui():
    index = UI_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Maintenance dashboard UI not found. Place ui/index.html to enable it."}


@app.get("/api/dashboard")
@limiter.limit("60/minute")
async def api_dashboard(request: Request):
    rows = _get_history()
    aggregates = _dashboard_aggregates(rows)

    ml_metrics: dict = {}
    ml_path = AGENT_DIR / "evaluation" / "ml" / "health_model_metrics.json"
    if ml_path.exists():
        try:
            ml_metrics = json.loads(ml_path.read_text())
        except Exception:
            pass

    nlp_metrics: dict = {}
    nlp_path = AGENT_DIR / "evaluation" / "nlp" / "classification_metrics.json"
    if nlp_path.exists():
        try:
            nlp_metrics = json.loads(nlp_path.read_text())
        except Exception:
            pass

    rag_metrics: dict = {}
    rag_path = AGENT_DIR / "evaluation" / "rag" / "retrieval_metrics.json"
    if rag_path.exists():
        try:
            rag_metrics = json.loads(rag_path.read_text())
        except Exception:
            pass

    audit_count = supabase_store.fetch_audit_count()
    if audit_count is None:
        try:
            audit_count = sum(1 for _ in open(AUDIT_LOG, encoding="utf-8")) if AUDIT_LOG.exists() else 0
        except Exception:
            audit_count = 0

    recent_reports = _in_memory_reports[-10:]
    recent_events = supabase_store.fetch_recent_events(20) or _in_memory_events[-20:]

    manual_sections_count = len(manual_retriever._load_manual_sections())

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "supabase" if supabase_store.get_client() else "local_csv",
        "aggregates": aggregates,
        "ml_metrics": ml_metrics,
        "nlp_metrics": nlp_metrics,
        "rag_metrics": rag_metrics,
        "audit_count": audit_count,
        "recent_reports": recent_reports,
        "recent_events": recent_events,
        "hub_status": {
            "hub_url": hub_client.HUB_BASE_URL,
            "upstash_configured": bool(hub_client.UPSTASH_REDIS_URL),
            "supabase_configured": supabase_store.get_client() is not None,
        },
        "rag_info": {
            "manual_sections_indexed": manual_sections_count,
            "retrieval_backend": "supabase_pgvector" if (
                os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY")
            ) else "local_tfidf",
        },
    }


@app.get("/api/assets")
@limiter.limit("60/minute")
async def api_assets(
    request: Request,
    asset_type: Optional[str] = None,
    health_status: Optional[str] = None,
    limit: int = 50,
):
    rows = _get_history()
    if asset_type:
        rows = [r for r in rows if r.get("asset_type") == asset_type]
    if health_status:
        rows = [r for r in rows if r.get("health_status") == health_status.upper()]
    return {"assets": rows[:limit], "total": len(rows)}


@app.post("/asset-health")
@limiter.limit("30/minute")
async def asset_health(request: Request, payload: AssetHealthRequest):
    prediction = health_model.predict_health(
        asset_type=payload.asset_type,
        days_since_service=payload.days_since_service,
        fault_count_30d=payload.fault_count_30d,
        sensors=payload.sensors,
    )

    query = f"{payload.asset_type} {' '.join(str(v) for v in payload.sensors.values())}"
    manual_sections, retrieval_method = manual_retriever.retrieve_manual_sections(
        query=query,
        asset_type=payload.asset_type,
        top_k=3,
    )

    recommendation, rec_method = rec_layer.compose_recommendation(
        asset_id=payload.asset_id,
        asset_type=payload.asset_type,
        health_score=prediction["health_score"],
        health_status=prediction["health_status"],
        top_features=prediction["top_contributing_features"],
        manual_sections=manual_sections,
    )

    result = {
        "asset_id": payload.asset_id,
        "asset_type": payload.asset_type,
        "health_score": prediction["health_score"],
        "health_status": prediction["health_status"],
        "confidence": prediction["confidence"],
        "model_version": prediction["model_version"],
        "top_contributing_features": prediction["top_contributing_features"],
        "manual_sections_cited": [
            {
                "manual": s.get("manual"),
                "section_title": s.get("section_title"),
                "snippet": str(s.get("content", ""))[:200],
                "source_file": s.get("source_file"),
            }
            for s in manual_sections
        ],
        "recommendation": recommendation,
        "recommendation_method": rec_method,
        "retrieval_method": retrieval_method,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    client_ip = request.client.host if request.client else "unknown"
    _write_audit("asset_health_prediction", client_ip, {
        "asset_id": payload.asset_id,
        "asset_type": payload.asset_type,
        "health_status": prediction["health_status"],
    })

    if prediction["health_status"] == "RED":
        try:
            alert = await hub_client.publish_maintenance_alert(
                asset_id=payload.asset_id,
                asset_type=payload.asset_type,
                health_status=prediction["health_status"],
                health_score=prediction["health_score"],
                recommended_action=recommendation,
            )
            result["alert"] = alert
            event_record = {
                "event_type": "maintenance_alert",
                "sender_agent": "maintenance-agent",
                "asset_id": payload.asset_id,
                "asset_type": payload.asset_type,
                "severity": "RED",
                "payload": {"health_score": prediction["health_score"], "recommendation": recommendation},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            _in_memory_events.append(event_record)
            supabase_store.insert_maintenance_event(event_record)
        except Exception as exc:
            logger.warning("Alert publish failed: %s", exc)

    return result


@app.get("/asset-status/{asset_id}")
@limiter.limit("60/minute")
async def asset_status(request: Request, asset_id: str):
    rows = _get_history()
    matches = [r for r in rows if r.get("asset_id") == asset_id]
    if not matches:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found.")
    latest = sorted(matches, key=lambda r: r.get("last_service_date", ""), reverse=True)[0]
    return {"asset_id": asset_id, "latest_record": latest, "total_records": len(matches)}


@app.post("/maintenance-report")
@limiter.limit("20/minute")
async def maintenance_report(request: Request, payload: MaintenanceReportRequest):
    extraction = note_extractor.extract_technician_note(payload.text)
    summary, nlp_method = report_summarizer.summarize_maintenance_report(payload.text)

    manual_sections, retrieval_method = manual_retriever.retrieve_manual_sections(
        query=f"{extraction['detected_fault_type']} {payload.asset_type} {payload.text[:200]}",
        asset_type=payload.asset_type,
        fault_type=extraction["detected_fault_type"],
        top_k=2,
    )

    report_record = {
        "report_id": payload.report_id,
        "asset_id": payload.asset_id,
        "asset_type": payload.asset_type,
        "station": payload.station,
        "summary": summary,
        "detected_fault_type": extraction["detected_fault_type"],
        "parts_mentioned": extraction["parts_mentioned"],
        "actions_taken": extraction["actions_taken"],
        "measurements_found": extraction["measurements_found"],
        "extraction_method": extraction["extraction_method"],
        "nlp_method": nlp_method,
        "retrieval_method": retrieval_method,
        "manual_sections_cited": [s.get("section_title") for s in manual_sections],
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    _in_memory_reports.append(report_record)

    client_ip = request.client.host if request.client else "unknown"
    _write_audit("maintenance_report_submitted", client_ip, {
        "asset_id": payload.asset_id,
        "asset_type": payload.asset_type,
        "detected_fault_type": extraction["detected_fault_type"],
    })

    return report_record


@app.get("/manual-search")
@limiter.limit("30/minute")
async def manual_search(
    request: Request,
    q: str,
    asset_type: Optional[str] = None,
    fault_type: Optional[str] = None,
    k: int = 3,
):
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=422, detail="Query 'q' must be at least 2 characters.")
    q_clean = bleach.clean(q[:500], tags=[], strip=True)
    sections, method = manual_retriever.retrieve_manual_sections(
        query=q_clean,
        asset_type=asset_type or "",
        fault_type=fault_type or "",
        top_k=min(k, 5),
    )
    return {
        "query": q_clean,
        "retrieval_method": method,
        "results": [
            {
                "manual": s.get("manual"),
                "section_title": s.get("section_title"),
                "content": s.get("content", "")[:500],
                "source_file": s.get("source_file"),
                "score": s.get("score"),
            }
            for s in sections
        ],
    }


@app.get("/chat-ui")
async def chatbot_ui():
    chat_page = UI_DIR / "chat.html"
    if chat_page.exists():
        return FileResponse(str(chat_page))
    return {"message": "Chat UI not found. Place ui/chat.html to enable it."}


@app.post("/chat")
@limiter.limit("30/minute")
async def chat(request: Request, payload: ChatRequest):
    history = [{"role": t.role, "content": t.content} for t in payload.history]
    result = engineer_chatbot.answer_engineer_question(
        message=payload.message,
        asset_type=payload.asset_type or "",
        history=history,
    )
    client_ip = request.client.host if request.client else "unknown"
    _write_audit("engineer_chat", client_ip, {
        "detected_asset_type": result["detected_asset_type"],
        "answer_method": result["answer_method"],
        "retrieval_method": result["retrieval_method"],
    })
    return result


@app.post("/hub/message")
async def hub_message(request: Request, payload: HubMessageRequest):
    if payload.intent == "maintenance_check":
        asset_id = payload.payload.get("asset_id", "unknown")
        asset_type = payload.payload.get("asset_type", "diesel_engine")
        sensors = payload.payload.get("sensors", {})
        days = int(payload.payload.get("days_since_service", 30))

        prediction = health_model.predict_health(
            asset_type=asset_type,
            days_since_service=days,
            sensors=sensors,
        )
        sections, method = manual_retriever.retrieve_manual_sections(
            query=f"{asset_type} maintenance",
            asset_type=asset_type,
            top_k=2,
        )
        recommendation, rec_method = rec_layer.compose_recommendation(
            asset_id=asset_id,
            asset_type=asset_type,
            health_score=prediction["health_score"],
            health_status=prediction["health_status"],
            top_features=prediction["top_contributing_features"],
            manual_sections=sections,
        )
        response_envelope = {
            "message_id": str(uuid.uuid4()),
            "sender_agent": "maintenance-agent",
            "receiver_agent": payload.sender_agent,
            "intent": "maintenance_check_response",
            "payload": {
                "asset_id": asset_id,
                "health_score": prediction["health_score"],
                "health_status": prediction["health_status"],
                "recommendation": recommendation,
                "retrieval_method": method,
                "recommendation_method": rec_method,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        client_ip = request.client.host if request.client else "unknown"
        _write_audit("hub_message_received", client_ip, {
            "intent": payload.intent,
            "asset_id": asset_id,
            "asset_type": asset_type,
            "sender": payload.sender_agent,
        })
        return response_envelope

    raise HTTPException(status_code=400, detail=f"Unsupported intent: {payload.intent}")
