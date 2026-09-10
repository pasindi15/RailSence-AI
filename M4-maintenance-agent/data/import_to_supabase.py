"""Upload assets_history.csv to Supabase assets_history table.

Usage (from repo root):
    python M4-maintenance-agent/data/import_to_supabase.py

Requires SUPABASE_URL and SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY) in .env
Run supabase_schema.sql in the Supabase SQL editor first.
"""

import csv
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("railsense.maintenance.import")

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

import supabase_store

DATA_PATH = AGENT_DIR / "data" / "assets_history.csv"
BATCH_SIZE = 100


INT_FIELDS = {"days_since_service", "fault_count_30d"}
FLOAT_FIELDS = {
    "temperature_celsius", "vibration_level", "oil_pressure_bar",
    "fuel_efficiency_pct", "axle_temp_celsius", "wheel_profile_mm",
    "pad_thickness_mm", "brake_cylinder_pressure_bar", "stopping_distance_m",
    "response_time_ms", "voltage_output_v", "contact_resistance_ohm",
    "rail_wear_mm", "gauge_deviation_mm", "ballast_void_pct",
    "motor_current_a", "cycle_time_seconds", "sensor_reliability_pct",
    "health_score",
}


def cast_row(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if v == "" or v is None:
            out[k] = None
        elif k in INT_FIELDS:
            try:
                out[k] = int(float(v))
            except (ValueError, TypeError):
                out[k] = None
        elif k in FLOAT_FIELDS:
            try:
                out[k] = float(v)
            except (ValueError, TypeError):
                out[k] = None
        else:
            out[k] = v
    return out


def run():
    client = supabase_store.get_client()
    if client is None:
        logger.error(
            "Supabase client unavailable. "
            "Set SUPABASE_URL and SUPABASE_SECRET_KEY (service_role JWT) in .env"
        )
        sys.exit(1)

    if not DATA_PATH.exists():
        logger.info("CSV not found, generating dataset first...")
        import generate_dataset
        records = generate_dataset.generate_records(600)
        fieldnames = list(records[0].keys())
        with open(DATA_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)
        logger.info("Generated %d records.", len(records))

    rows = []
    with open(DATA_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(cast_row(row))

    logger.info("Uploading %d rows in batches of %d...", len(rows), BATCH_SIZE)
    uploaded = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i: i + BATCH_SIZE]
        try:
            client.table("assets_history").upsert(batch, on_conflict="record_id").execute()
            uploaded += len(batch)
            logger.info("  Uploaded %d/%d rows", uploaded, len(rows))
        except Exception as exc:
            logger.error("  Batch %d failed: %s", i // BATCH_SIZE, exc)

    logger.info("Done. Uploaded %d/%d rows to assets_history.", uploaded, len(rows))


if __name__ == "__main__":
    run()
