"""Embed historical incident notes and upload them to Supabase pgvector.

Run from the repository root:
    python M2-operations-agent/rag/embed_documents.py

The command is intentionally explicit so importing the API never downloads a
model or writes to the shared database. It loads the root .env file and uses
the Supabase secret key for controlled ingestion.
"""

import os
from pathlib import Path

import pandas as pd
from sentence_transformers import SentenceTransformer
from supabase import create_client

THIS_DIR = Path(__file__).resolve().parent
ROOT_DIR = THIS_DIR.parents[1]
DATA_PATH = THIS_DIR.parent / "data" / "operations_history.csv"
MODEL_NAME = "all-MiniLM-L6-v2"
BATCH_SIZE = 64


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


def main() -> None:
    load_root_env()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv(
        "SUPABASE_SECRET_KEY",
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", os.getenv("SUPABASE_KEY")),
    )
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY are required")

    frame = pd.read_csv(DATA_PATH).fillna("")
    frame = frame[frame["incident_note"].str.strip() != ""]
    model = SentenceTransformer(MODEL_NAME)
    client = create_client(url, key)

    records = frame.to_dict(orient="records")
    for start in range(0, len(records), BATCH_SIZE):
        batch = records[start : start + BATCH_SIZE]
        embeddings = model.encode(
            [record["incident_note"] for record in batch],
            normalize_embeddings=True,
        ).tolist()
        payload = [
            {
                "record_id": record["record_id"],
                "route": record["route"],
                "station": record["station"],
                "incident_type": record["incident_type"],
                "delay_minutes": float(record["delay_minutes"]),
                "incident_note": record["incident_note"],
                "embedding": embedding,
            }
            for record, embedding in zip(batch, embeddings)
        ]
        client.table("incident_embeddings").upsert(payload).execute()
        print(f"Uploaded {min(start + BATCH_SIZE, len(records))}/{len(records)} incidents")

    print(f"Completed pgvector indexing with {len(records)} incident notes")


if __name__ == "__main__":
    main()
