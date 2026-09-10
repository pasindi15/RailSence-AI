"""Retrieve relevant equipment manual sections for a maintenance query.

Primary:  Supabase pgvector (when SUPABASE_URL + SUPABASE_KEY are set).
Fallback: Local TF-IDF on manual text files (always available offline).
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("railsense.maintenance.rag")

AGENT_DIR = Path(__file__).resolve().parents[1]
MANUALS_DIR = AGENT_DIR / "manuals"

_tfidf_vectorizer = None
_tfidf_matrix = None
_tfidf_docs: list[dict] = []


def _load_manual_sections() -> list[dict]:
    """Load all manual files and split by section heading."""
    sections: list[dict] = []
    if not MANUALS_DIR.exists():
        return sections
    for manual_file in sorted(MANUALS_DIR.glob("*.txt")):
        text = manual_file.read_text(encoding="utf-8")
        manual_name = manual_file.stem.replace("_", " ").title()
        current_section = ""
        current_title = "Introduction"
        current_lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("##"):
                if current_lines:
                    sections.append({
                        "manual": manual_name,
                        "section_id": f"{manual_file.stem}_{current_section}",
                        "section_title": current_title,
                        "content": " ".join(current_lines).strip(),
                        "source_file": manual_file.name,
                    })
                    current_lines = []
                parts = stripped.lstrip("#").strip().split(" ", 1)
                current_section = parts[0] if parts else ""
                current_title = parts[1] if len(parts) > 1 else stripped.lstrip("#").strip()
            elif stripped and not stripped.startswith("#"):
                current_lines.append(stripped)
        if current_lines:
            sections.append({
                "manual": manual_name,
                "section_id": f"{manual_file.stem}_{current_section}",
                "section_title": current_title,
                "content": " ".join(current_lines).strip(),
                "source_file": manual_file.name,
            })
    return sections


def _ensure_tfidf() -> None:
    global _tfidf_vectorizer, _tfidf_matrix, _tfidf_docs
    if _tfidf_matrix is not None:
        return
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        _tfidf_docs = _load_manual_sections()
        if not _tfidf_docs:
            return
        corpus = [f"{d['section_title']} {d['content']}" for d in _tfidf_docs]
        _tfidf_vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
        _tfidf_matrix = _tfidf_vectorizer.fit_transform(corpus)
        logger.info("TF-IDF index built: %d manual sections", len(_tfidf_docs))
    except Exception as exc:
        logger.warning("TF-IDF setup failed: %s", exc)


def _retrieve_tfidf(query: str, top_k: int = 3) -> list[dict]:
    _ensure_tfidf()
    if _tfidf_matrix is None or not _tfidf_docs:
        return []
    try:
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity
        q_vec = _tfidf_vectorizer.transform([query])
        scores = cosine_similarity(q_vec, _tfidf_matrix).flatten()
        top_idx = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_idx:
            if scores[idx] > 0:
                doc = dict(_tfidf_docs[idx])
                doc["score"] = round(float(scores[idx]), 4)
                results.append(doc)
        return results
    except Exception as exc:
        logger.warning("TF-IDF retrieval failed: %s", exc)
        return []


def _retrieve_supabase(query: str, top_k: int = 3) -> list[dict]:
    try:
        sys.path.insert(0, str(AGENT_DIR))
        import supabase_store
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embedding = model.encode(query, normalize_embeddings=True).tolist()
        results = supabase_store.match_manual_sections(embedding, match_count=top_k)
        return results or []
    except Exception as exc:
        logger.warning("Supabase retrieval failed: %s — falling back to TF-IDF", exc)
        return []


def retrieve_manual_sections(
    query: str,
    asset_type: str = "",
    fault_type: str = "",
    top_k: int = 3,
) -> tuple[list[dict], str]:
    """Returns (sections, retrieval_method)."""
    full_query = f"{asset_type} {fault_type} {query}".strip()

    if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"):
        results = _retrieve_supabase(full_query, top_k)
        if results:
            return results, "supabase_pgvector"

    results = _retrieve_tfidf(full_query, top_k)
    return results, "local_tfidf"


def format_citation(section: dict) -> str:
    return f"{section.get('manual', 'Manual')} — {section.get('section_title', '')} ({section.get('source_file', '')})"
