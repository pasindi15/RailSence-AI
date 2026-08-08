"""
M2 — Operations & Delay-Prediction Agent
Phase 2: Delay-prediction model training.

Trains a GradientBoostingRegressor on operations_history.csv to predict
delay_minutes from route/time/weather/incident features. Saves:
    - delay_model.pkl        (trained sklearn pipeline)
    - feature_importances.json
    - metrics.json           (MAE, RMSE, R^2 on held-out test split)

Run:
    python train_delay_model.py
"""

import json
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

THIS_DIR = Path(__file__).resolve().parent
DATA_PATH = THIS_DIR.parent / "data" / "operations_history.csv"
MODEL_PATH = THIS_DIR / "delay_model.pkl"
IMPORTANCES_PATH = THIS_DIR / "feature_importances.json"
METRICS_PATH = THIS_DIR.parent / "evaluation" / "ml" / "delay_model_metrics.json"

CATEGORICAL_FEATURES = ["route", "station", "weather", "day_type", "incident_type"]
NUMERIC_FEATURES = ["scheduled_hour"]
TARGET = "delay_minutes"


def load_and_engineer_features(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["scheduled_time", "actual_time"])
    df["scheduled_hour"] = df["scheduled_time"].dt.hour
    return df


def build_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
            ("num", "passthrough", NUMERIC_FEATURES),
        ]
    )

    model = GradientBoostingRegressor(
        n_estimators=300,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.9,
        random_state=42,
    )

    return Pipeline(steps=[("preprocess", preprocessor), ("model", model)])


def extract_feature_importances(pipeline: Pipeline) -> list[dict]:
    preprocessor = pipeline.named_steps["preprocess"]
    model = pipeline.named_steps["model"]

    cat_encoder: OneHotEncoder = preprocessor.named_transformers_["cat"]
    cat_feature_names = list(cat_encoder.get_feature_names_out(CATEGORICAL_FEATURES))
    all_feature_names = cat_feature_names + NUMERIC_FEATURES

    importances = model.feature_importances_
    ranked = sorted(
        zip(all_feature_names, importances), key=lambda x: x[1], reverse=True
    )
    return [{"feature": name, "importance": float(score)} for name, score in ranked[:20]]


def main():
    print(f"Loading dataset from {DATA_PATH} ...")
    df = load_and_engineer_features(DATA_PATH)

    X = df[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    pipeline = build_pipeline()
    print("Training GradientBoostingRegressor ...")
    pipeline.fit(X_train, y_train)

    preds = pipeline.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    rmse = float(np.sqrt(mean_squared_error(y_test, preds)))
    r2 = r2_score(y_test, preds)

    metrics = {
        "model": "GradientBoostingRegressor",
        "n_train": len(X_train),
        "n_test": len(X_test),
        "mae_minutes": round(mae, 3),
        "rmse_minutes": round(rmse, 3),
        "r2": round(r2, 4),
    }

    print("\nHeld-out test metrics:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    importances = extract_feature_importances(pipeline)
    print("\nTop feature importances:")
    for item in importances[:8]:
        print(f"  {item['feature']}: {item['importance']:.4f}")

    # --- persist artifacts ---
    joblib.dump(pipeline, MODEL_PATH)
    print(f"\nSaved model -> {MODEL_PATH}")

    with open(IMPORTANCES_PATH, "w") as f:
        json.dump(importances, f, indent=2)
    print(f"Saved feature importances -> {IMPORTANCES_PATH}")

    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(METRICS_PATH, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Saved metrics -> {METRICS_PATH}")


if __name__ == "__main__":
    main()
