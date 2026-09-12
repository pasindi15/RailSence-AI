"""
Phase 2 - RAG ingestion script.

Reads every *.md file in backend/data/faq_docs/, splits each file into
chunks along its markdown headers (so each chunk is one logical section,
e.g. "## Colombo Fort - Kandy"), embeds the chunks with the
all-MiniLM-L6-v2 sentence-transformer model, and stores them in a
persistent ChromaDB collection called "passenger_faq".

Run this script whenever the FAQ docs change:
    python rag/embed_documents.py
"""
import re
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

FAQ_DIR = Path(__file__).parent.parent / "data" / "faq_docs"
CHROMA_DIR = Path(__file__).parent.parent / ".chroma"
COLLECTION_NAME = "passenger_faq"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# Matches a markdown header line, e.g. "# Title" or "## Section"
HEADER_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def chunk_markdown(text: str) -> list[dict]:
    """
    Split a markdown document into chunks by header.

    Each chunk keeps the document's top-level title (h1) as context, so an
    embedded chunk still makes sense on its own even though it came from
    deep inside a longer file. For example the docs in data/faq_docs/ look
    like:

        # Fares (placeholder data)
        ## Colombo Fort - Kandy
        - 1st Class: LKR 1000
        ...
        ## Colombo Fort - Galle
        ...

    This produces one chunk per "##" section, each prefixed with the "#"
    title so the retriever still knows the chunk is about fares.
    """
    matches = list(HEADER_PATTERN.finditer(text))
    if not matches:
        # No headers at all - treat the whole file as a single chunk.
        stripped = text.strip()
        return [{"heading": "", "text": stripped}] if stripped else []

    doc_title = ""
    chunks = []
    current_heading = None
    current_start = None

    for match in matches:
        level = len(match.group(1))
        heading_text = match.group(2).strip()

        if level == 1 and doc_title == "":
            doc_title = heading_text

        # Close off the previous chunk once we hit the next header.
        if current_heading is not None:
            body = text[current_start:match.start()].strip()
            chunks.append({"heading": current_heading, "body": body})

        current_heading = heading_text
        current_start = match.end()

    # Final chunk runs to the end of the file.
    if current_heading is not None:
        body = text[current_start:].strip()
        chunks.append({"heading": current_heading, "body": body})

    result = []
    for chunk in chunks:
        if chunk["heading"] == doc_title and not chunk["body"]:
            continue  # empty h1-only chunk, nothing to embed
        # Prefix with the document title so the chunk is self-contained.
        full_text = f"{doc_title}\n\n## {chunk['heading']}\n{chunk['body']}".strip()
        if full_text:
            result.append({"heading": chunk["heading"], "text": full_text})

    return result


def build_passenger_faq_collection() -> chromadb.api.models.Collection.Collection:
    """
    Chunk + embed every markdown file in FAQ_DIR and (re)build the
    "passenger_faq" ChromaDB collection on disk at CHROMA_DIR.
    """
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Start clean each time this script runs so stale chunks don't linger.
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass  # collection didn't exist yet - nothing to delete
    collection = client.create_collection(COLLECTION_NAME)

    model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    ids, documents, metadatas = [], [], []
    for path in sorted(FAQ_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        for i, chunk in enumerate(chunk_markdown(content)):
            ids.append(f"{path.name}::{i}")
            documents.append(chunk["text"])
            metadatas.append({"source": path.name, "heading": chunk["heading"]})

    if not documents:
        print(f"No markdown files found in {FAQ_DIR}")
        return collection

    embeddings = model.encode(documents).tolist()
    collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)

    print(f"Embedded {len(documents)} chunks from {FAQ_DIR} into collection '{COLLECTION_NAME}'")
    return collection


if __name__ == "__main__":
    build_passenger_faq_collection()
