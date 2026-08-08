"""
LLM-powered summarization of long maintenance technician notes.
"""

import os
import anthropic

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


SYSTEM_PROMPT = """You are a railway maintenance intelligence assistant.
Summarize the technician note below into 1-2 clear sentences suitable for an operations brief.
Focus on: what the issue is, which component is affected, and any urgency indicated.
Do not invent details not present in the note."""


async def summarize_log(notes: str, component: str) -> str:
    if not notes.strip():
        return ""

    client = _get_client()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Component: {component}\n\nTechnician note:\n{notes}",
            }
        ],
    )
    return response.content[0].text.strip()
