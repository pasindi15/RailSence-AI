"""
M2 — Operations & Delay-Prediction Agent
Phase 3: Incident report summarization.

Two modes, same pattern as classify_incident.py:
    1. Extractive baseline: word-frequency sentence scoring (a small,
       dependency-free relative of TextRank). Always available, no API
       cost, deterministic.
    2. Optional LLM summarization via the Anthropic API if
       ANTHROPIC_API_KEY is set. Falls back to the extractive baseline on
       any failure.

Most single-sentence incident notes are already short (this is by design —
see data/generate_dataset.py), so for those the baseline just returns the
sentence, lightly cleaned. The frequency-scoring path is where multi-
sentence staff logs actually get condensed.
"""

import os
import re
from typing import Optional

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "of", "to",
    "in", "on", "at", "for", "with", "by", "from", "as", "is", "was",
    "were", "be", "been", "being", "this", "that", "these", "those", "it",
    "its", "near", "before", "while", "due", "caused", "causing", "will",
    "required", "reported",
}

MAX_SUMMARY_CHARS = 200


def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip()]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z]+", text.lower())


def _extractive_summarize(text: str, max_sentences: int = 2) -> str:
    text = text.strip()
    if not text:
        return ""

    sentences = _split_sentences(text)
    if len(sentences) <= max_sentences:
        summary = " ".join(sentences)
    else:
        word_freq: dict[str, int] = {}
        for word in _tokenize(text):
            if word not in STOPWORDS:
                word_freq[word] = word_freq.get(word, 0) + 1

        scored = []
        for idx, sentence in enumerate(sentences):
            score = sum(word_freq.get(w, 0) for w in _tokenize(sentence))
            scored.append((idx, score, sentence))

        top = sorted(scored, key=lambda x: x[1], reverse=True)[:max_sentences]
        top_in_order = [s for s in sorted(top, key=lambda x: x[0])]
        summary = " ".join(s[2] for s in top_in_order)

    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[: MAX_SUMMARY_CHARS - 3].rsplit(" ", 1)[0] + "..."

    return summary


def _llm_summarize(text: str) -> Optional[str]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=80,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Summarize this railway staff incident report into a 1-2 sentence "
                        "operator brief, for a dashboard feed. Be concise and factual, no "
                        "commentary or preamble — reply with only the summary.\n\n"
                        f"Incident report: {text}"
                    ),
                }
            ],
        )
        return response.content[0].text.strip()
    except Exception:
        return None


def summarize_incident(text: str, prefer_llm: bool = False) -> dict:
    """
    Returns {"summary": str, "method": "rule_based" | "llm"}
    """
    if prefer_llm:
        llm_result = _llm_summarize(text)
        if llm_result is not None:
            return {"summary": llm_result, "method": "llm"}

    return {"summary": _extractive_summarize(text), "method": "rule_based"}
