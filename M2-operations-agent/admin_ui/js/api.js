// Shared fetch helper for the M2 admin dashboard.
// All admin API routes live under /admin/api (see backend/admin_router.py).

const API_BASE = "/admin/api";

const AdminAPI = {
  getToken() {
    return localStorage.getItem("m2_admin_token");
  },
  setToken(token) {
    localStorage.setItem("m2_admin_token", token);
  },
  clearToken() {
    localStorage.removeItem("m2_admin_token");
  },

  async request(path, options = {}) {
    const headers = options.headers || {};
    const token = this.getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    if (options.body && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }

    const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });

    if (resp.status === 401) {
      this.clearToken();
      showLoginScreen();
      throw new Error("Session expired — please log in again.");
    }

    let data = null;
    try { data = await resp.json(); } catch (_) { /* no body */ }

    if (!resp.ok) {
      const detail = data && data.detail ? data.detail : resp.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  },

  get(path) { return this.request(path, { method: "GET" }); },
  post(path, body) { return this.request(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }); },
  put(path, body) { return this.request(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }); },
  del(path) { return this.request(path, { method: "DELETE" }); },
  postForm(path, formData) { return this.request(path, { method: "POST", body: formData }); },

  async login(username, password) {
    const resp = await fetch(`${API_BASE}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Login failed");
    this.setToken(data.token);
    return data;
  },
};

// ---------------- Toasts ----------------
function toast(message, type = "info") {
  const stack = document.getElementById("toast-stack");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  stack.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function formatDate(value) {
  if (!value) return "—";
  try {
    const d = typeof value === "number" ? new Date(value * (value < 2e10 ? 1000 : 1)) : new Date(value);
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleString();
  } catch (_) {
    return String(value);
  }
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
