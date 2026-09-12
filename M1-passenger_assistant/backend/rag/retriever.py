"""
Phase 2 - RAG retrieval.

Loads the persistent "passenger_faq" ChromaDB collection built by
embed_documents.py, embeds an incoming passenger question with the same
all-MiniLM-L6-v2 model, and returns the top-k most relevant FAQ chunks.

The embedding model and DB connection are loaded once per process
(module-level singletons) since loading the sentence-transformer model
is relatively slow (~1s) and we don't want to pay that cost per request.
"""
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from rag.embed_documents import CHROMA_DIR, COLLECTION_NAME, EMBEDDING_MODEL_NAME

_model: SentenceTransformer | None = None
_collection = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def _get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def retrieve_faq_chunks(question: str, top_k: int = 3) -> list[dict]:
    """
    Returns up to top_k chunks as:
        [{"text": "...", "source": "fares.md", "heading": "...", "distance": 0.12}, ...]
    Returns an empty list if the collection hasn't been built yet or has no
    documents (e.g. embed_documents.py hasn't been run).
    """
    collection = _get_collection()
    if collection.count() == 0:
        return []

    query_embedding = _get_model().encode([question]).tolist()
    results = collection.query(query_embeddings=query_embedding, n_results=min(top_k, collection.count()))

    chunks = []
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for text, meta, distance in zip(documents, metadatas, distances):
        chunks.append(
            {
                "text": text,
                "source": meta.get("source", ""),
                "heading": meta.get("heading", ""),
                "distance": distance,
            }
        )
    return chunks


if __name__ == "__main__":
    for q in ["How much is a ticket from Colombo to Kandy?", "What time does the next train to Galle leave?"]:
        print(f"\nQ: {q}")
        for chunk in retrieve_faq_chunks(q):
            print(f"  [{chunk['source']}] (distance={chunk['distance']:.3f}) {chunk['heading']}")
