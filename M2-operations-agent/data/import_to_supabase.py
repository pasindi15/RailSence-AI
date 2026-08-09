"""Idempotently import operations_history.csv into Supabase.

Run from the repository root:
    python M2-operations-agent/data/import_to_supabase.py
"""

import csv
import os
from datetime import datetime
from pathlib import Path

from supabase import create_client

AGENT_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = AGENT_DIR.parent
DATA_PATH = AGENT_DIR / "data" / "operations_history.csv"
BATCH_SIZE = 500


def load_root_env() -> None:
    """Load simple KEY=value entries without adding a dotenv dependency."""
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_timestamp(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()


def load_rows() -> list[dict]:
    with DATA_PATH.open(newline="", encoding="utf-8") as handle:
        rows = []
        for row in csv.DictReader(handle):
            rows.append(
                {
                    "record_id": row["record_id"],
                    "route": row["route"],
                    "station": row["station"],
                    "train_id": row["train_id"],
                    "scheduled_time": parse_timestamp(row["scheduled_time"]),
                    "actual_time": parse_timestamp(row["actual_time"]),
                    "weather": row["weather"],
                    "day_type": row["day_type"],
                    "incident_type": row["incident_type"],
                    "incident_note": row.get("incident_note", ""),
                    "delay_minutes": float(row["delay_minutes"]),
                }
            )
    return rows


def main() -> None:
    load_root_env()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY are required")

    rows = load_rows()
    client = create_client(url, key)
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        client.table("operations_history").upsert(batch, on_conflict="record_id").execute()
        print(f"Uploaded {min(start + BATCH_SIZE, len(rows))}/{len(rows)} records")

    result = client.table("operations_history").select("record_id", count="exact").limit(1).execute()
    print(f"Supabase operations_history row count: {result.count}")
    if result.count != len(rows):
        raise SystemExit(f"Expected {len(rows)} rows but Supabase returned {result.count}")
    print("Import completed successfully")


if __name__ == "__main__":
    main()
