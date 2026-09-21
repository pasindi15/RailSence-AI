"""Load per-type health models and expose predict_health()."""

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

FAULT_SEVERITY_MAP: dict[str, int] = {
    "none": 0, "pad_worn": 1, "suspension_worn": 1,
    "brake_fade": 2, "bearing_noise": 2, "wheel_flat": 2,
    "cylinder_leak": 2, "starter_failure": 2,
    "oil_leak": 3, "overheating": 3, "fuel_pump_fault": 3,
    "axle_crack": 5,
}

SERVICE_INTERVAL: dict[str, int] = {
    "diesel_engine": 90, "bogie": 60, "brake_system": 45,
}

# Healthy sensor ranges {asset_type: {feature: (min_ok, max_ok)}}
SENSOR_RANGES: dict[str, dict[str, tuple]] = {
    "diesel_engine": {
        "temperature_celsius":  (60.0, 100.0),
        "vibration_level":      (0.0,  3.5),
        "oil_pressure_bar":     (3.5,  5.5),
        "fuel_efficiency_pct":  (80.0, 100.0),
    },
    "bogie": {
        "vibration_level":   (0.0,  3.0),
        "axle_temp_celsius": (25.0, 65.0),
        "wheel_profile_mm":  (120.0, 140.0),
    },
    "brake_system": {
        "pad_thickness_mm":            (8.0,  20.0),
        "brake_cylinder_pressure_bar": (5.0,  7.5),
        "stopping_distance_m":         (0.0,  310.0),
    },
}

SENSOR_LABELS: dict[str, str] = {
    "temperature_celsius": "Engine Temp",
    "vibration_level": "Vibration",
    "oil_pressure_bar": "Oil Pressure",
    "fuel_efficiency_pct": "Fuel Efficiency",
    "axle_temp_celsius": "Axle Temp",
    "wheel_profile_mm": "Wheel Profile",
    "pad_thickness_mm": "Pad Thickness",
    "brake_cylinder_pressure_bar": "Cyl. Pressure",
    "stopping_distance_m": "Stopping Dist.",
}

_bundle = None


def _load_bundle() -> Optional[dict]:
    global _bundle
    if _bundle is None and MODEL_PATH.exists():
        try:
            loaded = joblib.load(MODEL_PATH)
            if isinstance(loaded, dict) and "models" in loaded:
                _bundle = loaded
                logger.info("Per-type model bundle loaded (v=%s)", loaded.get("version", "?"))
            else:
                logger.warning("Old single-model format — will use heuristic until retrained")
        except Exception as exc:
            logger.warning("Failed to load health model: %s", exc)
    return _bundle


def _heuristic_score(asset_type: str, days: int, faults: int, sensors: dict) -> float:
    score = 100.0
    score -= min(30.0, days / 6.0)
    score -= faults * 8.0
    vib = sensors.get("vibration_level") or 0.0
    if vib > 5:
        score -= (vib - 5) * 5
    temp = sensors.get("temperature_celsius") or 0.0
    if temp > 100:
        score -= (temp - 100) * 0.5
    pad = sensors.get("pad_thickness_mm") or 18.0
    if pad < 8:
        score -= (8 - pad) * 5
    return max(5.0, min(100.0, score))


def get_health_status(score: float) -> str:
    if score >= 70:
        return "GREEN"
    if score >= 40:
        return "AMBER"
    return "RED"


def _risk_factors(asset_type: str, sensors: dict) -> list:
    risks = []
    for feat, (lo, hi) in SENSOR_RANGES.get(asset_type, {}).items():
        val = sensors.get(feat)
        if val is None:
            continue
        label = SENSOR_LABELS.get(feat, feat)
        if float(val) < lo:
            risks.append({"sensor": feat, "label": label, "value": val,
                          "range": f"{lo}–{hi}", "direction": "low"})
        elif float(val) > hi:
            risks.append({"sensor": feat, "label": label, "value": val,
                          "range": f"{lo}–{hi}", "direction": "high"})
    return risks


def _days_to_failure(score: float, fault_count: int, status: str) -> Optional[int]:
    if status == "RED":
        return 0
    degradation = 0.05 + fault_count * 0.09
    days = (score - 40.0) / degradation
    return int(max(0, days))


def predict_health(
    asset_type: str,
    days_since_service: int,
    fault_count_30d: int = 0,
    sensors: Optional[dict[str, Any]] = None,
    fault_type: str = "none",
) -> dict[str, Any]:
    sensors = sensors or {}
    bundle = _load_bundle()

    fault_severity = FAULT_SEVERITY_MAP.get(fault_type, 0)
    interval = SERVICE_INTERVAL.get(asset_type, 90)
    overdue_days = max(0, days_since_service - interval)

    if bundle is not None and asset_type in bundle.get("models", {}):
        info = bundle["models"][asset_type]
        model = info["model"]
        features = info["features"]
        mae = info.get("mae", 3.5)

        row: dict[str, Any] = {
            "days_since_service": days_since_service,
            "fault_count_30d": fault_count_30d,
            "fault_severity": fault_severity,
            "overdue_days": overdue_days,
        }
        for f in features:
            if f not in row:
                row[f] = sensors.get(f, 0) or 0

        try:
            X = pd.DataFrame([row])[features]
            raw = float(np.clip(model.predict(X)[0], 0, 100))
            method = bundle.get("version", "phase3-hgbr-per-type-v1")
            conf_low  = round(max(0.0,   raw - mae * 1.5), 1)
            conf_high = round(min(100.0, raw + mae * 1.5), 1)
        except Exception as exc:
            logger.warning("Prediction failed: %s", exc)
            raw = _heuristic_score(asset_type, days_since_service, fault_count_30d, sensors)
            method = "heuristic_fallback"
            conf_low, conf_high = max(0.0, raw - 8.0), min(100.0, raw + 8.0)
            mae = 8.0
    else:
        raw = _heuristic_score(asset_type, days_since_service, fault_count_30d, sensors)
        method = "heuristic_fallback"
        conf_low, conf_high = max(0.0, raw - 8.0), min(100.0, raw + 8.0)
        mae = 8.0

    score = round(raw, 2)
    status = get_health_status(score)

    # Feature importances for this type
    top_features: list = []
    if IMPORTANCE_PATH.exists():
        try:
            all_imp = json.loads(IMPORTANCE_PATH.read_text())
            typed = [e for e in all_imp if e.get("asset_type") == asset_type]
            top_features = (typed if typed else all_imp)[:5]
        except Exception:
            pass

    return {
        "health_score": score,
        "health_status": status,
        "confidence": "high" if mae < 4 else "medium",
        "confidence_low": round(conf_low, 1),
        "confidence_high": round(conf_high, 1),
        "model_version": method,
        "risk_factors": _risk_factors(asset_type, sensors),
        "days_to_failure": _days_to_failure(score, fault_count_30d, status),
        "fault_severity": fault_severity,
        "overdue_days": overdue_days,
        "top_contributing_features": top_features,
    }
