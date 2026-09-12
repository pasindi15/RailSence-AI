"""
Hub client stub.
NOT wired into /chat yet - that happens in Phase 3, once the message envelope
contract is agreed with Member C (Hub owner).

Expected envelope shape (from RailSense_AI_Complete_Implementation_Guide):

{
  "message_id": "uuid",
  "sender_agent": "passenger-agent",
  "receiver_agent": "operations-agent" | "maintenance-agent",
  "intent": "delay_check" | "issue_report",
  "payload": { ... },
  "auth_token": "JWT",
  "timestamp": "ISO8601"
}
"""
import itertools
from datetime import datetime, timezone

HUB_BASE_URL = "http://localhost:9000"  # placeholder, move to .env once agreed
_msg_counter = itertools.count(2001)


def build_envelope(receiver_agent: str, intent: str, payload: dict, auth_token: str = "placeholder") -> dict:
    return {
        "message_id": f"MSG-{next(_msg_counter)}",
        "sender_agent": "passenger-agent",
        "receiver_agent": receiver_agent,
        "intent": intent,
        "payload": payload,
        "auth_token": auth_token,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def send_to_hub(envelope: dict) -> dict:
    """
    Phase 3 TODO: replace this stub with a real httpx.AsyncClient POST to HUB_BASE_URL.
    For now, returns a fake response so /chat can be tested end-to-end.
    """
    if envelope["intent"] == "delay_check":
        return {
            "status": "ok",
            "sender_agent": "operations-agent",
            "payload": {
                "predicted_delay_minutes": 9,
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
