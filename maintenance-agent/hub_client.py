import httpx
import uuid
from datetime import datetime, timezone
import os

HUB_URL = os.getenv("HUB_URL", "http://agent-hub:8000")
AGENT_NAME = "maintenance-agent"
JWT_TOKEN = os.getenv("MAINTENANCE_AGENT_TOKEN", "")


def _envelope(receiver: str, intent: str, payload: dict) -> dict:
    return {
        "message_id": str(uuid.uuid4()),
        "sender_agent": AGENT_NAME,
        "receiver_agent": receiver,
        "intent": intent,
        "payload": payload,
        "auth_token": JWT_TOKEN,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def publish_maintenance_alert(train_id: str, component: str, health_result: dict):
    msg = _envelope(
        receiver="operations-agent",
        intent="maintenance_alert",
        payload={
            "train_id": train_id,
            "component": component,
            "health": health_result.get("health"),
            "days_to_service": health_result.get("days_to_service"),
            "recommendation": health_result.get("recommendation"),
        },
    )
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(f"{HUB_URL}/route", json=msg)


async def subscribe_delay_alert(payload: dict):
    """
    Called when Operations publishes a delay_alert.
    Checks whether the affected train has open maintenance flags.
    """
    train_id = payload.get("payload", {}).get("train_id")
    if train_id:
        status = _check_local_health(train_id)
        if status and status.get("health") in ("AMBER", "RED"):
            await publish_maintenance_alert(train_id, component="(delay correlation)", health_result=status)


def _check_local_health(train_id: str) -> dict | None:
    from predictive.predict_status import predict_health
    return predict_health(train_id, component=None, sensor_readings={}, last_service_date=None)
