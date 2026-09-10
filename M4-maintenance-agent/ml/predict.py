"""Load the trained health model and expose predict_health()."""

import json
import logging
from pathlib import Path
from typing import Any, Optional

import joblib
import numpy as np
import pandas as pd

logger = logging.getLogger("railsense.maintenance.ml")

ML_DIR = Path(__file__).parent
MODEL_PATH = ML_DIR / "health_model.pkl"
IMPORTANCE_PATH = ML_DIR / "feature_importances.json"

NUMERIC_FEATURES = [
    "days_since_service", "fault_count_30d", "temperature_celsius",
    "vibration_level", "oil_pressure_bar", "fuel_efficiency_pct",
    "axle_temp_celsius", "wheel_profile_mm", "pad_thickness_mm",
    "brake_cylinder_pressure_bar", "stopping_distance_m", "response_time_ms",
    "voltage_output_v", "contact_resistance_ohm", "rail_wear_mm",
    "gauge_deviation_mm", "ballast_void_pct", "motor_current_a",
    "cycle_time_seconds", "sensor_reliability_pct",
]

_pipeline = None


def _load_pipeline():
    global _pipeline
    if _pipeline is None and MODEL_PATH.exists():
        try:
            _pipeline = joblib.load(MODEL_PATH)
            logger.info("Health model loaded from %s", MODEL_PATH)
        except Exception as exc:
            logger.warning("Failed to load health model: %s", exc)
    return _pipeline


def _heuristic_score(asset_type: str, days_since_service: int, fault_count: int, sensors: dict) -> float:
    """Fallback heuristic when model is not trained yet."""
    score = 100.0
    score -= min(30, days_since_service / 6)
    score -= fault_count * 8
    vib = sensors.get("vibration_level") or 0
    if vib > 5:
        score -= (vib - 5) * 5
    temp = sensors.get("temperature_celsius") or 0
    if temp > 100:
        score -= (temp - 100) * 0.5
    pad = sensors.get("pad_thickness_mm") or 18
    if pad < 8:
        score -= (8 - pad) * 5
    resp = sensors.get("response_time_ms") or 120
    if resp > 300:
        score -= (resp - 300) * 0.05
    return max(5.0, min(100.0, score))


def get_health_status(score: float) -> str:
    if score >= 70:
        return "GREEN"
    elif score >= 40:
        return "AMBER"
    return "RED"


def get_confidence(score: float) -> str:
    if 30 <= score <= 80:
        return "medium"
    return "high"


def predict_health(
    asset_type: str,
    days_since_service: int,
    fault_count_30d: int = 0,
    sensors: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    sensors = sensors or {}
    pipeline = _load_pipeline()

    if pipeline is not None:
        row: dict[str, Any] = {
            "asset_type": asset_type,
            "days_since_service": days_since_service,
            "fault_count_30d": fault_count_30d,
        }
        for feat in NUMERIC_FEATURES[2:]:
            row[feat] = sensors.get(feat, 0) or 0
        X = pd.DataFrame([row])
        try:
            score = float(np.clip(pipeline.predict(X)[0], 0, 100))
            method = "phase2-gbr-v1"
        except Exception as exc:
            logger.warning("Prediction failed: %s — using heuristic", exc)
            score = _heuristic_score(asset_type, days_since_service, fault_count_30d, sensors)
            method = "heuristic_fallback"
    else:
        score = _heuristic_score(asset_type, days_since_service, fault_count_30d, sensors)
        method = "heuristic_fallback"

    top_features: list[dict] = []
    if IMPORTANCE_PATH.exists():
        try:
            top_features = json.loads(IMPORTANCE_PATH.read_text())[:5]
        except Exception:
            pass

    return {
        "health_score": round(score, 2),
        "health_status": get_health_status(score),
        "confidence": get_confidence(score),
        "model_version": method,
        "top_contributing_features": top_features,
    }
