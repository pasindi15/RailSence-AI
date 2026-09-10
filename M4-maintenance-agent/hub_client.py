"""HTTP and Upstash adapters for the shared RailSense agent hub.

All outbound calls are best-effort so the dashboard remains demoable offline.
"""

import os
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

HUB_BASE_URL = os.getenv("HUB_BASE_URL", "http://localhost:8000")
AGENT_NAME = "maintenance-agent"

MAINTENANCE_ALERT_THRESHOLD = "RED"
HUB_AUTH_TOKEN = os.getenv("HUB_AUTH_TOKEN", os.getenv("JWT_TOKEN", ""))
HUB_MESSAGE_PATH = os.getenv("HUB_MESSAGE_PATH", "/messages")
UPSTASH_REDIS_URL = os.getenv("UPSTASH_REDIS_URL", "").rstrip("/")
UPSTASH_REDIS_TOKEN = os.getenv("UPSTASH_REDIS_TOKEN", "")


async def _post_hub(path: str, payload: dict[str, Any]) -> dict:
    headers = {"Authorization": f"Bearer {HUB_AUTH_TOKEN}"} if HUB_AUTH_TOKEN else {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.post(
            f"{HUB_BASE_URL.rstrip('/')}{path}", json=payload, headers=headers
        )
        response.raise_for_status()
        return response.json() if response.content else {"ok": True}


async def register_with_hub() -> None:
    await _post_hub(
        "/register",
        {
            "agent_name": AGENT_NAME,
            "capabilities": ["maintenance_check", "asset_health", "manual_search"],
            "callback_url": os.getenv("MAINTENANCE_AGENT_URL", "http://localhost:8002"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


async def send_to_hub(
    receiver_agent: str, intent: str, payload: dict[str, Any], auth_token: str
) -> dict:
    envelope = {
        "message_id": uuid.uuid4().hex,
        "sender_agent": AGENT_NAME,
        "receiver_agent": receiver_agent,
        "intent": intent,
        "payload": payload,
        "auth_token": auth_token,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return await _post_hub(HUB_MESSAGE_PATH, envelope)


async def publish_maintenance_alert(
    asset_id: str, asset_type: str, health_status: str, health_score: float, recommended_action: str
) -> dict:
    """Publish a RED-status asset alert to Hub and/or Upstash Redis."""
    if health_status != MAINTENANCE_ALERT_THRESHOLD:
        return {"published": False, "reason": "not_critical"}
    event = {
        "event_type": "maintenance_alert",
        "sender_agent": AGENT_NAME,
        "asset_id": asset_id,
        "asset_type": asset_type,
        "health_status": health_status,
        "health_score": health_score,
        "recommended_action": recommended_action,
        "threshold": MAINTENANCE_ALERT_THRESHOLD,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    destinations, errors = [], []
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.post(
                    f"{UPSTASH_REDIS_URL}/publish/maintenance_alert",
                    headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                    json=[json.dumps(event)],
                )
                response.raise_for_status()
                destinations.append("upstash_redis")
        except Exception as exc:
            errors.append(f"upstash_redis: {exc}")
    try:
        await _post_hub("/events", event)
        destinations.append("hub")
    except Exception as exc:
        errors.append(f"hub: {exc}")
    return {"published": bool(destinations), "destinations": destinations, "errors": errors, "event": event}
