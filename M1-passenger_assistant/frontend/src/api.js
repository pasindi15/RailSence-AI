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
