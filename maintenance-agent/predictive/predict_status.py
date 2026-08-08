import os
import joblib
import numpy as np
import pandas as pd
from datetime import date

MODEL_PATH = os.path.join(os.path.dirname(__file__), "health_model.pkl")
_model = None


def _load_model():
    global _model
    if _model is None and os.path.exists(MODEL_PATH):
        _model = joblib.load(MODEL_PATH)
    return _model


def _days_since(last_service_date: str | None) -> int:
    if not last_service_date:
        return 180  # assume overdue if unknown
    try:
        last = date.fromisoformat(last_service_date)
        return (date.today() - last).days
    except ValueError:
        return 180


THRESHOLDS = {
    "vibration_level": (0, 5),
    "temperature_celsius": (0, 95),
    "oil_pressure_bar": (1.5, 6.0),
}

SERVICE_INTERVAL_DAYS = 90


def predict_health(
    train_id: str,
    component: str | None,
    sensor_readings: dict,
    last_service_date: str | None,
) -> dict:
    days_since = _days_since(last_service_date)
    days_to_service = max(0, SERVICE_INTERVAL_DAYS - days_since)

    features = {
        "vibration_level": sensor_readings.get("vibration_level", 0),
        "temperature_celsius": sensor_readings.get("temperature_celsius", 60),
        "oil_pressure_bar": sensor_readings.get("oil_pressure_bar", 3.0),
        "days_since_last_service": days_since,
        "mileage_km": sensor_readings.get("mileage_km", 0),
    }

    model = _load_model()
    if model:
        X = pd.DataFrame([features])
        health = model.predict(X)[0]
    else:
        health = _threshold_health(features, days_since)

    recommendation = _recommendation(health, days_to_service, component)

    return {
        "health": health,
        "days_to_service": days_to_service,
        "recommendation": recommendation,
        "features_used": features,
    }


def _threshold_health(features: dict, days_since: int) -> str:
    issues = 0
    vib = features["vibration_level"]
    temp = features["temperature_celsius"]
    oil = features["oil_pressure_bar"]

    if vib > THRESHOLDS["vibration_level"][1]:
        issues += 2
    if temp > THRESHOLDS["temperature_celsius"][1]:
        issues += 2
    if oil < THRESHOLDS["oil_pressure_bar"][0] or oil > THRESHOLDS["oil_pressure_bar"][1]:
        issues += 1
    if days_since > 120:
        issues += 2
    elif days_since > 90:
        issues += 1

    if issues >= 3:
        return "RED"
    if issues >= 1:
        return "AMBER"
    return "GREEN"


def _recommendation(health: str, days_to_service: int, component: str | None) -> str:
    comp = component or "component"
    if health == "RED":
        return f"Immediate inspection required for {comp}. Schedule service within 48 hours."
    if health == "AMBER":
        return f"{comp.capitalize()} shows early wear signs. Recommend inspection within {days_to_service} days."
    return f"{comp.capitalize()} is healthy. Next scheduled service in {days_to_service} days."
