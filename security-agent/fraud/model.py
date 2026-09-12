"""
security-agent/fraud/model.py
------------------------------
RailSense AI — Security & Fraud Agent ML Anomaly Detector.

Responsibilities:
1. Behavioral Anomaly Detection using scikit-learn IsolationForest.
2. Calibration of raw decision function output into a project-calibrated risk score (0.00 to 1.00).
3. Risk categorization:
   - 0.00 to 0.39: LOW (Action: ALLOW)
   - 0.40 to 0.69: MEDIUM (Action: REVIEW)
   - 0.70 to 1.00: HIGH (Action: REVIEW)
4. Explanatory reason code generation for human adjudicators.

Important Multi-Agent Governance:
- The ML model is purely an ADVISORY risk scoring component.
- The model NEVER creates, updates, or confirms a ticket directly.
- The risk score represents a normalized behavioral anomaly index, not a Bayesian probability.
"""

from __future__ import annotations

from typing import Any
import numpy as np
from sklearn.ensemble import IsolationForest


# Standard feature vector keys
FEATURE_KEYS = [
    "bookings_last_1_minute",
    "bookings_last_10_minutes",
    "bookings_last_24_hours",
    "cancellations_last_24_hours",
    "duplicate_attempts",
    "active_booking_count",
    "overlapping_trip_count",
    "conflicting_journey_attempts",
    "distinct_routes_last_hour",
    "seconds_since_previous_booking",
]


