"""
RAG retrieval + LLM answer generation over equipment manuals.
"""

import os
import anthropic
import chromadb
from sentence_transformers import SentenceTransformer

CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chroma_db")
COLLECTION_NAME = "equipment_manuals"
TOP_K = 3

_embed_model = None
_collection = None
_llm_client = None


def _get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


def _get_llm():
    global _llm_client
    if _llm_client is None:
        _llm_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _llm_client


SYSTEM_PROMPT = """You are a railway equipment maintenance expert.
Answer the technician's question using ONLY the manual excerpts provided below.
If the excerpts do not contain sufficient information, say so clearly.
Always cite the source document and section when possible."""


async def query_manual(query: str) -> dict:
    model = _get_embed_model()
    query_embedding = model.encode([query]).tolist()[0]

    collection = _get_collection()
    results = collection.query(query_embeddings=[query_embedding], n_results=TOP_K)

    if not results["documents"] or not results["documents"][0]:
        return {
            "answer": "No relevant manual content found for this query.",
            "sources": [],
        }

    docs = results["documents"][0]
    metadatas = results["metadatas"][0]

    context = "\n\n---\n\n".join(
        f"[Source: {m['source']}, chunk {m['chunk_index']}]\n{d}"
        for d, m in zip(docs, metadatas)
    )

    llm = _get_llm()
    response = llm.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Manual excerpts:\n{context}\n\nQuestion: {query}",
            }
        ],
    )

    return {
        "answer": response.content[0].text.strip(),
        "sources": [
            {"source": m["source"], "chunk_index": m["chunk_index"], "excerpt": d[:200]}
            for d, m in zip(docs, metadatas)
        ],
    }
