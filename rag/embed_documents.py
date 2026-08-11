"""
rag/embed_documents.py
Phase 2 script (not run in Phase 1).

Will do, once data/faq_docs/ has real content:
  1. Read every .txt/.md file in data/faq_docs/
  2. Chunk each document (~300-500 tokens, with overlap)
  3. Embed chunks with sentence-transformers (settings.EMBEDDING_MODEL)
  4. Upsert into a persistent ChromaDB collection at settings.CHROMA_PERSIST_DIR

Run manually whenever the source FAQ/fare/schedule docs change:
    python -m rag.embed_documents
"""

if __name__ == "__main__":
    print(
        "rag/embed_documents.py is a Phase 2 script. "
        "Add real FAQ/schedule/fare docs to data/faq_docs/ first, "
        "then implement chunking + embedding here."
    )
