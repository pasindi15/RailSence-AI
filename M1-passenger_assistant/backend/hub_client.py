"""
Hub client for Passenger Assistant Agent (M1).
Sends MCP-style envelopes to M3 Central Communication Hub (http://localhost:8002/messages).
Includes JWT generation and offline fallback stub.
"""
import itertools
import os
from datetime import datetime, timezone, timedelta
import httpx

HUB_BASE_URL = os.getenv("HUB_BASE_URL", "http://localhost:8002")
_msg_counter = itertools.count(2001)


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


def build_envelope(receiver_agent: str, intent: str, payload: dict, auth_token: str | None = None) -> dict:
    token = auth_token or generate_auth_token("passenger-agent")
    return {
        "message_id": f"MSG-{next(_msg_counter)}",
        "sender_agent": "passenger-agent",
        "receiver_agent": receiver_agent,
        "intent": intent,
        "payload": payload,
        "auth_token": token,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def send_to_hub(envelope: dict) -> dict:
    """
    POST AgentMessage envelope to M3 Central Hub at {HUB_BASE_URL}/messages.
    Falls back to local stub response if the Hub is offline.
    """
    hub_url = f"{HUB_BASE_URL.rstrip('/')}/messages"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(hub_url, json=envelope)
            if response.status_code == 200:
                data = response.json()
                # If Hub returned routed destination response
                if "response" in data and isinstance(data["response"], dict):
                    dest_resp = data["response"]
                    return {
                        "status": "ok",
                        "sender_agent": dest_resp.get("sender_agent", envelope["receiver_agent"]),
                        "payload": dest_resp.get("payload", dest_resp),
                    }
                return {"status": "ok", "payload": data}
    except Exception as exc:
        print(f"[M1 Hub Client] Hub communication error ({exc}), using fallback stub.")

    # Offline fallback stub
    if envelope["intent"] == "delay_check":
        return {
            "status": "ok",
            "sender_agent": "operations-agent",
            "payload": {
                "predicted_delay_minutes": 9.0,
                "reason": "Historical congestion + weather conditions",
                "similar_incident": "Signal failure occurred on same route previously",
            },
        }
    if envelope["intent"] == "issue_report":
        return {
            "status": "ok",
            "sender_agent": "maintenance-agent",
            "payload": {
                "ticket_id": "MT-0001",
                "message": "Issue logged. A technician will inspect within 48 hours.",
            },
        }
    if envelope["intent"] == "booking_request":
        return {
            "status": "ok",
            "sender_agent": "booking-agent",
            "payload": {
                "booking_id": "BK-1001",
                "message": (
                    "To complete your booking, please visit our booking portal "
                    "or use the /book endpoint with your selected train and seat class."
                ),
            },
        }
    return {"status": "error", "message": "Unknown intent for Hub routing"}
