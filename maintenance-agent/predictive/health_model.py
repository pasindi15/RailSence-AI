"""
Trains a simple health-scoring model from the synthetic dataset.
Run once: python -m predictive.health_model
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib
import json
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), "health_model.pkl")
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "maintenance_logs.csv")


def train():
    df = pd.read_csv(DATA_PATH)

    feature_cols = [
        "vibration_level",
        "temperature_celsius",
        "oil_pressure_bar",
        "days_since_last_service",
        "mileage_km",
    ]
    target_col = "health_label"

    X = df[feature_cols].fillna(df[feature_cols].median())
    y = df[target_col]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    report = classification_report(y_test, model.predict(X_test), output_dict=True)
    with open(os.path.join(os.path.dirname(__file__), "..", "evaluation", "ml", "health_model_metrics.json"), "w") as f:
        json.dump(report, f, indent=2)

    importances = dict(zip(feature_cols, model.feature_importances_.tolist()))
    with open(os.path.join(os.path.dirname(__file__), "feature_importances.json"), "w") as f:
        json.dump(importances, f, indent=2)

    joblib.dump(model, MODEL_PATH)
    print(f"Model saved to {MODEL_PATH}")
    print(classification_report(y_test, model.predict(X_test)))


if __name__ == "__main__":
    train()
