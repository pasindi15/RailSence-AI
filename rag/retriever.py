"""
rag/retriever.py
Phase 1: stub returning an empty list — /chat calls the LLM with no
grounding context yet, which is expected for Phase 1.
Phase 2: connect to the persistent ChromaDB client built by
embed_documents.py, embed the query with sentence-transformers, and
return the top-k chunks (with their source filename, for citations).
"""

from typing import TypedDict


class RetrievedChunk(TypedDict):
    text: str
    source: str
    score: float


def retrieve(query: str, top_k: int = 3) -> list[RetrievedChunk]:
    # Phase 2 TODO: real ChromaDB similarity search
    return []
