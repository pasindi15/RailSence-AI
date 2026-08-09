"""HTTP and Upstash adapters for the shared RailSense agent hub.

Mirrors the pattern used in M2-operations-agent/hub_client.py.
All outbound calls are best-effort so the service stays demoable offline.
"""

import httpx
import json
import uuid
import os
from datetime import datetime, timezone

HUB_BASE_URL = os.getenv("HUB_BASE_URL", "http://localhost:8000")
AGENT_NAME = "maintenance-agent"
HUB_AUTH_TOKEN = os.getenv("MAINTENANCE_AGENT_TOKEN", os.getenv("JWT_TOKEN", ""))
HUB_MESSAGE_PATH = os.getenv("HUB_MESSAGE_PATH", "/messages")
UPSTASH_REDIS_URL = os.getenv("UPSTASH_REDIS_URL", "").rstrip("/")
UPSTASH_REDIS_TOKEN = os.getenv("UPSTASH_REDIS_TOKEN", "")


async def _post_hub(path: str, payload: dict) -> dict:
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
            "capabilities": ["maintenance_alert", "manual_query", "log_ingest"],
            "callback_url": os.getenv("MAINTENANCE_AGENT_URL", "http://localhost:8004"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def _envelope(receiver: str, intent: str, payload: dict) -> dict:
    return {
        "message_id": uuid.uuid4().hex,
        "sender_agent": AGENT_NAME,
        "receiver_agent": receiver,
        "intent": intent,
        "payload": payload,
        "auth_token": HUB_AUTH_TOKEN,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def publish_maintenance_alert(
    train_id: str, component: str, health_result: dict
) -> dict:
    event = {
        "event_type": "maintenance_alert",
        "sender_agent": AGENT_NAME,
        "train_id": train_id,
        "component": component,
        "health": health_result.get("health"),
        "days_to_service": health_result.get("days_to_service"),
        "recommendation": health_result.get("recommendation"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    destinations, errors = [], []

    # Publish to Upstash Redis (same channel pattern as operations-agent)
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

    # Also notify Hub directly
    try:
        await _post_hub("/events", event)
        destinations.append("hub")
    except Exception as exc:
        errors.append(f"hub: {exc}")

    return {
        "published": bool(destinations),
        "destinations": destinations,
        "errors": errors,
        "event": event,
    }


async def subscribe_delay_alert(payload: dict) -> None:
    """
    Called when Operations publishes a delay_alert event.
    Checks whether the affected train has open maintenance flags and
    publishes a maintenance_alert if RED or AMBER.
    """
    train_id = payload.get("payload", {}).get("train_id") or payload.get("train_id")
    if not train_id:
        return

    status = _check_local_health(train_id)
    if status and status.get("health") in ("AMBER", "RED"):
        await publish_maintenance_alert(
            train_id, component="(delay correlation)", health_result=status
        )


def _check_local_health(train_id: str) -> dict | None:
    from predictive.predict_status import predict_health
    return predict_health(
        train_id, component=None, sensor_readings={}, last_service_date=None
    )
