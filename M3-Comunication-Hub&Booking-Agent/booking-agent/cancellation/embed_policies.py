"""
cancellation/embed_policies.py
------------------------------
Ingestion script for RailSense AI Cancellation Policy Knowledge Base.

Parses railway policy markdown documents, chunks them by article/section,
computes 384-dimensional dense semantic embeddings using SentenceTransformer
('all-MiniLM-L6-v2'), and seeds them into Supabase PostgreSQL with pgvector.

Usage:
    python -m cancellation.embed_policies
    or
    python M3-Comunication-Hub&Booking-Agent/booking-agent/cancellation/embed_policies.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from sentence_transformers import SentenceTransformer
from sqlalchemy import text

# Ensure booking-agent root is in sys.path
_CURRENT_DIR = Path(__file__).resolve().parent
_BOOKING_AGENT_DIR = _CURRENT_DIR.parent
if str(_BOOKING_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOOKING_AGENT_DIR))

from database.database import DATABASE_URL, engine, is_test_environment

_POLICIES_DIR = _CURRENT_DIR / "policies"
MODEL_NAME = "all-MiniLM-L6-v2"


def parse_policy_chunks(policies_dir: Path | None = None) -> list[dict[str, Any]]:
    """Parse all markdown policies into chunk records."""
    target_dir = policies_dir or _POLICIES_DIR
    if not target_dir.is_dir():
        raise FileNotFoundError(f"Policies directory not found at {target_dir}")

    documents = sorted(list(target_dir.glob("*.md")))
    chunks: list[dict[str, Any]] = []

    for doc_path in documents:
        doc_name = doc_path.name
        with open(doc_path, "r", encoding="utf-8") as f:
            content = f.read()

        doc_id_match = re.search(r"Document ID:\s*([A-Z0-9-]+)", content)
        doc_id = doc_id_match.group(1) if doc_id_match else doc_name.replace(".md", "").upper()

        sections = re.split(r"(?=^##\s+)", content, flags=re.MULTILINE)
        for sec in sections:
            sec_text = sec.strip()
            if not sec_text:
                continue

            lines = sec_text.splitlines()
            header = lines[0].replace("#", "").strip() if lines else "General Policy"

            citation = f"[{doc_id} - {header}]"
            chunks.append(
                {
                    "document": doc_name,
                    "document_id": doc_id,
                    "section": header,
                    "citation": citation,
                    "content": sec_text,
                }
            )

    return chunks


def seed_policy_embeddings(policies_dir: Path | None = None) -> int:
    """
    Generate embeddings and seed them into cancellation_policy_embeddings table in Supabase.
    Returns the number of seeded chunks.
    """
    if DATABASE_URL.startswith("sqlite"):
        print("[Embedding Seeder] SQLite detected. Skipping Supabase pgvector seeding.")
        return 0

    chunks = parse_policy_chunks(policies_dir)
    print(f"[Embedding Seeder] Found {len(chunks)} policy chunks to embed.")

    print(f"[Embedding Seeder] Loading SentenceTransformer model '{MODEL_NAME}'...")
    model = SentenceTransformer(MODEL_NAME)

    texts_to_embed = [f"{c['section']}\n{c['content']}" for c in chunks]
    print("[Embedding Seeder] Computing 384-dimensional dense vectors...")
    embeddings = model.encode(texts_to_embed, normalize_embeddings=True).tolist()

    insert_sql = text(
        """
        INSERT INTO cancellation_policy_embeddings 
            (document, document_id, section, citation, content, embedding)
        VALUES 
            (:document, :document_id, :section, :citation, :content, CAST(:embedding AS vector))
        """
    )

    with engine.connect() as conn:
        print("[Embedding Seeder] Clearing existing policy embeddings in Supabase...")
        conn.execute(text("TRUNCATE TABLE cancellation_policy_embeddings RESTART IDENTITY;"))

        for chunk, emb in zip(chunks, embeddings):
            emb_str = f"[{','.join(f'{x:.6f}' for x in emb)}]"
            conn.execute(
                insert_sql,
                {
                    "document": chunk["document"],
                    "document_id": chunk["document_id"],
                    "section": chunk["section"],
                    "citation": chunk["citation"],
                    "content": chunk["content"],
                    "embedding": emb_str,
                },
            )

        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cancellation_policy_embeddings_embedding ON cancellation_policy_embeddings USING hnsw (embedding vector_cosine_ops);"))
        conn.commit()

    print(f"[Embedding Seeder] Successfully seeded {len(chunks)} policy vectors into Supabase pgvector!")
    return len(chunks)


if __name__ == "__main__":
    count = seed_policy_embeddings()
    print(f"Done. {count} records embedded.")
