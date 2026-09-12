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

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Path resolution
_CURRENT_DIR = Path(__file__).resolve().parent
if str(_CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CURRENT_DIR))

from fraud.model import fraud_detector


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


class FraudScoreResponse(BaseModel):
    risk_score: float = Field(..., description="Project-calibrated anomaly risk score between 0.0 and 1.0")
    risk_level: str = Field(..., description="Risk category: LOW, MEDIUM, HIGH")
    recommended_action: str = Field(..., description="Recommended policy action: ALLOW, REVIEW, REJECT")
    reasons: list[str] = Field(default_factory=list, description="List of behavioral explanation codes")
    model: str = Field(default="IsolationForest", description="Underlying ML model")


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
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SECURITY_AGENT_PORT", "8004"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
