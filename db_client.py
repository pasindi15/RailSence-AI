"""
db_client.py
Supabase Postgres client — persists chat messages and feedback so they
survive a restart and give you real data for the Phase 3 evaluation
write-up (15-20 test conversations, precision@3 notes, etc).

Design choice: every function here swallows its own DB errors and logs a
warning instead of raising. A DB outage should degrade the chat experience
(no history saved) — it should never take the chat itself down. This
mirrors the same "graceful degradation" pattern used in hub_client.py.

supabase-py's client is synchronous, so calls are wrapped in
asyncio.to_thread to avoid blocking FastAPI's event loop.
"""

import asyncio
import logging
from typing import Optional

from config import settings

logger = logging.getLogger("passenger-agent.db")

_client = None
_client_init_failed = False


def _get_client():
    """Lazily creates the Supabase client. Returns None if not configured
    or if the supabase package isn't installed, so callers can no-op."""
    global _client, _client_init_failed

    if _client is not None:
        return _client
    if _client_init_failed:
        return None

    if not settings.SUPABASE_URL or not settings.SUPABASE_SECRET_KEY:
        logger.warning("Supabase not configured (SUPABASE_URL/SUPABASE_SECRET_KEY missing) — skipping persistence")
        _client_init_failed = True
        return None

    try:
        from supabase import create_client
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SECRET_KEY)
        return _client
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        _client_init_failed = True
        return None


async def save_message(session_id: str, role: str, content: str) -> None:
    """role must be 'user' or 'assistant'."""
    client = _get_client()
    if client is None:
        return

    def _insert():
        client.table("messages").insert({
            "session_id": session_id,
            "role": role,
            "content": content,
        }).execute()

    try:
        await asyncio.to_thread(_insert)
    except Exception as e:
        logger.error(f"Failed to save message to Supabase: {e}")


async def save_feedback(session_id: str, rating: str, comment: Optional[str]) -> None:
    client = _get_client()
    if client is None:
        return

    def _insert():
        client.table("feedback").insert({
            "session_id": session_id,
            "rating": rating,
            "comment": comment,
        }).execute()

    try:
        await asyncio.to_thread(_insert)
    except Exception as e:
        logger.error(f"Failed to save feedback to Supabase: {e}")


async def get_session_messages(session_id: str) -> list[dict]:
    """Returns message history for a session, oldest first. Empty list on
    any failure (including DB not configured) rather than raising."""
    client = _get_client()
    if client is None:
        return []

    def _select():
        res = (
            client.table("messages")
            .select("*")
            .eq("session_id", session_id)
            .order("created_at")
            .execute()
        )
        return res.data or []

    try:
        return await asyncio.to_thread(_select)
    except Exception as e:
        logger.error(f"Failed to fetch messages from Supabase: {e}")
        return []
