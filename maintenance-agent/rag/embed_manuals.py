"""
One-time script: chunks and embeds equipment manual text into ChromaDB.
Place manual .txt files under maintenance-agent/data/manuals/
Run: python -m rag.embed_manuals
"""

import os
import glob
import chromadb
from sentence_transformers import SentenceTransformer

MANUALS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "manuals")
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chroma_db")
COLLECTION_NAME = "equipment_manuals"
CHUNK_SIZE = 400
CHUNK_OVERLAP = 80


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunks.append(" ".join(words[i : i + size]))
        i += size - overlap
    return chunks


def build_index():
    model = SentenceTransformer("all-MiniLM-L6-v2")
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(COLLECTION_NAME)

    manual_files = glob.glob(os.path.join(MANUALS_DIR, "*.txt"))
    if not manual_files:
        print(f"No .txt files found in {MANUALS_DIR}")
        return

    for path in manual_files:
        source = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()

        chunks = chunk_text(text)
        embeddings = model.encode(chunks, show_progress_bar=True).tolist()
        ids = [f"{source}_{i}" for i in range(len(chunks))]
        metadatas = [{"source": source, "chunk_index": i} for i in range(len(chunks))]

        collection.upsert(documents=chunks, embeddings=embeddings, ids=ids, metadatas=metadatas)
        print(f"Indexed {len(chunks)} chunks from {source}")

    print("Manual index built.")


if __name__ == "__main__":
    build_index()
