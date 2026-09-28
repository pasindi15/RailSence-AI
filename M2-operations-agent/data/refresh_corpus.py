"""Bring the operations corpus up to date (idempotent).

operations_history.csv was generated once for 2025-01-01 .. 2025-07-30. This
script keeps every existing record (record_id, train_id, route, station,
incident note, delay) and only:

1. Shifts all scheduled/actual timestamps forward so the corpus ends on the
   given end date (default: yesterday, Sri Lanka time). No ML feature uses the
   calendar date (route, hour, day type, weather, station, incident type), so
   the trained model and the pgvector embeddings (keyed by record_id, no dates)
   stay valid.
2. Adds a denser batch of recent records for the last RECENT_DAYS days, drawn
   from the same distributions as generate_dataset.py and re-using each route's
   existing train ids, so nothing points at a train the shared registry
   doesn't know. Their record ids are deterministic (uuid5), so re-running
   never duplicates them.

Run from M2-operations-agent/:
    python data/refresh_corpus.py                      # CSV only
    python data/refresh_corpus.py --supabase --embed   # also upsert + index new notes
Then retrain:  python ml/train_delay_model.py
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent
AGENT_DIR = DATA_DIR.parent
CSV_PATH = DATA_DIR / "operations_history.csv"
RECENT_NAMESPACE = uuid.UUID("5b0a6f7e-2d1c-4c1e-9b7a-6d2f0e4c8a11")
RECENT_DAYS = 60
RECENT_ROWS = 900

sys.path.insert(0, str(DATA_DIR))
import generate_dataset as gen  # noqa: E402  (same distributions and note templates)


def _yesterday_colombo() -> datetime:
    now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    return datetime(now.year, now.month, now.day) - timedelta(days=1)


def shift_to(frame: pd.DataFrame, end_date: datetime) -> int:
    sched = pd.to_datetime(frame["scheduled_time"])
    offset = (end_date.date() - sched.max().date()).days
    if offset:
        delta = pd.Timedelta(days=offset)
        frame["scheduled_time"] = (sched + delta).dt.strftime("%Y-%m-%dT%H:%M:%S")
        frame["actual_time"] = (pd.to_datetime(frame["actual_time"]) + delta).dt.strftime("%Y-%m-%dT%H:%M:%S")
    return offset


def recent_rows(frame: pd.DataFrame, end_date: datetime) -> pd.DataFrame:
    random.seed(2026)
    np.random.seed(2026)
    trains_by_route = frame.groupby("route")["train_id"].unique().to_dict()
    start = end_date - timedelta(days=RECENT_DAYS - 1)
    rows = []
    for i in range(RECENT_ROWS):
        route_name, stations = random.choice(gen.ROUTES)
        station = random.choice(stations)
        train_id = random.choice(list(trains_by_route.get(route_name) or [gen.make_train_id()]))
        base_date = start + timedelta(days=random.randint(0, RECENT_DAYS - 1))
        scheduled = gen.sample_scheduled_time(base_date)
        weather = gen.weighted_choice(gen.WEATHER_OPTIONS, gen.WEATHER_WEIGHTS)
        day_type = gen.weighted_choice(gen.DAY_TYPES, gen.DAY_TYPE_WEIGHTS)
        weights = ([0.35, 0.15, 0.15, 0.20, 0.10, 0.05] if weather in ("heavy_rain", "fog")
                   else [0.55, 0.12, 0.12, 0.05, 0.09, 0.07])
        incident = gen.weighted_choice(gen.INCIDENT_TYPES, weights)
        delay = gen.sample_delay_minutes(weather, day_type, incident)
        rows.append({
            "record_id": str(uuid.uuid5(RECENT_NAMESPACE, f"recent-{i}")),
            "route": route_name, "station": station, "train_id": train_id,
            "scheduled_time": scheduled.isoformat(),
            "actual_time": (scheduled + timedelta(minutes=delay)).isoformat(),
            "weather": weather, "day_type": day_type, "incident_type": incident,
            "incident_note": gen.generate_incident_note(incident, station, train_id, delay) if incident != "none" else "",
            "delay_minutes": delay,
        })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--end", help="last corpus day, YYYY-MM-DD (default: yesterday, Asia/Colombo)")
    parser.add_argument("--supabase", action="store_true", help="upsert the refreshed corpus to operations_history")
    parser.add_argument("--embed", action="store_true", help="add the new incident notes to pgvector")
    args = parser.parse_args()

    end_date = datetime.fromisoformat(args.end) if args.end else _yesterday_colombo()
    frame = pd.read_csv(CSV_PATH).fillna({"incident_note": ""})
    recent_ids = {str(uuid.uuid5(RECENT_NAMESPACE, f"recent-{i}")) for i in range(RECENT_ROWS)}
    base = frame[~frame["record_id"].isin(recent_ids)].copy()

    offset = shift_to(base, end_date)
    added = recent_rows(base, end_date)
    out = pd.concat([base, added], ignore_index=True).sort_values("scheduled_time").reset_index(drop=True)
    out.to_csv(CSV_PATH, index=False)
    sched = pd.to_datetime(out["scheduled_time"])
    print(f"Shifted {len(base)} records by {offset} days; {len(added)} recent records; "
          f"{len(out)} total covering {sched.min().date()} .. {sched.max().date()}")

    if args.supabase:
        sys.path.insert(0, str(DATA_DIR))
        import import_to_supabase as imp
        imp.main()

    if args.embed:
        sys.path.insert(0, str(AGENT_DIR))
        from rag import embed_documents as emb
        emb.load_root_env()
        client, model = emb._get_client(), emb._get_model()
        if client is None:
            raise SystemExit("Supabase is not configured; cannot index embeddings")
        notes = added[added["incident_note"].str.strip() != ""].to_dict(orient="records")
        for start in range(0, len(notes), 100):
            batch = notes[start:start + 100]
            vectors = model.encode([r["incident_note"] for r in batch], normalize_embeddings=True).tolist()
            client.table("incident_embeddings").upsert([{
                "record_id": r["record_id"], "route": r["route"], "station": r["station"],
                "incident_type": r["incident_type"], "delay_minutes": float(r["delay_minutes"]),
                "incident_note": r["incident_note"], "embedding": v,
            } for r, v in zip(batch, vectors)]).execute()
        print(f"Indexed {len(notes)} new incident notes in pgvector")


if __name__ == "__main__":
    main()
