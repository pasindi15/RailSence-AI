const BASE_URL = "http://localhost:8001";

export async function sendMessage(sessionId, message) {
  const res = await fetch(`${BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!res.ok) throw new Error("Chat request failed");
  return res.json();
}

export async function getHistory(sessionId) {
  const res = await fetch(`${BASE_URL}/chat/${sessionId}/history`);
  if (!res.ok) throw new Error("History request failed");
  return res.json();
}

export async function listChats() {
  const res = await fetch(`${BASE_URL}/chat`);
  if (!res.ok) throw new Error("Failed to load chat list");
  return res.json();
}

export async function deleteChat(sessionId) {
  const res = await fetch(`${BASE_URL}/chat/${sessionId}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error("Failed to delete chat");
}

export async function pinChat(sessionId, pinned) {
  const res = await fetch(`${BASE_URL}/chat/${sessionId}/pin`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pinned }),
  });
  if (!res.ok) throw new Error("Failed to update pin");
  return res.json();
}

export async function submitCancellationRequest(bookingRef, reason, userId = "passenger_web_user") {
  try {
    const res = await fetch(`${BASE_URL}/cancellations/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        booking_reference: bookingRef,
        reason: reason,
        user_id: userId,
      }),
    });
    if (res.ok) return await res.json();
  } catch (e) {
    console.warn("M1 cancellations endpoint fallback:", e);
  }

  const gatewayRes = await fetch("http://localhost:3000/api/cancellations/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      booking_reference: bookingRef,
      reason: reason,
    }),
  });
  if (!gatewayRes.ok) throw new Error("Cancellation request failed");
  return gatewayRes.json();
}
