"""
setup_db.py
-----------
Utility script to connect to the configured database (Supabase PostgreSQL or local),
create all RailSense AI Member C tables, and seed initial development/test data.

Usage:
    python setup_db.py
    python setup_db.py --no-seed
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Path resolution
_CURRENT_DIR = Path(__file__).resolve().parent
_BOOKING_AGENT_DIR = _CURRENT_DIR / "booking-agent"
_AGENT_HUB_DIR = _CURRENT_DIR / "agent-hub"

for p in (str(_CURRENT_DIR), str(_BOOKING_AGENT_DIR), str(_AGENT_HUB_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from database.database import Base, SessionLocal, engine, init_db
from database.models import AuditLog, Booking, CancellationRequest, Train, TrainSchedule
from database.seed import seed_test_train_data


def main():
    do_seed = "--no-seed" not in sys.argv
    raw_url = os.getenv("DATABASE_URL", "")
    if raw_url and ("postgresql://" in raw_url or "postgres://" in raw_url):
        backend_name = "PostgreSQL/Supabase"
        masked_host = raw_url.split("@")[-1]
    elif raw_url and "sqlite" in raw_url:
        backend_name = "SQLite"
        masked_host = raw_url
    else:
        backend_name = "Not configured in .env"
        masked_host = "None"

    print("==================================================")
    print("RailSense AI - Database Setup")
    print(f"Active Backend: {backend_name}")
    print(f"Connection Host: {masked_host}")
    print("==================================================")

    if not raw_url:
        print("[!] ERROR: DATABASE_URL is not set in .env.")
        print("    To set up Supabase PostgreSQL, add the connection string to .env:")
        print("    DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres")
        sys.exit(1)

    print("Step 1: Connecting and creating database tables (trains, train_schedules, bookings, cancellation_requests, audit_logs)...")
    init_db(seed=False)
    print("[OK] Tables created successfully.")

    if do_seed:
        print("Step 2: Seeding standard train and schedule data (PM-4082, INACT-9999)...")
        with SessionLocal() as db:
            result = seed_test_train_data(db)
            print(f"[OK] Seeded active train: {result['active_train'].train_id} ({result['active_train'].train_name})")
            print(f"[OK] Seeded inactive train: {result['inactive_train'].train_id}")
            print(f"[OK] Seeded schedule: {result['schedule'].from_station} -> {result['schedule'].to_station} on {result['schedule'].travel_date}")

    # Verify counts
    with SessionLocal() as db:
        train_count = db.query(Train).count()
        schedule_count = db.query(TrainSchedule).count()
        booking_count = db.query(Booking).count()
        audit_count = db.query(AuditLog).count()
        print("--------------------------------------------------")
        print(f"Database verification:")
        print(f"  Trains in database:          {train_count}")
        print(f"  Schedules in database:       {schedule_count}")
        print(f"  Bookings in database:        {booking_count}")
        print(f"  Audit records in database:   {audit_count}")
        print(f"==================================================")
        print("Database setup complete.")


if __name__ == "__main__":
    main()
