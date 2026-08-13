"""
evaluation/fraud/evaluate_fraud.py — Fraud detection evaluation script (Phase 3)

Loads the trained IsolationForest model and the full booking_events.csv dataset,
runs the held-out test set through the model, and writes real measured metrics
to evaluation/fraud/fraud_metrics.json.

Run from the repository root:
  python M3-security-agent/evaluation/fraud/evaluate_fraud.py

Or from the M3-security-agent directory:
  python evaluation/fraud/evaluate_fraud.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow imports from M3-security-agent root
M3_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(M3_ROOT))

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FRAUD_DIR  = M3_ROOT / "fraud"
MODEL_PATH = FRAUD_DIR / "fraud_model.pkl"
CSV_PATH   = FRAUD_DIR / "booking_events.csv"
OUT_PATH   = Path(__file__).parent / "fraud_metrics.json"

FEATURE_COLS = [
    "timestamp",
    "route_id",
    "ticket_price",
    "bookings_last_60s",
    "travel_distance_km",
    "time_since_last_booking",
]

THRESHOLD_HIGH   = 0.04
THRESHOLD_MEDIUM = 0.07


def evaluate() -> None:
    # ── Checks ────────────────────────────────────────────────────────────
    if not MODEL_PATH.exists():
        print(f"ERROR: Model not found at {MODEL_PATH}")
        print("Run: Set-Location M3-security-agent\\fraud; python train_model.py")
        return

    if not CSV_PATH.exists():
        print(f"ERROR: Dataset not found at {CSV_PATH}")
        print("Run: Set-Location M3-security-agent\\fraud; python dataset.py")
        return

    # ── Load ──────────────────────────────────────────────────────────────
    model = joblib.load(MODEL_PATH)
    df    = pd.read_csv(CSV_PATH)

    X = df[FEATURE_COLS].values.astype(float)
    y = (df["label"] == "anomalous").astype(int).values

    _, X_test, _, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    # ── Score ─────────────────────────────────────────────────────────────
    scores = model.decision_function(X_test)

    predicted_high_medium = (scores < THRESHOLD_MEDIUM).astype(int)   # MEDIUM + HIGH
    predicted_high        = (scores < THRESHOLD_HIGH).astype(int)     # HIGH only

    tp_hm = int(((predicted_high_medium == 1) & (y_test == 1)).sum())
    fn_hm = int(((predicted_high_medium == 0) & (y_test == 1)).sum())
    fp_hm = int(((predicted_high_medium == 1) & (y_test == 0)).sum())
    tn_hm = int(((predicted_high_medium == 0) & (y_test == 0)).sum())

    tp_h  = int(((predicted_high == 1) & (y_test == 1)).sum())
    fn_h  = int(((predicted_high == 0) & (y_test == 1)).sum())
    fp_h  = int(((predicted_high == 1) & (y_test == 0)).sum())

    n_anom = int(y_test.sum())
    n_norm = int((y_test == 0).sum())

    detection_rate_hm = tp_hm / n_anom if n_anom else 0.0
    fpr_hm            = fp_hm / n_norm if n_norm else 0.0
    precision_hm      = tp_hm / (tp_hm + fp_hm) if (tp_hm + fp_hm) else 0.0

    detection_rate_h  = tp_h / n_anom if n_anom else 0.0
    fpr_h             = fp_h / n_norm if n_norm else 0.0
    precision_h       = tp_h / (tp_h + fp_h) if (tp_h + fp_h) else 0.0

    # Score distribution
    score_dist = {
        "min":    round(float(scores.min()), 4),
        "max":    round(float(scores.max()), 4),
        "mean":   round(float(scores.mean()), 4),
        "median": round(float(np.median(scores)), 4),
        "p25":    round(float(np.percentile(scores, 25)), 4),
        "p75":    round(float(np.percentile(scores, 75)), 4),
    }

    # Risk level distribution on test set
    risk_counts = {
        "HIGH":   int((scores < THRESHOLD_HIGH).sum()),
        "MEDIUM": int(((scores >= THRESHOLD_HIGH) & (scores < THRESHOLD_MEDIUM)).sum()),
        "LOW":    int((scores >= THRESHOLD_MEDIUM).sum()),
    }

    # ── Build output ──────────────────────────────────────────────────────
    metrics = {
        "model_version":      "phase3-iforest-v1",
        "dataset_rows":       len(df),
        "test_rows":          len(X_test),
        "actual_anomalies":   n_anom,
        "actual_normals":     n_norm,
        "threshold_high":     THRESHOLD_HIGH,
        "threshold_medium":   THRESHOLD_MEDIUM,
        "detection_rate_HIGH_MEDIUM": round(detection_rate_hm, 4),
        "false_positive_rate_HIGH_MEDIUM": round(fpr_hm, 4),
        "precision_HIGH_MEDIUM": round(precision_hm, 4),
        "recall_HIGH_MEDIUM": round(detection_rate_hm, 4),
        "detection_rate_HIGH_only": round(detection_rate_h, 4),
        "false_positive_rate_HIGH_only": round(fpr_h, 4),
        "precision_HIGH_only": round(precision_h, 4),
        "confusion_matrix_HIGH_MEDIUM": {
            "TP": tp_hm, "FN": fn_hm, "FP": fp_hm, "TN": tn_hm,
        },
        "score_distribution": score_dist,
        "risk_level_distribution_test": risk_counts,
    }

    # ── Write output ──────────────────────────────────────────────────────
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"Evaluation complete. Results written to {OUT_PATH}\n")
    print(f"  Test rows:               {len(X_test)}")
    print(f"  Actual anomalies:        {n_anom}")
    print(f"  Actual normals:          {n_norm}")
    print(f"  Threshold (HIGH):        {THRESHOLD_HIGH}")
    print(f"  Threshold (MEDIUM):      {THRESHOLD_MEDIUM}")
    print()
    print(f"  Detection rate (HIGH+MED): {detection_rate_hm:.1%}")
    print(f"  False positive rate:       {fpr_hm:.1%}")
    print(f"  Precision  (HIGH+MED):     {precision_hm:.1%}")
    print(f"  Recall     (HIGH+MED):     {detection_rate_hm:.1%}")
    print()
    print(f"  Risk level distribution on test set:")
    for level, count in risk_counts.items():
        print(f"    {level:<8} {count:>4}  ({count/len(X_test)*100:.1f}%)")


if __name__ == "__main__":
    evaluate()
