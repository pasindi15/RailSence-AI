"""
fraud/train_model.py — Isolation Forest training script (Phase 3)

Trains an unsupervised Isolation Forest on the synthetic booking dataset and
saves the model artifact + feature importances for use by the Hub API.

Steps:
  1. Load booking_events.csv (run dataset.py first if missing)
  2. Select the 6 numeric feature columns (drop event_id, user_id, label)
  3. 80/20 stratified train/test split (stratified by label for evaluation)
  4. Fit IsolationForest(n_estimators=200, contamination=0.08)
  5. Save model to fraud_model.pkl via joblib
  6. Compute feature importances via permutation on anomaly score
  7. Save feature_importances.json
  8. Print held-out evaluation metrics

Run:
  python train_model.py          (from this directory)
  Set-Location M3-security-agent\\fraud; python train_model.py  (PowerShell)
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE       = Path(__file__).parent
CSV_PATH   = HERE / "booking_events.csv"
MODEL_PATH = HERE / "fraud_model.pkl"
IMP_PATH   = HERE / "feature_importances.json"

# ---------------------------------------------------------------------------
# Feature columns used for training (unsupervised — no label)
# ---------------------------------------------------------------------------
FEATURE_COLS = [
    "timestamp",
    "route_id",
    "ticket_price",
    "bookings_last_60s",
    "travel_distance_km",
    "time_since_last_booking",
]

ANOMALY_THRESHOLD = 0.04   # score < this -> HIGH risk (tuned to score distribution)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_to_label(score: float) -> str:
    if score > -0.10:
        return "LOW"
    if score > ANOMALY_THRESHOLD:
        return "MEDIUM"
    return "HIGH"


def _compute_feature_importances(
    model: IsolationForest,
    X: np.ndarray,
    feature_names: list[str],
    n_repeats: int = 5,
) -> dict[str, float]:
    """
    Estimate feature importance by permutation:
    for each feature, shuffle its values and measure how much the mean
    anomaly score changes. Larger change = more important feature.
    """
    baseline = model.decision_function(X).mean()
    importances: dict[str, float] = {}

    rng = np.random.default_rng(42)
    for i, name in enumerate(feature_names):
        deltas = []
        for _ in range(n_repeats):
            X_perm = X.copy()
            rng.shuffle(X_perm[:, i])
            perm_score = model.decision_function(X_perm).mean()
            deltas.append(abs(baseline - perm_score))
        importances[name] = round(float(np.mean(deltas)), 6)

    # Normalize to sum to 1
    total = sum(importances.values()) or 1.0
    return {k: round(v / total, 4) for k, v in
            sorted(importances.items(), key=lambda x: x[1], reverse=True)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def train(csv_path: Path = CSV_PATH) -> None:
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found. Run dataset.py first.")
        return

    # ── Load data ──────────────────────────────────────────────────────────
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} rows  |  normal={( df['label']=='normal').sum()}  anomalous={(df['label']=='anomalous').sum()}")

    X = df[FEATURE_COLS].values.astype(float)
    y = (df["label"] == "anomalous").astype(int).values   # 1 = anomalous, for eval only

    # ── Train / test split ─────────────────────────────────────────────────
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )
    print(f"Train: {len(X_train)} rows  |  Test: {len(X_test)} rows")

    # ── Train IsolationForest in a scaled pipeline ─────────────────────────
    print("Training IsolationForest pipeline (StandardScaler + n_estimators=200, contamination=0.08) ...")
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("iforest", IsolationForest(
            n_estimators=200,
            contamination=0.08,
            max_samples="auto",
            random_state=42,
            n_jobs=-1,
        )),
    ])
    model.fit(X_train)

    # ── Save model ─────────────────────────────────────────────────────────
    joblib.dump(model, MODEL_PATH)
    print("Model saved -> " + str(MODEL_PATH))

    # ── Feature importances ────────────────────────────────────────────────
    print("Computing feature importances (permutation, 5 repeats per feature) ...")
    importances = _compute_feature_importances(model, X_train, FEATURE_COLS)
    with open(IMP_PATH, "w") as f:
        json.dump(importances, f, indent=2)
    print("Feature importances saved -> " + str(IMP_PATH))
    for feat, imp in importances.items():
        bar = "|" * int(imp * 50)
        print(f"  {feat:<28} {imp:.4f}  {bar}")

    # ── Held-out evaluation ────────────────────────────────────────────────
    print("\nEvaluating on held-out test set ...")
    scores = model.decision_function(X_test)
    predicted_anomaly = (scores < ANOMALY_THRESHOLD).astype(int)

    # True positives / negatives among actual anomalies and normals
    tp = int(((predicted_anomaly == 1) & (y_test == 1)).sum())
    fn = int(((predicted_anomaly == 0) & (y_test == 1)).sum())
    fp = int(((predicted_anomaly == 1) & (y_test == 0)).sum())
    tn = int(((predicted_anomaly == 0) & (y_test == 0)).sum())

    n_actual_anom  = tp + fn
    n_actual_norm  = fp + tn

    detection_rate = tp / n_actual_anom if n_actual_anom else 0.0
    fpr            = fp / n_actual_norm if n_actual_norm else 0.0
    precision      = tp / (tp + fp) if (tp + fp) else 0.0
    recall         = detection_rate

    print(f"\n  Actual anomalies in test:  {n_actual_anom}")
    print(f"  Actual normals in test:    {n_actual_norm}")
    print(f"  Threshold:                 {ANOMALY_THRESHOLD}")
    print(f"  True Positives:            {tp}")
    print(f"  False Negatives:           {fn}")
    print(f"  False Positives:           {fp}")
    print(f"  True Negatives:            {tn}")
    print(f"\n  Detection rate (recall):   {detection_rate:.1%}")
    print(f"  False positive rate:       {fpr:.1%}")
    print(f"  Precision:                 {precision:.1%}")
    print(f"\nTraining complete.")


if __name__ == "__main__":
    train()
