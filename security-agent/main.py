"""
security-agent/main.py
----------------------
RailSense AI — Security & Fraud Agent Service (Port 8004).

Responsibilities:
1. Receives derived behavioral passenger features from Booking Agent.
2. Evaluates features using scikit-learn IsolationForest anomaly detection model.
3. Returns calibrated risk analysis (risk_score, risk_level, recommended_action, reasons).
4. Strictly maintains multi-agent boundary:
   - Does not perform ticket bookings, seat queries, or fare calculations.
   - Does not confirm or issue tickets.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from typing import Any
from fastapi import FastAPI, status, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Path resolution
_CURRENT_DIR = Path(__file__).resolve().parent
if str(_CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CURRENT_DIR))

from fraud.model import fraud_detector
from fraud.llm_summary import generate_grounded_fraud_summary, DEMO_POLICY_CITATIONS

# In-memory storage for feedback
_FEEDBACK_LOG: list[dict[str, Any]] = []

app = FastAPI(
    title="RailSense AI - Security & Fraud Agent",
    description="Provides behavioral anomaly scoring and fraud risk assessment for railway operations.",
    version="1.0.0",
)


class FraudScoreRequest(BaseModel):
    nic_key: str = Field(default="", description="Protected non-plain identifier")
    booking_reference: str | None = Field(default=None, description="Optional booking/case reference")
    features: dict[str, float] = Field(
        default_factory=dict,
        description="Behavioral numerical features extracted by Booking Agent",
    )
    travel_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Sanitized contextual trip details (origin, dest, train, date)",
    )


class FraudScoreResponse(BaseModel):
    risk_score: float = Field(..., description="Project-calibrated anomaly risk score between 0.0 and 1.0")
    risk_level: str = Field(..., description="Risk category: LOW, MEDIUM, HIGH")
    recommended_action: str = Field(..., description="Recommended policy action: ALLOW, REVIEW, REJECT")
    reasons: list[str] = Field(default_factory=list, description="List of behavioral explanation codes")
    model: str = Field(default="IsolationForest", description="Underlying ML model")
    grounded_summary: dict[str, Any] | None = Field(default=None, description="4-section grounded LLM summary")


class AgentMessagePayload(BaseModel):
    message_id: str | None = None
    sender: str = "booking-agent"
    receiver: str = "security-agent"
    intent: str
    body: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None


class InvestigationFeedbackRequest(BaseModel):
    case_reference: str = Field(..., description="Unique fraud review case reference (e.g. FR-...)")
    true_label: str = Field(..., description="Adjudicated true label: CONFIRMED_FRAUD or FALSE_POSITIVE")
    reviewer_notes: str | None = Field(default=None, description="Adjudicator notes or rationale")
    admin_id: str | None = Field(default="admin", description="Reviewer administrator ID")


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"service": "security-agent", "status": "ok"}


@app.post(
    "/internal/fraud-score",
    response_model=FraudScoreResponse,
    tags=["fraud"],
    summary="Evaluate passenger behavioral features for fraud risk",
)
def evaluate_fraud_score(payload: FraudScoreRequest) -> JSONResponse:
    """
    Accepts derived behavioral features from Booking Agent.
    Runs scikit-learn IsolationForest model and returns advisory risk analysis.
    """
    result = fraud_detector.score_features(payload.features)

    # Attach grounded summary if flagged for review or rejection
    if result.get("recommended_action") in ("REVIEW", "REJECT") or result.get("risk_level") in ("MEDIUM", "HIGH"):
        evidence = {
            "features": payload.features,
            "risk_score": result.get("risk_score", 0.0),
            "risk_level": result.get("risk_level", "LOW"),
            "reasons": result.get("reasons", []),
            "travel_context": payload.travel_context,
        }
        result["grounded_summary"] = generate_grounded_fraud_summary(evidence)

    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@app.post(
    "/internal/messages",
    tags=["inter-agent"],
    summary="Receive inter-agent message from Communication Hub",
)
def handle_internal_message(payload: AgentMessagePayload) -> JSONResponse:
    """
    Handles messages routed via Communication Hub for fraud scoring.
    """
    if payload.intent in ("fraud_score_request", "fraud_check"):
        features = payload.body.get("features", {})
        nic_key = payload.body.get("nic_key", "")
        booking_ref = payload.body.get("booking_reference")
        travel_ctx = payload.body.get("travel_context", {})

        result = fraud_detector.score_features(features)

        if result.get("recommended_action") in ("REVIEW", "REJECT") or result.get("risk_level") in ("MEDIUM", "HIGH"):
            evidence = {
                "features": features,
                "risk_score": result.get("risk_score", 0.0),
                "risk_level": result.get("risk_level", "LOW"),
                "reasons": result.get("reasons", []),
                "travel_context": travel_ctx,
            }
            result["grounded_summary"] = generate_grounded_fraud_summary(evidence)

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "message_id": f"RESP-{payload.message_id or 'SCORE'}",
                "status": "scored",
                "result": result,
            },
        )

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": f"Unsupported intent '{payload.intent}' for security-agent."},
    )


@app.post(
    "/internal/grounded-summary",
    tags=["fraud"],
    summary="Generate 4-section grounded LLM summary from raw evidence",
)
def evaluate_grounded_summary(evidence: dict[str, Any]) -> JSONResponse:
    """Generates 4-section grounded explanation with policy citations."""
    summary = generate_grounded_fraud_summary(evidence)
    return JSONResponse(status_code=status.HTTP_200_OK, content=summary)


@app.post(
    "/internal/investigation-feedback",
    tags=["fraud"],
    summary="Record human adjudicator label for model evaluation",
)
def record_investigation_feedback(feedback: InvestigationFeedbackRequest) -> JSONResponse:
    """
    Collects ground-truth labels (CONFIRMED_FRAUD / FALSE_POSITIVE) from human review.
    Used for feedback telemetry and retraining evaluation.
    """
    record = {
        "case_reference": feedback.case_reference,
        "true_label": feedback.true_label.upper(),
        "reviewer_notes": feedback.reviewer_notes,
        "admin_id": feedback.admin_id,
        "timestamp": os.getenv("MOCK_TIMESTAMP") or "2026-09-17T05:00:00Z",
    }
    _FEEDBACK_LOG.append(record)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "recorded", "record": record},
    )


@app.get(
    "/internal/investigation-feedback",
    tags=["fraud"],
    summary="Retrieve recorded investigation feedback history",
)
def get_investigation_feedback(limit: int = Query(default=50, ge=1, le=200)) -> JSONResponse:
    """Returns the most recent investigation feedback records."""
    return JSONResponse(status_code=status.HTTP_200_OK, content=_FEEDBACK_LOG[-limit:])


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SECURITY_AGENT_PORT", "8004"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
