"""
M2 — Operations & Delay-Prediction Agent
Synthetic historical dataset generator.

Produces operations_history.csv with columns:
route, station, scheduled_time, actual_time, weather, day_type,
incident_type, delay_minutes

This single dataset is used for:
  - Phase 2: training the delay-prediction ML model
  - Phase 4: the IR/RAG corpus (incident descriptions -> embeddings)

Run:
    python generate_dataset.py
"""

import random
import uuid
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

random.seed(42)
np.random.seed(42)

# ---------------------------------------------------------------------------
# Reference data (Sri Lanka Railways-flavoured, matches the Passenger Agent's
# example route "Colombo Fort - Kandy" / train PM-4082 used elsewhere in the
# project so cross-agent demos line up).
# ---------------------------------------------------------------------------

ROUTES = [
    ("Colombo Fort - Kandy", ["Colombo Fort", "Peradeniya", "Kandy"]),
    ("Colombo Fort - Galle", ["Colombo Fort", "Panadura", "Kalutara", "Galle"]),
    ("Colombo Fort - Jaffna", ["Colombo Fort", "Anuradhapura", "Vavuniya", "Jaffna"]),
    ("Colombo Fort - Badulla", ["Colombo Fort", "Nanu Oya", "Ella", "Badulla"]),
    ("Colombo Fort - Trincomalee", ["Colombo Fort", "Polgahawela", "Trincomalee"]),
    ("Colombo Fort - Matara", ["Colombo Fort", "Galle", "Matara"]),
    ("Colombo Fort - Batticaloa", ["Colombo Fort", "Polonnaruwa", "Batticaloa"]),
]

TRAIN_PREFIXES = ["PM", "UD", "YD", "IC", "ND"]  # Podi Menike, Udarata Menike, etc. style codes

WEATHER_OPTIONS = ["clear", "light_rain", "heavy_rain", "fog", "extreme_heat"]
WEATHER_WEIGHTS = [0.50, 0.22, 0.10, 0.08, 0.10]

DAY_TYPES = ["weekday", "weekend", "public_holiday"]
DAY_TYPE_WEIGHTS = [0.68, 0.24, 0.08]

INCIDENT_TYPES = ["none", "signal_fault", "mechanical", "weather", "track_obstruction", "staffing"]

# Base delay (minutes) contributed by each incident type, before noise
INCIDENT_BASE_DELAY = {
    "none": 0,
    "signal_fault": 12,
    "mechanical": 18,
    "weather": 9,
    "track_obstruction": 15,
    "staffing": 6,
}

# Free-text templates staff might log for an incident (feeds Phase 3 NLP + Phase 4 RAG)
INCIDENT_NOTE_TEMPLATES = {
    "signal_fault": [
        "Signal failure reported near {station}, trains held for {mins} minutes while technicians reset the interlocking system.",
        "Automatic signal at {station} stuck on red, manual override required, causing delays through the section.",
    ],
    "mechanical": [
        "Locomotive on {train_id} reported engine overheating near {station}, replacement unit dispatched.",
        "Brake system fault detected on {train_id}, inspected and cleared at {station} before continuing.",
    ],
    "weather": [
        "Heavy rain near {station} reduced visibility and required speed restrictions on the approach.",
        "Flooding risk reported on the track bed near {station}, service ran at reduced speed as a precaution.",
    ],
    "track_obstruction": [
        "Fallen tree on the line near {station} required manual clearance before {train_id} could proceed.",
        "Livestock on the track near {station} caused an unscheduled stop.",
    ],
    "staffing": [
        "Delayed departure from {station} due to late arrival of relief crew for {train_id}.",
        "Platform staff shortage at {station} slowed boarding and dispatch.",
    ],
    "none": [
        "No incidents reported; {train_id} operated on schedule through {station}.",
    ],
}


def weighted_choice(options, weights):
    return random.choices(options, weights=weights, k=1)[0]


