"""Embed equipment manual sections and upload to Supabase pgvector.

Usage (from repo root):
    python M4-maintenance-agent/rag/embed_manuals.py

Requires: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env
"""

import json
import logging
import os
import sys
import uuid
from pathlib import Path

# Prevent transformers from trying to load TensorFlow/JAX (not needed for inference)
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_JAX", "0")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("railsense.maintenance.embed")

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from rag.manual_retriever import _load_manual_sections
import supabase_store


def embed_and_upload(batch_size: int = 50) -> None:
    sections = _load_manual_sections()
    if not sections:
        logger.error("No manual sections found. Check manuals/ directory.")
        sys.exit(1)
    logger.info("Loaded %d manual sections.", len(sections))

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.error("sentence-transformers not installed. Run: pip install sentence-transformers")
        sys.exit(1)

    model = SentenceTransformer("all-MiniLM-L6-v2")
    client = supabase_store.get_client()
    if client is None:
        logger.error("Supabase client unavailable. Check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
        sys.exit(1)

    texts = [f"{s['section_title']} {s['content']}" for s in sections]
    logger.info("Generating embeddings for %d sections...", len(texts))
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=True)

    uploaded = 0
    for i in range(0, len(sections), batch_size):
        batch_sections = sections[i: i + batch_size]
        batch_embeddings = embeddings[i: i + batch_size]
        rows = []
        for section, embedding in zip(batch_sections, batch_embeddings):
            rows.append({
                "id": str(uuid.uuid4()),
                "section_id": section["section_id"],
                "manual": section["manual"],
                "section_title": section["section_title"],
                "content": section["content"],
                "source_file": section["source_file"],
                "embedding": embedding.tolist(),
            })
        try:
            client.table("manual_embeddings").upsert(rows, on_conflict="section_id").execute()
            uploaded += len(rows)
            logger.info("Uploaded batch %d/%d (%d sections so far)", i // batch_size + 1,
                        -(-len(sections) // batch_size), uploaded)
        except Exception as exc:
            logger.error("Batch upload failed: %s", exc)

    logger.info("Done. Uploaded %d/%d sections to Supabase.", uploaded, len(sections))


if __name__ == "__main__":
    embed_and_upload()
