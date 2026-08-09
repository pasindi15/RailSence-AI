"""Phase 4 incident retrieval over the historical operations corpus.

The retriever prefers sentence-transformers embeddings and can optionally
persist/query them through Supabase pgvector. A TF-IDF fallback keeps local
demos deterministic and dependency-light when the embedding model or cloud
credentials are unavailable.
"""

import json
import os
from pathlib import Path
from typing import Optional

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

THIS_DIR = Path(__file__).resolve().parent
DATA_PATH = THIS_DIR.parent / "data" / "operations_history.csv"
CACHE_PATH = THIS_DIR / "incident_embeddings.json"
DEFAULT_TOP_K = 3

_vectorizer: Optional[TfidfVectorizer] = None
_matrix = None
_records: list[dict] = []
_embedding_model = None


def _load_records() -> list[dict]:
    global _records
    if _records:
        return _records
    frame = pd.read_csv(DATA_PATH).fillna("")
    frame = frame[frame["incident_note"].str.strip() != ""]
    _records = frame.to_dict(orient="records")
    return _records


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


def _build_tfidf_index() -> None:
    global _vectorizer, _matrix
    records = _load_records()
    _vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
    _matrix = _vectorizer.fit_transform([record["incident_note"] for record in records])


def _search_supabase(query: str, top_k: int) -> Optional[list[dict]]:
    """Query the optional pgvector RPC; return None when it is not configured."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None

    try:
        embedding = _get_embedding_model().encode(query).tolist()
        from supabase import create_client

        client = create_client(url, key)
        response = client.rpc(
            "match_incidents",
            {"query_embedding": embedding, "match_count": top_k},
        ).execute()
        return response.data or []
    except Exception:
        return None


def retrieve_similar_incidents(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    *,
    route: Optional[str] = None,
    station: Optional[str] = None,
    incident_type: Optional[str] = None,
    exclude_record_id: Optional[str] = None,
) -> dict:
    """Return top historical incidents and the retrieval method used."""
    top_k = max(1, min(top_k, 5))
    cloud_results = _search_supabase(query, top_k)
    if cloud_results is not None:
        return {"incidents": cloud_results, "method": "supabase_pgvector"}

    if _vectorizer is None or _matrix is None:
        _build_tfidf_index()

    query_vector = _vectorizer.transform([query])
    scores = cosine_similarity(query_vector, _matrix)[0]
    candidates = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)

    results = []
    for index, score in candidates:
        record = _records[index]
        if exclude_record_id and record["record_id"] == exclude_record_id:
            continue
        if route and record["route"] == route:
            score += 0.08
        if station and record["station"] == station:
            score += 0.05
        if incident_type and record["incident_type"] == incident_type:
            score += 0.05
        results.append(
            {
                "record_id": record["record_id"],
                "route": record["route"],
                "station": record["station"],
                "incident_type": record["incident_type"],
                "delay_minutes": float(record["delay_minutes"]),
                "incident_note": record["incident_note"],
                "similarity": round(float(score), 4),
            }
        )

    results.sort(key=lambda item: item["similarity"], reverse=True)
    return {"incidents": results[:top_k], "method": "local_tfidf"}


def format_incident_citations(incidents: list[dict]) -> list[str]:
    """Convert retrieved records to concise, user-facing citations."""
    return [
        (
            f"{item.get('incident_type', 'incident').replace('_', ' ')} at "
            f"{item.get('station', 'an unknown station')} on {item.get('route', 'the route')}: "
            f"{item.get('incident_note', '').strip()} "
            f"(historical delay {float(item.get('delay_minutes', 0)):.1f} min)"
        ).strip()
        for item in incidents
    ]