def make_train_id():
    prefix = random.choice(TRAIN_PREFIXES)
    number = random.randint(1000, 9999)
    return f"{prefix}-{number}"


def sample_scheduled_time(base_date):
    """Sample a departure time with morning/evening peak weighting."""
    hour_weights = {h: 1 for h in range(5, 23)}
    for h in (6, 7, 8, 17, 18, 19):
        hour_weights[h] = 4
    hours = list(hour_weights.keys())
    weights = list(hour_weights.values())
    hour = random.choices(hours, weights=weights, k=1)[0]
    minute = random.choice([0, 5, 10, 15, 20, 30, 35, 40, 45, 50])
    return base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)


def sample_delay_minutes(weather, day_type, incident_type):
    base = INCIDENT_BASE_DELAY[incident_type]

    weather_add = {
        "clear": 0,
        "light_rain": 2,
        "heavy_rain": 7,
        "fog": 5,
        "extreme_heat": 3,
    }[weather]

    day_add = {"weekday": 0, "weekend": -1, "public_holiday": 4}[day_type]

    noise = np.random.normal(loc=0, scale=3)
    delay = base + weather_add + day_add + noise

    # Small chance of an early arrival on an otherwise clean run
    if incident_type == "none" and weather == "clear" and random.random() < 0.15:
        delay -= random.uniform(1, 3)

    return round(max(delay, -2), 1)  # allow slightly early trains, floor at -2 min


def generate_incident_note(incident_type, station, train_id, delay_minutes):
    template = random.choice(INCIDENT_NOTE_TEMPLATES[incident_type])
    return template.format(station=station, train_id=train_id, mins=max(int(delay_minutes), 1))


def generate_rows(n_rows: int, start_date: datetime, days_span: int) -> pd.DataFrame:
    rows = []
    for _ in range(n_rows):
        route_name, stations = random.choice(ROUTES)
        station = random.choice(stations)
        train_id = make_train_id()

        day_offset = random.randint(0, days_span)
        base_date = start_date + timedelta(days=day_offset)

        scheduled_time = sample_scheduled_time(base_date)

        weather = weighted_choice(WEATHER_OPTIONS, WEATHER_WEIGHTS)
        day_type = weighted_choice(DAY_TYPES, DAY_TYPE_WEIGHTS)

        # Weather influences incident likelihood (e.g. heavy_rain -> more weather/mechanical incidents)
        if weather in ("heavy_rain", "fog"):
            incident_type = weighted_choice(
                INCIDENT_TYPES, [0.35, 0.15, 0.15, 0.20, 0.10, 0.05]
            )
        else:
            incident_type = weighted_choice(
                INCIDENT_TYPES, [0.55, 0.12, 0.12, 0.05, 0.09, 0.07]
            )

        delay_minutes = sample_delay_minutes(weather, day_type, incident_type)
        actual_time = scheduled_time + timedelta(minutes=delay_minutes)

        incident_note = (
            generate_incident_note(incident_type, station, train_id, delay_minutes)
            if incident_type != "none"
            else ""
        )

        rows.append(
            {
                "record_id": str(uuid.uuid4()),
                "route": route_name,
                "station": station,
                "train_id": train_id,
                "scheduled_time": scheduled_time.isoformat(),
                "actual_time": actual_time.isoformat(),
                "weather": weather,
                "day_type": day_type,
                "incident_type": incident_type,
                "incident_note": incident_note,
                "delay_minutes": delay_minutes,
            }
        )

    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = generate_rows(n_rows=3000, start_date=datetime(2025, 1, 1), days_span=210)
    df = df.sort_values("scheduled_time").reset_index(drop=True)

    out_path = "operations_history.csv"
    df.to_csv(out_path, index=False)

    print(f"Generated {len(df)} rows -> {out_path}")
    print("\nColumn summary:")
    print(df.dtypes)
    print("\nDelay minutes stats:")
    print(df["delay_minutes"].describe())
    print("\nIncident type counts:")
    print(df["incident_type"].value_counts())
