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


# --- Index integrity / source-aware retrieval (source-of-truth alignment) ---

def test_chroma_index_matches_the_current_faq_docs_exactly():
    """Guards against a stale/duplicated index: the collection must hold exactly
    one chunk per FAQ section - no leftovers from old docs, no duplicate IDs."""
    from rag.embed_documents import FAQ_DIR
    from rag.retriever import _get_collection

    expected = {}
    for path in sorted(FAQ_DIR.glob("*.md")):
        for i, chunk in enumerate(chunk_markdown(path.read_text(encoding="utf-8"))):
            expected[f"{path.name}::{i}"] = chunk["text"]

    got = _get_collection().get()
    assert len(got["ids"]) == len(set(got["ids"])), "duplicate chunk IDs in the index"
    assert dict(zip(got["ids"], got["documents"])) == expected, (
        "index is stale - run `python -m rag.embed_documents` with the backend venv"
    )


def test_policy_questions_retrieve_the_right_policy_section():
    cases = {
        "How much luggage can I carry?": "Luggage",
        "What is the refund policy?": "Refunds",
        "What is the ticket validity period?": "Ticket Validity",
        "How can I make a complaint?": "Complaints and Issue Reporting",
        "Can I cancel my ticket?": "Cancelling a Booking",
    }
    for question, heading in cases.items():
        top = retrieve_faq_chunks(question, top_k=1, source_filter="policies.md")[0]
        assert top["heading"] == heading, f"{question!r} -> {top['heading']!r}"


def test_fare_retrieval_with_source_filter_only_returns_fares_and_finds_each_route():
    for route, heading in {
        "Colombo Fort to Kandy": "Colombo Fort - Kandy",
        "Colombo Fort to Galle": "Colombo Fort - Galle",
        "Colombo Fort to Badulla": "Colombo Fort - Badulla",
    }.items():
        results = retrieve_faq_chunks(route, top_k=3, source_filter="fares.md")
        assert {c["source"] for c in results} == {"fares.md"}
        assert results[0]["heading"] == heading


def test_schedule_retrieval_with_source_filter_finds_the_line():
    top = retrieve_faq_chunks("Colombo Fort to Jaffna", top_k=1, source_filter="schedules.md")[0]
    assert top["source"] == "schedules.md" and "Jaffna" in top["heading"]
