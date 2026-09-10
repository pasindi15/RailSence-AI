"""Train a GradientBoostingRegressor to predict asset health score (0-100).

Usage (from repo root):
    python M4-maintenance-agent/ml/train_health_model.py
Or from this directory:
    python train_health_model.py
"""

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ML_DIR = Path(__file__).parent
AGENT_DIR = ML_DIR.parent
DATA_PATH = AGENT_DIR / "data" / "assets_history.csv"
MODEL_PATH = ML_DIR / "health_model.pkl"
IMPORTANCE_PATH = ML_DIR / "feature_importances.json"
METRICS_PATH = AGENT_DIR / "evaluation" / "ml" / "health_model_metrics.json"

CATEGORICAL_FEATURES = ["asset_type"]
NUMERIC_FEATURES = [
    "days_since_service",
    "fault_count_30d",
    "temperature_celsius",
    "vibration_level",
    "oil_pressure_bar",
    "fuel_efficiency_pct",
    "axle_temp_celsius",
    "wheel_profile_mm",
    "pad_thickness_mm",
    "brake_cylinder_pressure_bar",
    "stopping_distance_m",
    "response_time_ms",
    "voltage_output_v",
    "contact_resistance_ohm",
    "rail_wear_mm",
    "gauge_deviation_mm",
    "ballast_void_pct",
    "motor_current_a",
    "cycle_time_seconds",
    "sensor_reliability_pct",
]
TARGET = "health_score"


def load_data() -> pd.DataFrame:
    if not DATA_PATH.exists():
        print(f"Dataset not found at {DATA_PATH}. Generating...")
        sys.path.insert(0, str(AGENT_DIR / "data"))
        import generate_dataset
        generate_dataset.generate_records.__module__
        records = generate_dataset.generate_records(600)
        import csv
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(records[0].keys())
        with open(DATA_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)
        print(f"Generated {len(records)} records.")
    return pd.read_csv(DATA_PATH)


def build_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
            ("num", "passthrough", NUMERIC_FEATURES),
        ]
    )
    model = GradientBoostingRegressor(
        n_estimators=200,
        learning_rate=0.05,
        max_depth=4,
        random_state=42,
    )
    return Pipeline([("preprocessor", preprocessor), ("model", model)])


def train() -> None:
    df = load_data()
    available_numeric = [c for c in NUMERIC_FEATURES if c in df.columns]
    df[available_numeric] = df[available_numeric].fillna(0)

    X = df[CATEGORICAL_FEATURES + available_numeric]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    r2 = r2_score(y_test, y_pred)

    print(f"MAE:  {mae:.4f}")
    print(f"RMSE: {rmse:.4f}")
    print(f"R²:   {r2:.4f}")

    joblib.dump(pipeline, MODEL_PATH)
    print(f"Model saved -> {MODEL_PATH}")

    cat_encoder = pipeline.named_steps["preprocessor"].named_transformers_["cat"]
    cat_feature_names = cat_encoder.get_feature_names_out(CATEGORICAL_FEATURES).tolist()
    all_feature_names = cat_feature_names + available_numeric

    raw_importances = pipeline.named_steps["model"].feature_importances_
    importance_pairs = sorted(
        zip(all_feature_names, raw_importances.tolist()),
        key=lambda x: x[1],
        reverse=True,
    )
    top20 = [{"feature": f, "importance": round(v, 6)} for f, v in importance_pairs[:20]]
    IMPORTANCE_PATH.write_text(json.dumps(top20, indent=2))
    print(f"Feature importances -> {IMPORTANCE_PATH}")

    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    metrics = {
        "model": "GradientBoostingRegressor",
        "version": "phase2-gbr-v1",
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    print(f"Metrics -> {METRICS_PATH}")


if __name__ == "__main__":
    train()
