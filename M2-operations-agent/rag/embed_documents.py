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


def _get_client():
    """Return a Supabase client for embedding writes, or None when unconfigured."""
    load_root_env()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv(
        "SUPABASE_SECRET_KEY",
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", os.getenv("SUPABASE_KEY")),
    )
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


_singleton_model = None


def _get_model():
    """Lazily load the sentence-transformer, shared across single-record calls."""
    global _singleton_model
    if _singleton_model is None:
        _singleton_model = SentenceTransformer(MODEL_NAME)
    return _singleton_model


def embed_incident(record: dict) -> dict:
    """Index one newly-created incident so RAG can retrieve it from now on.

    Called by POST /incident-report. Best-effort by design: a missing model
    download or unreachable Supabase must never fail incident creation, so the
    outcome is reported back rather than raised. The local TF-IDF index is
    refreshed separately by rag.incident_retriever.add_live_incident().
    """
    note = str(record.get("incident_note") or "").strip()
    if not note:
        return {"indexed": False, "reason": "no_incident_note"}

    client = _get_client()
    if client is None:
        return {"indexed": False, "reason": "supabase_unconfigured"}

    try:
        embedding = _get_model().encode([note], normalize_embeddings=True)[0].tolist()
        client.table("incident_embeddings").upsert({
            "record_id": record["record_id"],
            "route": record.get("route") or "Live incident report",
            "station": record.get("station") or "unknown",
            "incident_type": record.get("incident_type") or "other",
            "delay_minutes": float(record.get("delay_minutes") or 0.0),
            "incident_note": note,
            "embedding": embedding,
        }).execute()
        return {"indexed": True, "reason": "pgvector"}
    except Exception as exc:
        return {"indexed": False, "reason": f"{exc.__class__.__name__}: {exc}"}


def delete_incident_embedding(record_id: str) -> dict:
    """Drop an incident's vector row so RAG never retrieves a ghost record."""
    client = _get_client()
    if client is None:
        return {"deleted": False, "reason": "supabase_unconfigured"}
    try:
        client.table("incident_embeddings").delete().eq("record_id", record_id).execute()
        return {"deleted": True, "reason": "pgvector"}
    except Exception as exc:
        return {"deleted": False, "reason": f"{exc.__class__.__name__}: {exc}"}


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
