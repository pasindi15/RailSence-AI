"""Summarize technician maintenance reports.

Default: extractive frequency-based summarization.
Optional: LLM summarization when ANTHROPIC_API_KEY is set.
"""

import os
import re
from collections import Counter

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "was", "are", "were", "be", "been", "by", "from",
    "it", "its", "this", "that", "as", "all", "no", "not", "so", "up",
    "has", "had", "have", "due", "now", "out", "set", "per", "got", "found",
    "during", "within", "after", "before", "been", "will", "also",
}


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _word_freq(sentences: list[str]) -> Counter:
    words: list[str] = []
    for s in sentences:
        for w in re.findall(r"[a-z]+", s.lower()):
            if w not in STOPWORDS and len(w) > 2:
                words.append(w)
    return Counter(words)


def summarize_rule_based(text: str, max_sentences: int = 2) -> str:
    sentences = _sentences(text)
    if len(sentences) <= max_sentences:
        return text.strip()
    freq = _word_freq(sentences)
    scores = []
    for s in sentences:
        score = sum(freq[w] for w in re.findall(r"[a-z]+", s.lower()) if w not in STOPWORDS)
        scores.append(score)
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:max_sentences]
    top_indices.sort()
    return " ".join(sentences[i] for i in top_indices)


def summarize_llm(text: str) -> str:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        prompt = (
            "You are a railway maintenance supervisor. Summarize this technician report into "
            "1-2 clear sentences for an operator brief. Include the fault found and action taken.\n\n"
            f"Report: {text}"
        )
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception:
        return summarize_rule_based(text)


def summarize_maintenance_report(text: str) -> tuple[str, str]:
    """Returns (summary, method)."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return summarize_llm(text), "llm"
    return summarize_rule_based(text), "extractive"
