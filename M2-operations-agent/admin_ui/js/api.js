// Shared fetch helper & session manager for M2 Admin & RBAC Suite.
const API_BASE = "/admin/api";

const AdminAPI = {
  TOKEN_KEY: "railsense_m2_token",
  USER_KEY: "railsense_m2_officer",

  getToken() {
    return localStorage.getItem(this.TOKEN_KEY);
  },

  getCurrentUser() {
    try {
      return JSON.parse(localStorage.getItem(this.USER_KEY) || "null");
    } catch (_) {
      return null;
    }
  },

  setSession(token, officer) {
    if (token) localStorage.setItem(this.TOKEN_KEY, token);
    if (officer) localStorage.setItem(this.USER_KEY, JSON.stringify(officer));
  },

  clearSession() {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
  },

  async request(path, options = {}) {
    const headers = options.headers || {};
    const token = this.getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    if (options.body && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }

    let resp;
    try {
      resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
    } catch (netErr) {
      throw new Error("Unable to connect to M2 Operations service. Check if service is running.");
    }

    if (resp.status === 401) {
      this.clearSession();
      if (typeof showLoginScreen === "function") showLoginScreen();
      throw new Error("Session expired or invalid. Please sign in.");
    }

    let data = null;
    try { data = await resp.json(); } catch (_) { /* no json body */ }

    if (!resp.ok) {
      const detail = data && data.detail ? data.detail : resp.statusText;
      const msg = typeof detail === "string" ? detail : (detail.message || JSON.stringify(detail));
      const err = new Error(msg);
      err.status = resp.status;
      throw err;
    }
    return data;
  },

  get(path) { return this.request(path, { method: "GET" }); },
  post(path, body) { return this.request(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }); },
  put(path, body) { return this.request(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }); },
  del(path) { return this.request(path, { method: "DELETE" }); },
  postForm(path, formData) { return this.request(path, { method: "POST", body: formData }); },

  async login(emailOrUsername, password) {
    const resp = await fetch(`${API_BASE}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: emailOrUsername, password }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      const detail = data.detail || "Authentication failed.";
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    this.setSession(data.token, data.officer);
    return data;
  },

  async logout() {
    try {
      await this.post("/logout", {});
    } catch (_) {
      /* ignore network errors on logout */
    } finally {
      this.clearSession();
      if (typeof showLoginScreen === "function") showLoginScreen();
    }
  },
};

// ---------------- Toasts ----------------
function toast(message, type = "info") {
  const stack = document.getElementById("toast-stack");
  if (!stack) return;
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
