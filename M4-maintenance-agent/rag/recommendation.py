"""Compose a grounded maintenance recommendation from ML prediction + manual RAG results.

Default: template-based grounding.
Optional: LLM composition when ANTHROPIC_API_KEY is set.
"""

import os
from typing import Any

from rag.manual_retriever import format_citation


def _template_recommendation(
    asset_id: str,
    asset_type: str,
    health_score: float,
    health_status: str,
    top_features: list[dict],
    manual_sections: list[dict],
    fault_type: str = "",
) -> str:
    status_phrase = {
        "GREEN": "is in good condition",
        "AMBER": "requires attention within the next 7 days",
        "RED": "is CRITICAL and must be withdrawn from service immediately",
    }.get(health_status, "requires review")

    lines = [
        f"Asset {asset_id} ({asset_type.replace('_', ' ')}) {status_phrase}. "
        f"Health score: {health_score:.1f}/100."
    ]

    if top_features:
        top = top_features[0]["feature"].replace("_", " ")
        lines.append(f"The strongest signal driving this assessment is {top}.")

    if fault_type and fault_type != "none":
        lines.append(f"Detected fault category: {fault_type.replace('_', ' ')}.")

    if manual_sections:
        section = manual_sections[0]
        snippet = section.get("content", "")[:200].strip()
        citation = format_citation(section)
        lines.append(f"Relevant guidance: \"{snippet}...\" — {citation}.")

    return " ".join(lines)


def _llm_recommendation(
    asset_id: str,
    asset_type: str,
    health_score: float,
    health_status: str,
    top_features: list[dict],
    manual_sections: list[dict],
    fault_type: str = "",
) -> str:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        context_parts = [
            f"Asset: {asset_id} ({asset_type})",
            f"Health Score: {health_score:.1f}/100",
            f"Health Status: {health_status}",
        ]
        if fault_type and fault_type != "none":
            context_parts.append(f"Detected Fault: {fault_type}")
        if top_features:
            feats = ", ".join(f['feature'] for f in top_features[:3])
            context_parts.append(f"Top Model Features: {feats}")
        if manual_sections:
            for i, s in enumerate(manual_sections[:2], 1):
                context_parts.append(
                    f"Manual Reference {i}: {s.get('section_title', '')} — {s.get('content', '')[:300]}"
                )

        prompt = (
            "You are a senior railway maintenance engineer. Based only on the information below, "
            "write a 2-3 sentence maintenance recommendation for the operator. "
            "Cite the manual reference if relevant. Be concise and actionable.\n\n"
            + "\n".join(context_parts)
        )
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception:
        return _template_recommendation(
            asset_id, asset_type, health_score, health_status,
            top_features, manual_sections, fault_type
        )


def compose_recommendation(
    asset_id: str,
    asset_type: str,
    health_score: float,
    health_status: str,
    top_features: list[dict],
    manual_sections: list[dict],
    fault_type: str = "",
) -> tuple[str, str]:
    """Returns (recommendation_text, method)."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return _llm_recommendation(
            asset_id, asset_type, health_score, health_status,
            top_features, manual_sections, fault_type
        ), "llm_grounded"
    return _template_recommendation(
        asset_id, asset_type, health_score, health_status,
        top_features, manual_sections, fault_type
    ), "template_grounded"
