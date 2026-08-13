"""
rag/embed_documents.py
Phase 2: builds the ChromaDB index from everything in data/faq_docs/.

Run manually whenever the source FAQ/fare/schedule docs change:
    python -m rag.embed_documents

Chunking strategy: split on markdown "## " section headers first (keeps
semantically related content together — a whole "## Podi Menike" block
stays as one chunk), then fall back to paragraph splitting for any
oversized section. This is simple on purpose — it's transparent enough to
explain in a viva and good enough for a FAQ-sized corpus.
"""

import os
import glob

import chromadb
from sentence_transformers import SentenceTransformer

from config import settings

COLLECTION_NAME = "passenger_faq"
MAX_CHUNK_CHARS = 800  # ~ a few hundred tokens; keeps chunks focused


def _split_into_chunks(text: str, source: str) -> list[dict]:
    """Splits markdown text into chunks by '## ' section, further splitting
    any section that's still too long by paragraph."""
    chunks = []

    sections = ["## " + s for s in text.split("## ")[1:]] or [text]
    if not text.strip().startswith("#"):
        sections = [text]

    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= MAX_CHUNK_CHARS:
            chunks.append({"text": section, "source": source})
        else:
            for para in section.split("\n\n"):
                para = para.strip()
                if para:
                    chunks.append({"text": para, "source": source})

    return chunks


def build_index() -> int:
    """Reads all docs in data/faq_docs/, chunks them, embeds them, and
    upserts into a persistent Chroma collection. Returns the chunk count."""
    doc_paths = sorted(glob.glob("data/faq_docs/*.md")) + sorted(
        glob.glob("data/faq_docs/*.txt")
    )
    if not doc_paths:
        print("No documents found in data/faq_docs/ — nothing to index.")
        return 0

    all_chunks: list[dict] = []
    for path in doc_paths:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        source_name = os.path.basename(path)
        all_chunks.extend(_split_into_chunks(text, source_name))

    print(f"Loaded {len(doc_paths)} document(s) -> {len(all_chunks)} chunk(s)")

    print(f"Loading embedding model: {settings.EMBEDDING_MODEL} ...")
    model = SentenceTransformer(settings.EMBEDDING_MODEL)
    embeddings = model.encode([c["text"] for c in all_chunks]).tolist()

    client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME)

    collection.add(
        ids=[f"chunk-{i}" for i in range(len(all_chunks))],
        embeddings=embeddings,
        documents=[c["text"] for c in all_chunks],
        metadatas=[{"source": c["source"]} for c in all_chunks],
    )

    print(f"Indexed {len(all_chunks)} chunks into '{COLLECTION_NAME}' "
          f"at {settings.CHROMA_PERSIST_DIR}")
    return len(all_chunks)


if __name__ == "__main__":
    build_index()
