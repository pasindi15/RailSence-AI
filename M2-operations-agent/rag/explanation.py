"""Phase 4 grounded explanation composition."""

import os
from typing import Optional


def _feature_label(feature: str) -> str:
    return feature.replace("_", " ").replace("incident type", "incident type")


def _template_explanation(
    route: str,
    predicted_delay: float,
    top_features: list[dict],
    incidents: list[dict],
) -> str:
    feature_text = ""
    if top_features:
        labels = [_feature_label(item["feature"]) for item in top_features[:3]]
        feature_text = f" The model's strongest signals are {', '.join(labels)}."

    precedent_text = ""
    if incidents:
        precedent = incidents[0]
        precedent_text = (
            f" A similar {precedent.get('incident_type', 'incident').replace('_', ' ')} "
            f"was recorded at {precedent.get('station', 'a nearby station')} on "
            f"{precedent.get('route', 'this network')} with a "
            f"{float(precedent.get('delay_minutes', 0)):.1f}-minute delay."
        )

    return (
        f"Expect approximately {predicted_delay:.1f} minutes of delay on {route}."
        f"{feature_text}{precedent_text}"
    )


def _llm_explanation(
    route: str,
    predicted_delay: float,
    top_features: list[dict],
    incidents: list[dict],
) -> Optional[str]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic

        evidence = "\n".join(
            f"- {item.get('incident_note', '')} ({item.get('delay_minutes', 0)} min historical delay)"
            for item in incidents
        ) or "- No similar historical incident was found."
        features = ", ".join(_feature_label(item["feature"]) for item in top_features[:3]) or "none available"
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=140,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Write one concise, factual railway operator explanation in 1-2 sentences. "
                        "Use only the supplied evidence, include the predicted delay, and do not "
                        "invent causes.\n"
                        f"Route: {route}\nPredicted delay: {predicted_delay:.1f} minutes\n"
                        f"Model signals: {features}\nSimilar incidents:\n{evidence}"
                    ),
                }
            ],
        )
        result = response.content[0].text.strip()
        return result or None
    except Exception:
        return None


def compose_explanation(
    route: str,
    predicted_delay: float,
    top_features: list[dict],
    incidents: list[dict],
    *,
    prefer_llm: bool = False,
) -> dict:
    """Return grounded explanation text and its transparent generation method."""
    if prefer_llm:
        result = _llm_explanation(route, predicted_delay, top_features, incidents)
        if result:
            return {"explanation": result, "method": "llm_grounded"}

    return {
        "explanation": _template_explanation(route, predicted_delay, top_features, incidents),
        "method": "template_grounded",
    }
