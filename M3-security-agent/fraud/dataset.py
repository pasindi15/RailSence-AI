"""
fraud/dataset.py — Synthetic booking event dataset generator (Phase 3)

Generates booking_events.csv with 5000 rows representing Sri Lanka Railways
passenger booking activity. ~8% of rows are injected anomalies covering four
realistic fraud/abuse patterns:

  1. Rapid automated purchasing  — many bookings within 60 seconds
  2. Impossible travel           — distant routes booked in unrealistically short time
  3. Ticket price outliers       — price > mean + 3σ (likely data error or fraud)
  4. Off-hours high-frequency    — midnight–4 am with > 2 bookings/min

Columns:
  event_id               — unique event identifier (string)
  user_id                — hashed numeric passenger identifier
  timestamp              — Unix timestamp of purchase
  route_id               — encoded route 0–6 (7 Sri Lanka Railways routes)
  ticket_price           — fare in Sri Lankan Rupees
  bookings_last_60s      — number of purchases by this user in the last 60 seconds
  travel_distance_km     — distance of the booked route
  time_since_last_booking — seconds since this user's previous purchase
  label                  — 'normal' or 'anomalous' (NOT passed to model — evaluation only)

Run:
  python dataset.py
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
SEED = 42
np.random.seed(SEED)
random.seed(SEED)

# ---------------------------------------------------------------------------
# Sri Lanka Railways routes (route_id → distance_km, typical price range Rs)
# ---------------------------------------------------------------------------
ROUTES = {
    0: {"name": "Colombo Fort - Kandy",          "km": 116, "price_mean": 350,  "price_std": 60},
    1: {"name": "Colombo Fort - Galle",           "km": 119, "price_mean": 370,  "price_std": 65},
    2: {"name": "Colombo Fort - Jaffna",          "km": 393, "price_mean": 950,  "price_std": 120},
    3: {"name": "Kandy - Badulla (Hill Country)", "km": 145, "price_mean": 420,  "price_std": 70},
    4: {"name": "Colombo Fort - Matara",          "km": 162, "price_mean": 480,  "price_std": 80},
    5: {"name": "Colombo Fort - Kurunegala",      "km": 95,  "price_mean": 280,  "price_std": 50},
    6: {"name": "Colombo Fort - Anuradhapura",    "km": 206, "price_mean": 620,  "price_std": 95},
}

N_TOTAL   = 5000
N_ANOMALY = int(N_TOTAL * 0.08)   # ~400 anomalous rows
N_NORMAL  = N_TOTAL - N_ANOMALY   # ~4600 normal rows

# Simulation base timestamp — midnight, 1 Jan 2026
BASE_TS = 1_767_225_600  # 2026-01-01T00:00:00 UTC


# ---------------------------------------------------------------------------
# Normal row generator
# ---------------------------------------------------------------------------

def _make_normal_rows(n: int) -> list[dict]:
    rows = []
    for i in range(n):
        route_id  = random.randint(0, 6)
        route     = ROUTES[route_id]
        user_id   = random.randint(1000, 9999)
        # Spread over 90 days; heavier usage during daytime (8 am – 10 pm)
        day_offset = random.uniform(0, 90 * 86400)
        hour_bias  = random.choices(
            range(24),
            weights=[1,1,1,1,1,2,3,5,8,8,7,7,8,8,7,7,7,8,8,8,6,4,2,1],
        )[0]
        ts = int(BASE_TS + day_offset - (day_offset % 86400) + hour_bias * 3600 + random.randint(0, 3599))

        price  = max(50, int(np.random.normal(route["price_mean"], route["price_std"])))
        b60    = random.choices([0, 1, 2], weights=[70, 25, 5])[0]
        t_last = int(np.random.exponential(scale=3600))   # avg 1 hour since last booking
        t_last = max(60, t_last)

        rows.append({
            "event_id":               f"evt_{i:05d}",
            "user_id":                user_id,
            "timestamp":              ts,
            "route_id":               route_id,
            "ticket_price":           price,
            "bookings_last_60s":      b60,
            "travel_distance_km":     route["km"],
            "time_since_last_booking": t_last,
            "label":                  "normal",
        })
    return rows


# ---------------------------------------------------------------------------
# Anomalous row generators — one function per pattern
# ---------------------------------------------------------------------------

def _rapid_purchasing(n: int, start_i: int) -> list[dict]:
    """Bot-like burst: many bookings within 60 s with very short intervals."""
    rows = []
    for i in range(n):
        route_id = random.randint(0, 6)
        route    = ROUTES[route_id]
        user_id  = random.randint(1000, 9999)
        ts       = int(BASE_TS + random.uniform(0, 90 * 86400))
        price    = max(50, int(np.random.normal(route["price_mean"], route["price_std"])))
        b60      = random.randint(8, 20)      # VERY high — clearly anomalous
        t_last   = random.randint(1, 5)       # 1-5 seconds since last

        rows.append({
            "event_id":               f"evt_a{start_i + i:04d}",
            "user_id":                user_id,
            "timestamp":              ts,
            "route_id":               route_id,
            "ticket_price":           price,
            "bookings_last_60s":      b60,
            "travel_distance_km":     route["km"],
            "time_since_last_booking": t_last,
            "label":                  "anomalous",
        })
    return rows


def _impossible_travel(n: int, start_i: int) -> list[dict]:
    """Extreme distance + near-zero time between bookings — physically impossible."""
    rows = []
    for i in range(n):
        route_id = random.choice([2, 6])     # long routes only
        route    = ROUTES[route_id]
        user_id  = random.randint(1000, 9999)
        ts       = int(BASE_TS + random.uniform(0, 90 * 86400))
        price    = max(50, int(np.random.normal(route["price_mean"], route["price_std"])))
        b60      = random.randint(3, 7)
        t_last   = random.randint(1, 8)      # 1-8 seconds — physically impossible

        rows.append({
            "event_id":               f"evt_a{start_i + i:04d}",
            "user_id":                user_id,
            "timestamp":              ts,
            "route_id":               route_id,
            "ticket_price":           price,
            "bookings_last_60s":      b60,
            "travel_distance_km":     route["km"] + random.randint(300, 600),  # extreme spike
            "time_since_last_booking": t_last,
            "label":                  "anomalous",
        })
    return rows


def _price_outliers(n: int, start_i: int) -> list[dict]:
    """Ticket prices far outside the normal distribution (> mean + 5sigma)."""
    rows = []
    for i in range(n):
        route_id = random.randint(0, 6)
        route    = ROUTES[route_id]
        user_id  = random.randint(1000, 9999)
        ts       = int(BASE_TS + random.uniform(0, 90 * 86400))
        # Price 5-10 standard deviations above mean — clearly anomalous
        outlier_price = int(route["price_mean"] + random.uniform(5, 10) * route["price_std"])
        b60    = random.choices([0, 1, 2], weights=[60, 30, 10])[0]
        t_last = int(np.random.exponential(scale=3600))
        t_last = max(60, t_last)

        rows.append({
            "event_id":               f"evt_a{start_i + i:04d}",
            "user_id":                user_id,
            "timestamp":              ts,
            "route_id":               route_id,
            "ticket_price":           outlier_price,
            "bookings_last_60s":      b60,
            "travel_distance_km":     route["km"],
            "time_since_last_booking": t_last,
            "label":                  "anomalous",
        })
    return rows


def _offhours_burst(n: int, start_i: int) -> list[dict]:
    """Midnight-4am high-frequency purchasing with extreme bookings_last_60s."""
    rows = []
    for i in range(n):
        route_id = random.randint(0, 6)
        route    = ROUTES[route_id]
        user_id  = random.randint(1000, 9999)
        # Force midnight-4 am timestamp
        day_offset = random.uniform(0, 90 * 86400)
        hour       = random.uniform(0, 4)
        ts         = int(BASE_TS + day_offset - (day_offset % 86400) + hour * 3600)
        price  = max(50, int(np.random.normal(route["price_mean"], route["price_std"])))
        b60    = random.randint(10, 20)      # extreme late-night burst
        t_last = random.randint(2, 10)       # very rapid

        rows.append({
            "event_id":               f"evt_a{start_i + i:04d}",
            "user_id":                user_id,
            "timestamp":              ts,
            "route_id":               route_id,
            "ticket_price":           price,
            "bookings_last_60s":      b60,
            "travel_distance_km":     route["km"],
            "time_since_last_booking": t_last,
            "label":                  "anomalous",
        })
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_dataset(output_path: str = "booking_events.csv") -> pd.DataFrame:
    # Split anomalies equally across the 4 patterns
    each = N_ANOMALY // 4
    remainder = N_ANOMALY - each * 4

    normal_rows   = _make_normal_rows(N_NORMAL)
    anomaly_rows  = []
    anomaly_rows += _rapid_purchasing(each,            start_i=0)
    anomaly_rows += _impossible_travel(each,           start_i=each)
    anomaly_rows += _price_outliers(each + remainder,  start_i=each * 2)
    anomaly_rows += _offhours_burst(each,              start_i=each * 3)

    all_rows = normal_rows + anomaly_rows
    random.shuffle(all_rows)

    df = pd.DataFrame(all_rows)
    df.to_csv(output_path, index=False)

    n_anom = (df["label"] == "anomalous").sum()
    n_norm = (df["label"] == "normal").sum()
    print(f"Dataset generated: {len(df)} rows  |  normal={n_norm}  anomalous={n_anom}  ({n_anom/len(df)*100:.1f}%)")
    print(f"Saved to: {output_path}")
    return df


if __name__ == "__main__":
    out = Path(__file__).parent / "booking_events.csv"
    generate_dataset(str(out))
