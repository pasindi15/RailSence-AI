import asyncio

import httpx
import respx

from hub_client import AGENT_HUB_URL, HUB_ROUTE_PATH, build_envelope, send_to_hub

HUB_URL = f"{AGENT_HUB_URL.rstrip('/')}/{HUB_ROUTE_PATH.lstrip('/')}"


@respx.mock
def test_send_to_hub_success_round_trip():
    envelope = build_envelope(
        receiver_agent="maintenance-agent", intent="issue_report", payload={"description": "AC broken"}
    )
    respx.post(HUB_URL).mock(
        return_value=httpx.Response(
            200,
            json={"sender_agent": "maintenance-agent", "payload": {"ticket_id": "MT-9001", "message": "Issue logged."}},
        )
    )

    response = asyncio.run(send_to_hub(envelope))

    assert response.status == "ok"
    assert response.sender_agent == "maintenance-agent"
    assert response.payload["ticket_id"] == "MT-9001"
    assert response.payload["message"] == "Issue logged."


@respx.mock
def test_send_to_hub_timeout_falls_back_gracefully():
    envelope = build_envelope(receiver_agent="operations-agent", intent="delay_check", payload={})
    route = respx.post(HUB_URL).mock(side_effect=httpx.TimeoutException("timed out"))

    response = asyncio.run(send_to_hub(envelope))

    assert response.status == "error"
    assert response.message == "I couldn't reach that service right now — please try again shortly."
    # One retry means two attempts total, not an unbounded/absent retry.
    assert route.call_count == 2


@respx.mock
def test_send_to_hub_non_200_returns_error():
    envelope = build_envelope(receiver_agent="booking-agent", intent="booking_request", payload={})
    respx.post(HUB_URL).mock(return_value=httpx.Response(500))

    response = asyncio.run(send_to_hub(envelope))

    assert response.status == "error"
    assert response.message == "I couldn't reach that service right now — please try again shortly."
