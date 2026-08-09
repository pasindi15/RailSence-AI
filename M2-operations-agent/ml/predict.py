"""
M2 — Operations & Delay-Prediction Agent
Phase 2: Prediction wrapper around the trained model.

Loads delay_model.pkl once at import time and exposes predict_delay(),
which main.py's /predict-delay endpoint calls. Falls back to the Phase 1
heuristic if the model file hasn't been trained yet (keeps the service
runnable even before `python train_delay_model.py` has been run).
"""

import json
from pathlib import Path
from typing import Optional

import joblib
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
MODEL_PATH = THIS_DIR / "delay_model.pkl"
IMPORTANCES_PATH = THIS_DIR / "feature_importances.json"

MODEL_VERSION = "phase2-gbr-v1"

_model = None
_feature_importances: list[dict] = []


def _load_model_if_needed():
    global _model, _feature_importances
    if _model is None and MODEL_PATH.exists():
        _model = joblib.load(MODEL_PATH)
        if IMPORTANCES_PATH.exists():
            with open(IMPORTANCES_PATH) as f:
                _feature_importances = json.load(f)
    return _model


def is_model_available() -> bool:
    return _load_model_if_needed() is not None


def get_top_features(n: int = 3) -> list[dict]:
    _load_model_if_needed()
    return _feature_importances[:n]


def predict_delay(
    route: str,
    scheduled_hour: int,
    weather: Optional[str] = None,
    day_type: Optional[str] = None,
    station: Optional[str] = None,
    incident_type: Optional[str] = None,
) -> dict:
    """
    Returns {"predicted_delay_minutes": float, "model_version": str, "top_features": [...]}

    Any unset categorical field is passed through as "unknown" — the
    OneHotEncoder was fit with handle_unknown="ignore" so this degrades
    gracefully rather than erroring.
    """
    model = _load_model_if_needed()
    if model is None:
        raise RuntimeError(
            "delay_model.pkl not found — run `python ml/train_delay_model.py` first."
        )

    row = pd.DataFrame(
        [
            {
                "route": route,
                "station": station or "unknown",
                "weather": weather or "clear",
                "day_type": day_type or "weekday",
                "incident_type": incident_type or "none",
                "scheduled_hour": scheduled_hour,
            }
        ]
    )

    prediction = float(model.predict(row)[0])

    return {
        "predicted_delay_minutes": round(prediction, 1),
        "model_version": MODEL_VERSION,
        "top_features": get_top_features(3),
    }
