from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import bleach

from predictive.predict_status import predict_health
from nlp.extract_entities import extract_entities
from nlp.summarize_log import summarize_log
from rag.manual_retriever import query_manual
from hub_client import publish_maintenance_alert, subscribe_delay_alert

app = FastAPI(title="RailSense — Maintenance & Asset Intelligence Agent")


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class LogIngestRequest(BaseModel):
    train_id: str = Field(..., max_length=20)
    component: str = Field(..., max_length=100)
    sensor_readings: dict
    technician_notes: Optional[str] = Field(None, max_length=2000)
    last_service_date: Optional[str] = None

    @field_validator("technician_notes")
    @classmethod
    def sanitize_notes(cls, v):
        if v:
            return bleach.clean(v, tags=[], strip=True)
        return v


class ManualQueryRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)

    @field_validator("query")
    @classmethod
    def sanitize_query(cls, v):
        return bleach.clean(v, tags=[], strip=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "agent": "maintenance-agent"}


@app.post("/log-ingest")
async def log_ingest(req: LogIngestRequest):
    notes = req.technician_notes or ""
    entities = extract_entities(notes)
    summary = await summarize_log(notes, req.component) if notes else None
    result = predict_health(req.train_id, req.component, req.sensor_readings, req.last_service_date)

    if result["health"] in ("AMBER", "RED"):
        await publish_maintenance_alert(req.train_id, req.component, result)

    return {
        "train_id": req.train_id,
        "component": req.component,
        "health": result["health"],
        "days_to_service": result.get("days_to_service"),
        "recommendation": result.get("recommendation"),
        "entities": entities,
        "log_summary": summary,
    }


@app.get("/maintenance-status/{train_id}")
def maintenance_status(train_id: str):
    status = predict_health(train_id, component=None, sensor_readings={}, last_service_date=None)
    if not status:
        raise HTTPException(status_code=404, detail="Train not found")
    return {"train_id": train_id, **status}


@app.post("/manual-query")
async def manual_query(req: ManualQueryRequest):
    result = await query_manual(req.query)
    return result


@app.post("/hub/delay-alert")
async def receive_delay_alert(payload: dict):
    """Called by the Hub when Operations publishes a delay_alert event."""
    await subscribe_delay_alert(payload)
    return {"status": "received"}
