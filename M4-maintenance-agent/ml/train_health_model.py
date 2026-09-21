"""Train per-asset-type HistGradientBoostingRegressor models for health score prediction.

Three separate models (diesel_engine, bogie, brake_system) — each trained only on its
own sensor features, eliminating zero-fill noise from cross-type sensors.
New engineered features: fault_severity (0-5 scale) and overdue_days (days past interval).

Usage:
    python M4-maintenance-agent/ml/train_health_model.py
"""

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import cross_val_score, train_test_split

ML_DIR = Path(__file__).parent
AGENT_DIR = ML_DIR.parent
DATA_PATH = AGENT_DIR / "data" / "assets_history.csv"
MODEL_PATH = ML_DIR / "health_model.pkl"
IMPORTANCE_PATH = ML_DIR / "feature_importances.json"
METRICS_PATH = AGENT_DIR / "evaluation" / "ml" / "health_model_metrics.json"

TARGET = "health_score"

TYPE_FEATURES = {
    "diesel_engine": [
        "days_since_service", "fault_count_30d", "fault_severity", "overdue_days",
        "temperature_celsius", "vibration_level", "oil_pressure_bar", "fuel_efficiency_pct",
    ],
    "bogie": [
        "days_since_service", "fault_count_30d", "fault_severity", "overdue_days",
        "vibration_level", "axle_temp_celsius", "wheel_profile_mm",
    ],
    "brake_system": [
        "days_since_service", "fault_count_30d", "fault_severity", "overdue_days",
        "pad_thickness_mm", "brake_cylinder_pressure_bar", "stopping_distance_m",
    ],
}


def load_data() -> pd.DataFrame:
    if not DATA_PATH.exists():
        print(f"Dataset not found at {DATA_PATH}. Generating...")
        sys.path.insert(0, str(AGENT_DIR / "data"))
        import generate_dataset
        import csv
        all_records = []
        for asset in generate_dataset.TRAIN_ASSETS:
            all_records.extend(generate_dataset.generate_asset_history(asset, n_records=60))
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DATA_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_records[0].keys()))
            writer.writeheader()
            writer.writerows(all_records)
        print(f"Generated {len(all_records)} records.")
    return pd.read_csv(DATA_PATH)


def train_type_model(df: pd.DataFrame, asset_type: str):
    subset = df[df["asset_type"] == asset_type].copy()
    features = [f for f in TYPE_FEATURES[asset_type] if f in subset.columns]
    subset[features] = subset[features].fillna(0)

    X = subset[features]
    y = subset[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = HistGradientBoostingRegressor(
        max_iter=400,
        learning_rate=0.04,
        max_depth=5,
        min_samples_leaf=8,
        l2_regularization=0.1,
        random_state=42,
    )
    model.fit(X_train, y_train)

    y_pred = np.clip(model.predict(X_test), 0, 100)
    mae = float(mean_absolute_error(y_test, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    r2 = float(r2_score(y_test, y_pred))
    cv = cross_val_score(model, X, y, cv=5, scoring="r2")

    print(f"\n  {asset_type}")
    print(f"    MAE={mae:.4f}  RMSE={rmse:.4f}  R²={r2:.4f}  CV-R²={cv.mean():.4f}±{cv.std():.4f}")
    print(f"    Train={len(X_train)}  Test={len(X_test)}")

    # Permutation importance
    perm = permutation_importance(model, X, y, n_repeats=8, random_state=42, n_jobs=-1)
    imp_pairs = sorted(
        zip(features, perm.importances_mean.tolist()),
        key=lambda x: x[1], reverse=True
    )

    return model, mae, rmse, r2, features, imp_pairs


def train() -> None:
    df = load_data()
    print(f"Loaded {len(df)} rows  |  asset types: {df['asset_type'].value_counts().to_dict()}")

    models: dict = {}
    all_importances: list = []
    all_metrics: dict = {}

    for asset_type in ["diesel_engine", "bogie", "brake_system"]:
        model, mae, rmse, r2, features, imp_pairs = train_type_model(df, asset_type)
        models[asset_type] = {"model": model, "features": features, "mae": round(mae, 4)}
        all_metrics[asset_type] = {"mae": round(mae, 4), "rmse": round(rmse, 4), "r2": round(r2, 4)}
        for feat, imp in imp_pairs[:6]:
            all_importances.append({
                "feature": feat,
                "importance": round(max(0.0, imp), 6),
                "asset_type": asset_type,
            })

    bundle = {
        "models": models,
        "version": "phase3-hgbr-per-type-v1",
    }
    joblib.dump(bundle, MODEL_PATH)
    print(f"\nModel bundle saved -> {MODEL_PATH}")

    IMPORTANCE_PATH.write_text(json.dumps(all_importances, indent=2))
    print(f"Feature importances -> {IMPORTANCE_PATH}")

    maes = [v["mae"] for v in all_metrics.values()]
    r2s  = [v["r2"]  for v in all_metrics.values()]
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    metrics = {
        "model": "HistGradientBoostingRegressor (per-type)",
        "version": "phase3-hgbr-per-type-v1",
        "asset_types": all_metrics,
        "overall_mae_avg": round(sum(maes) / len(maes), 4),
        "overall_r2_avg":  round(sum(r2s)  / len(r2s),  4),
        "total_rows": len(df),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    print(f"Metrics -> {METRICS_PATH}")
    print(f"\nOverall  MAE={metrics['overall_mae_avg']}  R²={metrics['overall_r2_avg']}")


if __name__ == "__main__":
    train()
