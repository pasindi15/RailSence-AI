"""
Hub client for Passenger Assistant Agent (M1).
Sends AgentMessage envelopes to the M3 Central Communication Hub and returns
its response. Falls back to a local mock (USE_MOCK_HUB=true) for local dev
when the Hub isn't running.

Response contract for downstream agents (Operations/Maintenance/Booking):
their payload's natural-language text is already composed by that agent (its
own LLM/template layer) - this module and main.py's intent handlers pass it
through as-is and must not re-run it through Gemini. The one exception is
delay_check: Operations' /hub/message doesn't hand back a single composed
sentence, it hands back structured fields (predicted_delay_minutes,
explanation, similar_incident) that main.py assembles into a reply - that's
not re-composition, there's no LLM call on M1's side either way.
"""
import itertools
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

# Same reasoning as main.py's load_dotenv() call: anchor to this file's own
# directory rather than the CWD. Safe to call again if main.py already did -
# and needed here too since this module's tests import it standalone.
load_dotenv(Path(__file__).parent / ".env")

# Reuses the .env var name the team already settled on (AGENT_HUB_URL) rather
# than introducing a second one for the same thing.
AGENT_HUB_URL = os.getenv("AGENT_HUB_URL", "http://localhost:8002")
HUB_ROUTE_PATH = os.getenv("HUB_ROUTE_PATH", "messages")
HUB_TIMEOUT_SECONDS = float(os.getenv("HUB_TIMEOUT_SECONDS", "15"))
USE_MOCK_HUB = os.getenv("USE_MOCK_HUB", "false").strip().lower() in ("1", "true", "yes")

HUB_UNREACHABLE_MESSAGE = "I couldn't reach that service right now — please try again shortly."

_msg_counter = itertools.count(2001)  # kept for any other caller still relying on it


class HubMessage(BaseModel):
    message_id: str
    sender_agent: str
    receiver_agent: str
    intent: str
    payload: dict
    auth_token: str
    timestamp: str


class HubResponse(BaseModel):
    status: str  # "ok" | "error"
    sender_agent: str | None = None
    payload: dict = {}
    message: str | None = None


def generate_auth_token(sender_agent: str = "passenger-agent") -> str:
    """Generate valid JWT token signed with JWT_SECRET_KEY for Hub authentication."""
    try:
        import jwt
        secret = os.getenv("JWT_SECRET_KEY", "change-me")
        algo = os.getenv("JWT_ALGORITHM", "HS256")
        now = datetime.now(timezone.utc)
        payload = {
            "sub": sender_agent,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=2)).timestamp()),
        }
        return jwt.encode(payload, secret, algorithm=algo)
    except Exception:
        return "placeholder-token"


def build_envelope(receiver_agent: str, intent: str, payload: dict, auth_token: str | None = None) -> HubMessage:
    token = auth_token or generate_auth_token("passenger-agent")
    return HubMessage(
        message_id=str(uuid.uuid4()),
        sender_agent="passenger-agent",
        receiver_agent=receiver_agent,
        intent=intent,
        payload=payload,
        auth_token=token,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


async def send_to_hub(message: HubMessage) -> HubResponse:
    """
    POST an AgentMessage envelope to the M3 Central Hub at
    {AGENT_HUB_URL}/{HUB_ROUTE_PATH}.

    One retry on timeout/connection error. Never raises - a non-200 response,
    a repeated timeout, or any other failure all resolve to a HubResponse with
    status="error" and a user-facing message, so a downstream agent being slow
    or offline degrades /chat gracefully instead of 500ing it.
    """
    if USE_MOCK_HUB:
        print(f"[hub] USE_MOCK_HUB=true - routing message_id={message.message_id} to local mock instead of {AGENT_HUB_URL}")
        return send_to_hub_mock(message)

    url = f"{AGENT_HUB_URL.rstrip('/')}/{HUB_ROUTE_PATH.lstrip('/')}"
    print(f"[hub] -> message_id={message.message_id} receiver_agent={message.receiver_agent} intent={message.intent} url={url}")

    attempts = 2  # one retry
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=HUB_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=message.model_dump())
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_error = exc
            print(f"[hub] !! message_id={message.message_id} attempt={attempt}/{attempts} {type(exc).__name__}: {exc}")
            continue
        except Exception as exc:
            # Not a timeout/connection issue (e.g. malformed URL) - retrying won't help.
            print(f"[hub] !! message_id={message.message_id} unexpected error ({type(exc).__name__}): {exc}")
            return HubResponse(status="error", message=HUB_UNREACHABLE_MESSAGE)

        print(f"[hub] <- message_id={message.message_id} status_code={response.status_code} attempt={attempt}/{attempts}")
        if response.status_code == 200:
            data = response.json()
            # Some Hub responses wrap the destination agent's reply under "response".
            dest_resp = data.get("response") if isinstance(data.get("response"), dict) else data
            return HubResponse(
                status="ok",
                sender_agent=dest_resp.get("sender_agent", message.receiver_agent),
                payload=dest_resp.get("payload", dest_resp),
            )
        return HubResponse(status="error", message=HUB_UNREACHABLE_MESSAGE)

    print(f"[hub] !! message_id={message.message_id} giving up after {attempts} attempts ({type(last_error).__name__}: {last_error})")
    return HubResponse(status="error", message=HUB_UNREACHABLE_MESSAGE)


def send_to_hub_mock(message: HubMessage) -> HubResponse:
    """Offline stub - used when USE_MOCK_HUB=true (e.g. local dev without the Hub running)."""
    if message.intent == "delay_check":
        return HubResponse(
            status="ok",
            sender_agent="operations-agent",
            payload={
                "predicted_delay_minutes": 25.0,
                "reason": "Mechanical fault — brake system maintenance in progress",
                "similar_incident": "Similar brake maintenance delay recorded on same route 3 weeks ago",
            },
        )
    if message.intent == "train_status_query":
        train_id = message.payload.get("train_id", "UNKNOWN")
        return HubResponse(
            status="ok",
            sender_agent="maintenance-agent",
            payload={
                "train_id": train_id,
                "under_maintenance": True,
                "found": True,
                "reason": "Brake system inspection and component replacement",
                "estimated_clear": "14:30 today",
                "message": f"Train {train_id} is currently under maintenance — brake system inspection.",
            },
        )
    if message.intent == "issue_report":
        return HubResponse(
            status="ok",
            sender_agent="maintenance-agent",
            payload={
                "ticket_id": "MT-0001",
                "message": "Issue logged. A technician will inspect within 48 hours.",
            },
        )
    if message.intent == "booking_request":
        return HubResponse(
            status="ok",
            sender_agent="booking-agent",
            payload={
                "booking_id": "BK-1001",
                "message": (
                    "To complete your booking, please visit our booking portal "
                    "or use the /book endpoint with your selected train and seat class."
                ),
            },
        )
    return HubResponse(status="error", message="Unknown intent for Hub routing")
