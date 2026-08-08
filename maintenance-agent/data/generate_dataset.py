"""
Generates a synthetic maintenance sensor/log dataset.
Run: python -m data.generate_dataset
Output: maintenance-agent/data/maintenance_logs.csv
"""

import pandas as pd
import numpy as np
import os

RANDOM_SEED = 42
N_RECORDS = 500
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "maintenance_logs.csv")

TRAIN_IDS = [f"TR-{i:03d}" for i in range(1, 21)]
COMPONENTS = ["braking system", "traction motor", "bogie", "compressor", "pantograph", "gearbox"]

TECHNICIAN_NOTES_GREEN = [
    "Routine inspection completed. All systems nominal.",
    "Checked and lubricated. No issues found.",
    "Preventive maintenance done. Component within spec.",
]
TECHNICIAN_NOTES_AMBER = [
    "Minor vibration observed on component, monitor closely.",
    "Temperature slightly elevated. Schedule follow-up in 2 weeks.",
    "Oil pressure borderline. Recommend service within 30 days.",
    "Some wear detected on part BR-4021. Not critical yet.",
]
TECHNICIAN_NOTES_RED = [
    "Excessive vibration detected. Immediate inspection required.",
    "Oil pressure critically low. Do not operate until serviced.",
    "Component overheating. Shutdown recommended. Ref manual section 4.2.",
    "Visible crack on coupling PN-8801. Immediate replacement needed.",
]


def assign_label(row: pd.Series) -> str:
    issues = 0
    if row["vibration_level"] > 5:
        issues += 2
    if row["temperature_celsius"] > 95:
        issues += 2
    if row["oil_pressure_bar"] < 1.5 or row["oil_pressure_bar"] > 6.0:
        issues += 1
    if row["days_since_last_service"] > 120:
        issues += 2
    elif row["days_since_last_service"] > 90:
        issues += 1
    if issues >= 3:
        return "RED"
    if issues >= 1:
        return "AMBER"
    return "GREEN"


def main():
    rng = np.random.default_rng(RANDOM_SEED)

    df = pd.DataFrame(
        {
            "train_id": rng.choice(TRAIN_IDS, N_RECORDS),
            "component": rng.choice(COMPONENTS, N_RECORDS),
            "vibration_level": rng.uniform(0, 8, N_RECORDS).round(2),
            "temperature_celsius": rng.uniform(50, 110, N_RECORDS).round(1),
            "oil_pressure_bar": rng.uniform(0.5, 7.5, N_RECORDS).round(2),
            "days_since_last_service": rng.integers(0, 180, N_RECORDS),
            "mileage_km": rng.integers(0, 200_000, N_RECORDS),
        }
    )

    df["health_label"] = df.apply(assign_label, axis=1)

    def pick_note(label):
        pool = {"GREEN": TECHNICIAN_NOTES_GREEN, "AMBER": TECHNICIAN_NOTES_AMBER, "RED": TECHNICIAN_NOTES_RED}
        return rng.choice(pool[label])

    df["technician_notes"] = df["health_label"].apply(pick_note)
    df["last_service_date"] = pd.to_datetime("2026-08-08") - pd.to_timedelta(
        df["days_since_last_service"], unit="d"
    )
    df["last_service_date"] = df["last_service_date"].dt.date.astype(str)

    df.to_csv(OUTPUT_PATH, index=False)
    print(f"Saved {len(df)} records to {OUTPUT_PATH}")
    print(df["health_label"].value_counts())


if __name__ == "__main__":
    main()