class FraudRiskDetector:
    """
    Behavioral anomaly detector for railway ticket purchases.
    Uses IsolationForest to identify bot-like, high-frequency, or irregular passenger behavior.
    """

    def __init__(self) -> None:
        self.feature_keys = FEATURE_KEYS
        self.model = IsolationForest(
            n_estimators=100,
            contamination=0.08,
            random_state=42,
        )
        self._is_fitted = False
        self._fit_baseline_model()

    def _fit_baseline_model(self) -> None:
        """
        Train IsolationForest on synthetic normal railway booking passenger distributions.
        Normal distributions:
        - 1 booking in last 24h, 0 in last 1m, 0 in last 10m
        - 0 cancellations
        - 0 duplicate attempts
        - 1-2 active bookings
        - seconds_since_previous_booking > 3600s
        """
        rng = np.random.default_rng(42)
        n_samples = 400

        # Normal samples
        b_1m = rng.choice([0, 0, 0, 0, 1], size=n_samples)
        b_10m = b_1m + rng.choice([0, 0, 1], size=n_samples)
        b_24h = b_10m + rng.choice([0, 1, 2], size=n_samples)
        canc = rng.choice([0, 0, 0, 1], size=n_samples)
        dup = rng.choice([0, 0, 0], size=n_samples)
        act = rng.choice([0, 1, 2], size=n_samples)
        overlap = rng.choice([0, 0, 0], size=n_samples)
        conflict = rng.choice([0, 0, 0], size=n_samples)
        routes = rng.choice([1, 1, 2], size=n_samples)
        sec_prev = rng.uniform(600, 86400, size=n_samples)

        X_normal = np.column_stack([
            b_1m, b_10m, b_24h, canc, dup, act, overlap, conflict, routes, sec_prev
        ])

        # Add a few anomaly exemplars to calibrate contamination boundary
        n_anom = 30
        a_1m = rng.integers(3, 10, size=n_anom)
        a_10m = rng.integers(6, 25, size=n_anom)
        a_24h = rng.integers(10, 50, size=n_anom)
        a_canc = rng.integers(3, 10, size=n_anom)
        a_dup = rng.integers(2, 6, size=n_anom)
        a_act = rng.integers(4, 12, size=n_anom)
        a_overlap = rng.integers(1, 4, size=n_anom)
        a_conflict = rng.integers(1, 4, size=n_anom)
        a_routes = rng.integers(3, 8, size=n_anom)
        a_sec = rng.uniform(1, 15, size=n_anom)

        X_anom = np.column_stack([
            a_1m, a_10m, a_24h, a_canc, a_dup, a_act, a_overlap, a_conflict, a_routes, a_sec
        ])

        X_train = np.vstack([X_normal, X_anom])
        self.model.fit(X_train)
        self._is_fitted = True

    def score_features(self, features: dict[str, float]) -> dict[str, Any]:
        """
        Evaluate behavioral features and return calibrated risk analysis.

        Returns
        -------
        dict containing:
        - risk_score: float (0.00 to 1.00)
        - risk_level: "LOW" | "MEDIUM" | "HIGH"
        - recommended_action: "ALLOW" | "REVIEW" | "REJECT"
        - reasons: list of explanation strings
        """
        # Vectorize features in deterministic order
        vec = []
        for k in self.feature_keys:
            vec.append(float(features.get(k, 0.0)))

        X = np.array([vec])

        # IsolationForest decision_function:
        # Higher score = more normal. Lower score = more anomalous.
        # Typical range: [-0.3, 0.3]
        raw_decision = float(self.model.decision_function(X)[0])

        # Sigmoid/linear projection to calibrated risk scale [0.0, 1.0]
        # raw ~ 0.15 -> risk ~ 0.15 (LOW)
        # raw ~ 0.00 -> risk ~ 0.50 (Contamination boundary / MEDIUM)
        # raw ~ -0.15 -> risk ~ 0.85 (HIGH)
        # We use a logistic curve centered near 0.0
        calibrated_risk = 1.0 / (1.0 + np.exp(12.0 * raw_decision))
        calibrated_risk = float(np.clip(calibrated_risk, 0.0, 1.0))
        calibrated_risk = round(calibrated_risk, 4)

        # Generate diagnostic explanation reasons
        reasons: list[str] = []
        b_1m = features.get("bookings_last_1_minute", 0.0)
        b_10m = features.get("bookings_last_10_minutes", 0.0)
        sec_prev = features.get("seconds_since_previous_booking", 999999.0)
        canc_24h = features.get("cancellations_last_24_hours", 0.0)
        active_count = features.get("active_booking_count", 0.0)
        dup_attempts = features.get("duplicate_attempts", 0.0)
        overlapping = features.get("overlapping_trip_count", 0.0)

        if b_1m >= 2.0 or sec_prev < 10.0:
            reasons.append(f"Rapid booking bursts: {int(b_1m)} requests in last minute ({int(sec_prev)}s since previous).")
        if b_10m >= 5.0:
            reasons.append(f"High aggregate booking velocity: {int(b_10m)} requests within 10 minutes.")
        if canc_24h >= 3.0:
            reasons.append(f"Unusual cancellation frequency: {int(canc_24h)} cancellations in past 24 hours.")
        if active_count >= 4.0:
            reasons.append(f"Elevated active booking holding count: {int(active_count)} concurrent tickets.")
        if dup_attempts >= 1.0:
            reasons.append(f"Recent rejected or duplicate ticket attempts detected ({int(dup_attempts)}).")
        if overlapping >= 1.0:
            reasons.append(f"Multiple journeys booked on same date ({int(overlapping)} existing trips).")

        # Fallback explanation if model flagged outlier but no single rule breached
        if calibrated_risk >= 0.40 and not reasons:
            reasons.append("Behavioral statistical pattern deviates from baseline passenger norms.")

        if not reasons:
            reasons.append("Standard legitimate passenger booking pattern.")

        # Determine risk level & action
        if calibrated_risk < 0.40:
            risk_level = "LOW"
            recommended_action = "ALLOW"
        elif calibrated_risk < 0.70:
            risk_level = "MEDIUM"
            recommended_action = "REVIEW"
        else:
            risk_level = "HIGH"
            recommended_action = "REVIEW"

        return {
            "risk_score": calibrated_risk,
            "risk_level": risk_level,
            "recommended_action": recommended_action,
            "reasons": reasons,
            "model": "IsolationForest",
        }


# Global detector singleton
fraud_detector = FraudRiskDetector()
