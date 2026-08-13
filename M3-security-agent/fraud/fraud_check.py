"""
fraud/fraud_check.py — Runtime fraud scorer (Phase 3)

Loads the trained IsolationForest model at import time and exposes
score_booking() for use by main.py's POST /security/fraud-check endpoint.

Fallback behaviour:
  If fraud_model.pkl has not been trained yet, score_booking() uses a
  rule-based heuristic (bookings_last_60s > 2 → HIGH) so the endpoint is
  always demoable without running the training step first.

Optional LLM explanation:
  If ANTHROPIC_API_KEY is set, score_booking() calls Claude claude-3-haiku
  to generate a richer plain-English reason string. If the key is missing,
  a deterministic rule-based reason is returned instead.

Usage (from main.py):
  from fraud.fraud_check import score_booking

  result = score_booking({
      "user_id": "usr_4421",
      "event_id": "evt_9921",
      "route_id": 2,
      "ticket_price": 480,
      "bookings_last_60s": 5,
      "travel_distance_km": 420,
      "time_since_last_booking": 4,
  })
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
HERE       = Path(__file__).parent
MODEL_PATH = HERE / "fraud_model.pkl"
IMP_PATH   = HERE / "feature_importances.json"

FEATURE_COLS = [
    "timestamp",
    "route_id",
    "ticket_price",
    "bookings_last_60s",
    "travel_distance_km",
    "time_since_last_booking",
]

THRESHOLD_HIGH   = 0.04
THRESHOLD_MEDIUM = 0.07
MODEL_VERSION    = "phase3-iforest-v1"

# ---------------------------------------------------------------------------
# Model loading (lazy — does not crash if model not yet trained)
# ---------------------------------------------------------------------------
_model = None
_importances: Dict[str, float] = {}

def _load_model() -> None:
    global _model, _importances
    if MODEL_PATH.exists():
        try:
            import joblib
            _model = joblib.load(MODEL_PATH)
            logger.info("Fraud model loaded from %s", MODEL_PATH)
        except Exception as exc:
            logger.warning("Could not load fraud model: %s — using rule-based fallback.", exc)
            _model = None
    else:
        logger.warning(
            "fraud_model.pkl not found at %s. "
            "Run fraud/train_model.py to train the model. "
            "Using rule-based fallback until then.",
            MODEL_PATH,
        )

    if IMP_PATH.exists():
        with open(IMP_PATH) as f:
            _importances = json.load(f)

_load_model()


# ---------------------------------------------------------------------------
# Risk level from score
# ---------------------------------------------------------------------------

def _score_to_risk(score: float) -> str:
    if score > THRESHOLD_MEDIUM:
        return "LOW"
    if score > THRESHOLD_HIGH:
        return "MEDIUM"
    return "HIGH"


# ---------------------------------------------------------------------------
# Top contributing features
# ---------------------------------------------------------------------------

def _top_features(event: Dict[str, Any], n: int = 3) -> Dict[str, Any]:
    """
    Return the top-n features by their importance weight,
    with the actual values from the current event.
    """
    if not _importances:
        # Fallback: return the three most fraud-relevant fields
        return {
            "bookings_last_60s":      event.get("bookings_last_60s", 0),
            "time_since_last_booking": event.get("time_since_last_booking", 0),
            "ticket_price":           event.get("ticket_price", 0),
        }

    top_keys = list(_importances.keys())[:n]
    return {k: event.get(k, 0) for k in top_keys}


# ---------------------------------------------------------------------------
# Rule-based reason string
# ---------------------------------------------------------------------------

def _build_reason(event: Dict[str, Any], risk_level: str, score: float) -> str:
    b60    = event.get("bookings_last_60s", 0)
    t_last = event.get("time_since_last_booking", 9999)
    price  = event.get("ticket_price", 0)
    dist   = event.get("travel_distance_km", 0)

    if risk_level == "LOW":
        return "Booking pattern is within normal parameters. No anomalies detected."

    reasons = []

    if b60 >= 4:
        reasons.append(
            f"{b60} bookings detected within 60 seconds — pattern matches rapid automated purchasing."
        )
    elif b60 >= 3:
        reasons.append(
            f"{b60} bookings in the last 60 seconds — elevated purchase frequency."
        )

    if t_last <= 15:
        reasons.append(
            f"Only {t_last}s since last booking — insufficient time between purchases."
        )

    if price > 2000:
        reasons.append(
            f"Ticket price Rs {price} is significantly above the expected range for this route."
        )

    if dist > 500:
        reasons.append(
            f"Travel distance of {dist} km is inconsistent with any standard route."
        )

    if not reasons:
        reasons.append(
            f"Combined feature pattern (score {score:.3f}) falls below the anomaly threshold of {THRESHOLD_HIGH}."
        )

    return " | ".join(reasons)


# ---------------------------------------------------------------------------
# Optional LLM explanation via Claude
# ---------------------------------------------------------------------------

def _llm_reason(event: Dict[str, Any], score: float, risk_level: str, top_feats: Dict[str, Any]) -> Optional[str]:
    """
    Call Claude claude-3-haiku-20240307 for a plain-English fraud explanation.
    Returns None if ANTHROPIC_API_KEY is not set or the call fails.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        prompt = (
            f"You are a railway booking fraud analyst. A booking event has been scored by an "
            f"Isolation Forest anomaly detector with score {score:.4f} (threshold {THRESHOLD_HIGH}). "
            f"Risk level: {risk_level}.\n\n"
            f"Top contributing features:\n"
            + "\n".join(f"  {k}: {v}" for k, v in top_feats.items())
            + f"\n\nFull booking event:\n{json.dumps(event, indent=2)}\n\n"
            f"Write one concise sentence (max 25 words) explaining WHY this booking was flagged, "
            f"referencing only the feature values above. Do not invent information."
        )

        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as exc:
        logger.warning("LLM explanation failed: %s — using rule-based reason.", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_booking(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score a booking event for fraud risk.

    Args:
        event: Dict with keys matching the 6 feature columns plus
               user_id, event_id (both returned in the response).

    Returns:
        Dict with:
          user_id, event_id, anomaly_score, risk_level,
          top_features, reason, model_version, threshold
    """
    import time
    # Use current Unix time as timestamp if not supplied
    if "timestamp" not in event:
        event = {**event, "timestamp": int(time.time())}

    user_id  = str(event.get("user_id", "unknown"))
    event_id = str(event.get("event_id", "unknown"))

    # ── Model-based scoring ────────────────────────────────────────────────
    if _model is not None:
        try:
            features = np.array([[float(event.get(col, 0)) for col in FEATURE_COLS]])
            score = float(_model.decision_function(features)[0])
            risk_level = _score_to_risk(score)
            used_model = True
        except Exception as exc:
            logger.error("Model scoring failed: %s — falling back to heuristic.", exc)
            score = None
            used_model = False
    else:
        score = None
        used_model = False

    # ── Rule-based fallback ────────────────────────────────────────────────
    if not used_model:
        b60 = int(event.get("bookings_last_60s", 0))
        t_last = int(event.get("time_since_last_booking", 9999))
        price = float(event.get("ticket_price", 0))
        if b60 > 2 or t_last < 10:
            score = -0.35
            risk_level = "HIGH"
        elif price > 2500:
            score = -0.20
            risk_level = "HIGH"
        else:
            score = 0.05
            risk_level = "LOW"

    top_feats = _top_features(event)

    # ── Reason string ──────────────────────────────────────────────────────
    reason = _llm_reason(event, score, risk_level, top_feats) or _build_reason(event, risk_level, score)

    return {
        "user_id":       user_id,
        "event_id":      event_id,
        "anomaly_score": round(score, 4),
        "risk_level":    risk_level,
        "top_features":  top_feats,
        "reason":        reason,
        "model_version": MODEL_VERSION if used_model else "rule-based-fallback",
        "threshold":     THRESHOLD_HIGH,
    }
