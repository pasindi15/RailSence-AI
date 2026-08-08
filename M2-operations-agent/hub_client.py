"""
M2 — Operations & Delay-Prediction Agent
Hub client stub.

Phase 5 TODO:
    - send_to_hub(): POST a message envelope (per Section 6.2/8.3 of the
      implementation guide) to the Hub, e.g. responding to a delay_check
      request routed from the Passenger Agent.
    - publish_delay_alert(): fire a delay_alert event through the Hub /
      Upstash Redis pub-sub whenever a predicted delay crosses the alert
      threshold, so Security and Maintenance can subscribe to it.
    - register_with_hub(): send a register/heartbeat message on startup so
      the Hub's service registry knows this agent is online.

Left unimplemented in Phase 1 on purpose — the ML/NLP/RAG pieces (Phases
2-4) need to exist before there's anything meaningful to send.
"""

import os
from datetime import datetime, timezone
from typing import Any

import httpx

HUB_BASE_URL = os.getenv("HUB_BASE_URL", "http://localhost:8000")
AGENT_NAME = "operations-agent"

DELAY_ALERT_THRESHOLD_MINUTES = 5.0


async def register_with_hub() -> None:
    """TODO (Phase 5): call Hub's /register endpoint on startup."""
    raise NotImplementedError("Hub registration lands in Phase 5")


async def send_to_hub(receiver_agent: str, intent: str, payload: dict[str, Any], auth_token: str) -> dict:
    """TODO (Phase 5): build the shared message envelope and POST it to the Hub."""
    envelope = {
        "sender_agent": AGENT_NAME,
        "receiver_agent": receiver_agent,
        "intent": intent,
        "payload": payload,
        "auth_token": auth_token,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    raise NotImplementedError("Hub message sending lands in Phase 5")


async def publish_delay_alert(route: str, train_id: str, predicted_delay_minutes: float) -> None:
    """TODO (Phase 5): publish a delay_alert event if predicted_delay_minutes
    exceeds DELAY_ALERT_THRESHOLD_MINUTES, so Security/Maintenance can react."""
    raise NotImplementedError("delay_alert publishing lands in Phase 5")
