"""
Tests for the Phase 2 RAG pipeline (rag/embed_documents.py, rag/retriever.py).

These tests assume `python -m rag.embed_documents` has already been run once
so the persistent ChromaDB collection exists on disk (same as a real dev
workflow: embed the docs once, then query them many times).
"""
from rag.embed_documents import chunk_markdown
from rag.retriever import retrieve_faq_chunks


def test_chunk_markdown_splits_by_h2_and_keeps_h1_title():
    text = (
        "# Fares (placeholder data)\n\n"
        "## Colombo Fort - Kandy\n"
        "- 1st Class: LKR 1000\n\n"
        "## Colombo Fort - Galle\n"
        "- 1st Class: LKR 700\n"
    )
    chunks = chunk_markdown(text)

    assert len(chunks) == 2
    assert chunks[0]["heading"] == "Colombo Fort - Kandy"
    assert "Fares (placeholder data)" in chunks[0]["text"]
    assert "LKR 1000" in chunks[0]["text"]
    assert chunks[1]["heading"] == "Colombo Fort - Galle"
    assert "LKR 700" in chunks[1]["text"]


def test_retriever_returns_top_matches_with_source_filename():
    results = retrieve_faq_chunks("How much is a ticket from Colombo to Kandy?", top_k=3)

    assert len(results) > 0
    assert len(results) <= 3
    # The best match for a fare question should come from fares.md
    assert results[0]["source"] == "fares.md"
    for chunk in results:
        assert chunk["source"].endswith(".md")
        assert chunk["text"]
