"""
llm_client.py
Thin wrapper so the rest of the app never cares which LLM provider is behind it.
Phase 1 goal: prove ONE call works end-to-end. Swap providers by changing
LLM_PROVIDER in .env — no other code changes needed.
"""

from config import settings


class LLMError(RuntimeError):
    pass


async def generate_reply(system_prompt: str, user_message: str) -> str:
    """Sends a single system+user turn to the configured LLM and returns the text reply.
    Phase 2 will extend this to accept retrieved RAG context as extra system content."""

    if not settings.LLM_API_KEY:
        raise LLMError("LLM_API_KEY is missing. Add it to your .env file.")

    if settings.LLM_PROVIDER == "openai":
        return await _call_openai(system_prompt, user_message)
    elif settings.LLM_PROVIDER == "anthropic":
        return await _call_anthropic(system_prompt, user_message)
    else:
        raise LLMError(f"Unknown LLM_PROVIDER: {settings.LLM_PROVIDER}")


async def _call_openai(system_prompt: str, user_message: str) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.LLM_API_KEY)
    response = await client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        max_tokens=400,
        temperature=0.3,
    )
    return response.choices[0].message.content or ""


async def _call_anthropic(system_prompt: str, user_message: str) -> str:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.LLM_API_KEY)
    response = await client.messages.create(
        model=settings.LLM_MODEL,
        max_tokens=400,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text if response.content else ""
