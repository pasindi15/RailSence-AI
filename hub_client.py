"""
hub_client.py
Sends messages to the Agent Communication Hub (Member C's service) using
the shared envelope defined in schemas.HubMessage.

Phase 1: function exists and is fully wired, but nothing calls it yet —
there's no live Hub to call against. Point HUB_URL at a stub/mock server
as soon as one exists so this stops being theoretical.

Phase 3: this becomes load-bearing for delay_check / complaint intents.
Before then, confirm with Member C:
  - exact payload field names per intent (see conversation notes)
  - what a success vs. timeout vs. error response looks like
  - how auth_token is issued/refreshed
"""

import httpx

from config import settings
from schemas import HubMessage, HubResponse


class HubClientError(RuntimeError):
    pass


async def send_to_hub(
    receiver_agent: str,
    intent: str,
    payload: dict,
    auth_token: str,
) -> HubResponse:
    message = HubMessage(
        receiver_agent=receiver_agent,
        intent=intent,
        payload=payload,
        auth_token=auth_token,
    )

    try:
        async with httpx.AsyncClient(timeout=settings.HUB_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.HUB_URL}/route",
                json=message.model_dump(),
            )
            resp.raise_for_status()
            return HubResponse(**resp.json())

    except httpx.TimeoutException:
        return HubResponse(message_id=message.message_id, status="timeout", error="Hub did not respond in time")
    except httpx.HTTPStatusError as e:
        return HubResponse(message_id=message.message_id, status="error", error=str(e))
    except httpx.RequestError as e:
        # Hub is unreachable entirely (not built yet, or down) — this is
        # expected through most of Phase 1/2, so callers must handle it
        # gracefully rather than crash the chat.
        return HubResponse(message_id=message.message_id, status="error", error=f"Hub unreachable: {e}")
