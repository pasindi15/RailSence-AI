"""RAG-powered chatbot for maintenance engineers.

Takes a free-text question, retrieves relevant manual sections,
and composes a grounded answer with citations.

Default: template-grounded (no API cost).
Optional: LLM answer via Claude when ANTHROPIC_API_KEY is set.
"""

import os
from typing import Any, Optional

from rag.manual_retriever import retrieve_manual_sections, format_citation

ASSET_TYPE_HINTS: dict[str, list[str]] = {
    "diesel_engine": ["engine", "diesel", "oil", "coolant", "radiator", "crankshaft", "fuel pump", "starter", "overheating", "rpm", "exhaust"],
    "electric_loco": ["pantograph", "inverter", "igbt", "traction motor", "electric", "loco", "overhead"],
    "bogie": ["bogie", "wheel", "axle", "bearing", "suspension", "spring", "flat spot", "vibration", "profile"],
    "brake_system": ["brake", "pad", "disc", "cylinder", "stopping", "air brake", "vacuum", "glazed", "fade"],
    "signal_unit": ["signal", "relay", "lamp", "aspect", "point motor", "interlocking", "crossing", "response time"],
    "track_section": ["track", "rail", "sleeper", "ballast", "tamping", "gauge", "geometry", "joint", "crack", "fishplate"],
    "level_crossing": ["crossing", "barrier", "gate", "proximity sensor", "level crossing"],
    "platform_gate": ["platform gate", "door", "gate motor"],
}

SYSTEM_PROMPT = """You are an expert railway maintenance engineer assistant for Sri Lanka Railways, with deep knowledge of diesel and electric locomotives, bogies, brakes, track, and signalling.

Rules:
1. Give a DIRECT, practical answer first — do not start by listing what the manual does or doesn't contain.
2. Use the provided manual sections as your primary source. Always cite which section your figures come from.
3. If the manual sections are incomplete, supplement with your general railway engineering knowledge but clearly label it as general guidance (e.g. "General practice:").
4. When time-based and mileage-based intervals both exist, state both clearly.
5. Keep answers concise and structured. Use short bullet points or a small table for intervals and specs.
6. If a question is completely outside railway maintenance (e.g. cooking, sports), politely redirect the engineer to ask a maintenance-related question.
7. Never refuse to answer a maintenance question just because the exact figure isn't in the manual — use your expertise and label it as such."""


def _detect_asset_type(message: str) -> str:
    lower = message.lower()
    scores: dict[str, int] = {}
    for asset_type, keywords in ASSET_TYPE_HINTS.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score:
            scores[asset_type] = score
    if not scores:
        return ""
    return max(scores, key=lambda k: scores[k])


def _build_context(sections: list[dict]) -> str:
    parts = []
    for i, s in enumerate(sections, 1):
        parts.append(
            f"[Section {i}] {s.get('manual', '')} — {s.get('section_title', '')}\n"
            f"{s.get('content', '')}"
        )
    return "\n\n".join(parts)


def _template_answer(message: str, sections: list[dict]) -> str:
    if not sections:
        return (
            "I could not find a relevant section in the equipment manuals for your question. "
            "Please consult the full manual or contact the Engineering Department."
        )
    top = sections[0]
    content = top.get("content", "")
    snippet = content[:400].strip()
    if len(content) > 400:
        snippet += "..."
    citation = format_citation(top)
    answer = f"Based on the maintenance manuals:\n\n{snippet}\n\n— Source: {citation}"
    if len(sections) > 1:
        extra = [format_citation(s) for s in sections[1:]]
        answer += f"\n\nAdditional references: {'; '.join(extra)}"
    return answer


def _llm_chat(message: str, history: list[dict]) -> str:
    """LLM response for greetings or out-of-scope questions (no manual sections found)."""
    try:
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in history[-6:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": message})
        response = client.chat.completions.create(
            model="groq/compound",
            max_tokens=300,
            messages=messages,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "Hello! I'm the RailSense Maintenance Assistant. Ask me anything about railway equipment maintenance, and I'll search the equipment manuals to help you."


def _llm_answer(
    message: str,
    sections: list[dict],
    history: list[dict],
) -> str:
    try:
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])

        context = _build_context(sections)
        user_content = (
            f"Manual sections:\n{context}\n\n"
            f"Engineer's question: {message}"
        )

        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in history[-6:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_content})

        response = client.chat.completions.create(
            model="groq/compound",
            max_tokens=500,
            messages=messages,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return _template_answer(message, sections)


def answer_engineer_question(
    message: str,
    asset_type: str = "",
    history: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """
    Returns:
        answer: str
        citations: list of retrieved manual sections
        retrieval_method: str
        answer_method: str
        detected_asset_type: str
    """
    history = history or []
    detected_type = asset_type or _detect_asset_type(message)

    sections, retrieval_method = retrieve_manual_sections(
        query=message,
        asset_type=detected_type,
        top_k=5,
    )

    if os.getenv("GROQ_API_KEY"):
        answer = _llm_answer(message, sections, history) if sections else _llm_chat(message, history)
        answer_method = "llm_grounded"
    else:
        answer = _template_answer(message, sections)
        answer_method = "template_grounded"

    citations = [
        {
            "manual": s.get("manual"),
            "section_title": s.get("section_title"),
            "snippet": str(s.get("content", ""))[:300],
            "source_file": s.get("source_file"),
            "score": s.get("score"),
        }
        for s in sections
    ]

    return {
        "answer": answer,
        "citations": citations,
        "retrieval_method": retrieval_method,
        "answer_method": answer_method,
        "detected_asset_type": detected_type,
    }
