// The app is served by the RailSense gateway (user side), which passes /svc/m1/* through
// to the M1 backend on whatever port start.py chose on this laptop — so no port is
// hard-coded here. `npm run dev` proxies /svc and /api to the gateway (vite.config.js).
// VITE_M1_URL still overrides this for a custom setup.
const BASE_URL = import.meta.env.VITE_M1_URL || "/svc/m1";

// The signed token from POST /auth/login. Every chat call carries it, and the
// backend reads the passenger's identity from it - the browser never sends a
// user_id of its own, because a value the browser chooses is a value any
// browser could choose.
const TOKEN_KEY = "railsense_token";

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {}
}

function authHeaders(extra) {
  const token = getToken();
  return {
    ...(extra || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

// A 401 means the token is missing, expired or invalid. Drop it so the app
// falls back to the login screen instead of retrying forever with a dead one.
function checkAuth(res) {
  if (res.status === 401) {
    setToken(null);
    throw new Error("UNAUTHORIZED");
  }
  return res;
}

export async function login(username, password) {
  const res = await fetch(`${BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (res.status === 401) throw new Error("Invalid username or password.");
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Sign-in failed. Please try again.");
  }
  const data = await res.json();
  setToken(data.access_token);
  return data;
}

export function logout() {
  setToken(null);
}

export async function sendMessage(sessionId, message) {
  const res = await fetch(`${BASE_URL}/chat`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!res.ok) throw new Error("Chat request failed");
  return res.json();
}

export async function getHistory(sessionId) {
  const res = checkAuth(await fetch(`${BASE_URL}/chat/${sessionId}/history`, { headers: authHeaders() }));
  if (!res.ok) throw new Error("History request failed");
  return res.json();
}

export async function listChats() {
  const res = checkAuth(await fetch(`${BASE_URL}/chat`, { headers: authHeaders() }));
  if (!res.ok) throw new Error("Failed to load chat list");
  return res.json();
}

export async function deleteChat(sessionId) {
  const res = checkAuth(await fetch(`${BASE_URL}/chat/${sessionId}`, { method: "DELETE", headers: authHeaders() }));
  if (!res.ok && res.status !== 204) throw new Error("Failed to delete chat");
}

export async function pinChat(sessionId, pinned) {
  const res = checkAuth(await fetch(`${BASE_URL}/chat/${sessionId}/pin`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ pinned }),
  }));
  if (!res.ok) throw new Error("Failed to update pin");
  return res.json();
}

export async function getTrainDetails(trainId) {
  const res = await fetch(`${BASE_URL}/trains/${encodeURIComponent(trainId)}/details`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("Train details request failed");
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

  const gatewayRes = await fetch("/api/cancellations/confirm", {
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

export async function renameChat(sessionId, title) {
  const res = checkAuth(await fetch(`${BASE_URL}/chat/${sessionId}/title`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ title }),
  }));
  if (!res.ok) throw new Error("Failed to rename chat");
  return res.json();
}
