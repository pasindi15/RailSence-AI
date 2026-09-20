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
_model_mtime: float | None = None
_importances_mtime: float | None = None


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _load_model_if_needed():
    """Load the pipeline, re-loading whenever the .pkl changes on disk.

    Retraining and rollback both overwrite delay_model.pkl while the service
    is running, so the cache is keyed on the file's mtime. This is what lets
    the admin console's "Retrain" and "Restore" buttons take effect without a
    service restart.
    """
    global _model, _feature_importances, _model_mtime, _importances_mtime

    model_mtime = _mtime(MODEL_PATH)
    if model_mtime is None:
        _model = None
        return None

    if _model is None or model_mtime != _model_mtime:
        try:
            _model = joblib.load(MODEL_PATH)
            _model_mtime = model_mtime
        except Exception:
            _model = None
            _model_mtime = None
            return None

    importances_mtime = _mtime(IMPORTANCES_PATH)
    if importances_mtime is not None and importances_mtime != _importances_mtime:
        try:
            with open(IMPORTANCES_PATH, encoding="utf-8") as handle:
                _feature_importances = json.load(handle)
            _importances_mtime = importances_mtime
        except Exception:
            _feature_importances = []

    return _model


def reload_model() -> bool:
    """Force a reload after a retrain or rollback. Returns True if a model loaded."""
    global _model, _model_mtime, _importances_mtime
    _model = None
    _model_mtime = None
    _importances_mtime = None
    return _load_model_if_needed() is not None


def is_model_available() -> bool:
    return _load_model_if_needed() is not None


def get_top_features(n: int = 3) -> list[dict]:
    """Top-n entries of the real ml/feature_importances.json from the last run."""
    _load_model_if_needed()
    return _feature_importances[:n]


def get_all_features() -> list[dict]:
    """Every ranked feature from the last training run, for the ML screen chart."""
    _load_model_if_needed()
    return list(_feature_importances)


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
