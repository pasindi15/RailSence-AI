// App shell: dynamic RBAC sidebar nav, hash routing, profile popover, and login flow.

const VIEWS = [
  { id: "home", label: "Home", icon: "🏠", group: null, title: "Operations Overview", adminOnly: false },
  { id: "officers", label: "Officers & Access", icon: "👥", group: "Officers & RBAC", title: "Officers & Access Control", adminOnly: true },
  { id: "roles", label: "Roles & Permissions", icon: "🔑", group: "Officers & RBAC", title: "Roles & Permissions Matrix", adminOnly: true },
  { id: "data", label: "Data Management", icon: "🗄️", group: "Operations", title: "Data Management", adminOnly: true },
  { id: "incidents", label: "Incident Review Queue", icon: "📋", group: "Operations", title: "Incident Review Queue", adminOnly: true },
  { id: "health", label: "System Health & Config", icon: "💻", group: "Administration", title: "System Health & Config", adminOnly: true },
  { id: "model", label: "Model Operations", icon: "🧠", group: "Administration", title: "Model Operations", adminOnly: true },
  { id: "hub", label: "Hub & Event Control", icon: "🔗", group: "Administration", title: "Hub & Event Control", adminOnly: true },
  { id: "audit", label: "Audit Logs", icon: "🛡️", group: "Security & Audit", title: "Security Audit Logs", adminOnly: true },
];

const VIEW_LOADERS = {
  home: () => window.ViewHome && window.ViewHome.load(),
  officers: () => window.ViewOfficers && window.ViewOfficers.load(),
  roles: () => window.ViewRoles && window.ViewRoles.load(),
  data: () => window.ViewData && window.ViewData.load(),
  incidents: () => window.ViewIncidents && window.ViewIncidents.load(),
  health: () => window.ViewHealth && window.ViewHealth.load(),
  model: () => window.ViewModel && window.ViewModel.load(),
  hub: () => window.ViewHub && window.ViewHub.load(),
  audit: () => window.ViewAudit && window.ViewAudit.load(),
};

function getAuthorizedViews() {
  const user = AdminAPI.getCurrentUser();
  const isAdmin = user && user.role === "admin";
  if (isAdmin) {
    return VIEWS;
  }
  // Operations Engineer or other non-admin
  return VIEWS.filter(v => !v.adminOnly);
}

function buildSidebar() {
  const nav = document.getElementById("sidebar-nav");
  nav.innerHTML = "";
  const authorized = getAuthorizedViews();

  let currentGroup = null;
  authorized.forEach((v) => {
    if (v.group && v.group !== currentGroup) {
      currentGroup = v.group;
      const label = document.createElement("div");
      label.className = "nav-group-label";
      label.textContent = v.group;
      nav.appendChild(label);
    }
    const item = document.createElement("div");
    item.className = "nav-item";
    item.dataset.view = v.id;
    item.innerHTML = `<span class="icon">${v.icon}</span><span>${v.label}</span>`;
    item.onclick = () => { window.location.hash = `#${v.id}`; };
    nav.appendChild(item);
  });
}

function navigateTo(viewId) {
  const user = AdminAPI.getCurrentUser();
  const isAdmin = user && user.role === "admin";
  const targetMeta = VIEWS.find(v => v.id === viewId);

  // 403 Access Restriction Check
  if (targetMeta && targetMeta.adminOnly && !isAdmin) {
    showAccessRestrictedScreen(targetMeta.label);
    return;
  }

  const authorized = getAuthorizedViews();
  const valid = authorized.some((v) => v.id === viewId) ? viewId : (authorized[0]?.id || "home");

  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.view === valid);
  });
  document.querySelectorAll(".view").forEach((el) => {
    el.classList.toggle("active", el.id === `view-${valid}`);
  });

  const meta = VIEWS.find((v) => v.id === valid);
  if (meta) {
    document.getElementById("topbar-title").textContent = meta.title;
    const crumb = document.getElementById("topbar-crumb");
    if (crumb) crumb.textContent = meta.group ? `M2 Admin / ${meta.group} / ${meta.label}` : `M2 Operations / ${meta.label}`;
  }

  const loader = VIEW_LOADERS[valid];
  if (loader) loader();
}

function showAccessRestrictedScreen(featureName = "this administrative feature") {
  const container = document.querySelector(".content");
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));

  let restrictedEl = document.getElementById("view-restricted-403");
  if (!restrictedEl) {
    restrictedEl = document.createElement("div");
    restrictedEl.id = "view-restricted-403";
    restrictedEl.className = "view active";
    container.appendChild(restrictedEl);
  }
  restrictedEl.classList.add("active");

  restrictedEl.innerHTML = `
    <div class="card" style="max-width:560px;margin:40px auto;padding:36px;text-align:center;">
      <div style="font-size:42px;margin-bottom:12px;">🛡️</div>
      <h2 style="color:#ef4444;margin:0 0 8px 0;font-size:22px;">403 — Access Restricted</h2>
      <p style="color:var(--muted);font-size:14px;line-height:1.6;margin:0 0 20px 0;">
        Your account role (<strong>Operations Engineer</strong>) is not authorized to access <strong>${escapeHtml(featureName)}</strong> or administrative settings.
      </p>
      <div style="background:#f8fafc;padding:16px;border-radius:12px;border:1.5px solid var(--border);margin-bottom:24px;text-align:left;">
        <div style="font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;margin-bottom:8px;">Authorized Operations Surfaces:</div>
        <div style="display:flex;flex-direction:column;gap:6px;font-size:13px;">
          <div>✅ <strong>Control Room Dashboard</strong> (Port 8005 / Live Route Tracking)</div>
          <div>✅ <strong>Interactive Delay Prediction</strong> (Live ML Inference &amp; Triage)</div>
        </div>
      </div>
      <div style="display:flex;justify-content:center;gap:12px;">
        <a href="/" class="btn btn-primary">Open Control Room ➔</a>
        <button class="btn btn-ghost" onclick="AdminAPI.logout()">Sign Out</button>
      </div>
    </div>
  `;
}

window.addEventListener("hashchange", () => {
  navigateTo(window.location.hash.replace("#", "") || "home");
});

// ---------------- Login & App States ----------------
function showLoginScreen() {
  document.getElementById("login-screen").style.display = "flex";
  document.getElementById("app").classList.remove("visible");
}

function showApp() {
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("app").classList.add("visible");

  const user = AdminAPI.getCurrentUser();
  if (user) {
    updateUserDisplay(user);
  }

  // Refresh profile from server
  AdminAPI.get("/me").then((meData) => {
    AdminAPI.setSession(AdminAPI.getToken(), meData);
    updateUserDisplay(meData);
    buildSidebar();
    const hash = window.location.hash.replace("#", "");
    navigateTo(hash || "home");
  }).catch(() => {
    buildSidebar();
    navigateTo(window.location.hash.replace("#", "") || "home");
  });

  refreshTopbarStatus();
  setInterval(refreshTopbarStatus, 30000);
}

function updateUserDisplay(user) {
  const nameEl = document.getElementById("current-username");
  const badgeEl = document.getElementById("current-role-badge");
  if (nameEl) nameEl.textContent = `👤 ${user.name || user.email || 'Officer'}`;

  const role = user.role || 'operations_engineer';
  if (badgeEl) {
    badgeEl.textContent = role === 'admin' ? 'Admin' : 'Ops Eng';
    badgeEl.className = `badge ${role}`;
  }

  // Update popover fields
  if (document.getElementById("popover-name")) document.getElementById("popover-name").textContent = user.name || 'Officer';
  if (document.getElementById("popover-email")) document.getElementById("popover-email").textContent = user.email || '';
  if (document.getElementById("popover-role")) {
    const rEl = document.getElementById("popover-role");
    rEl.textContent = user.role_display || (role === 'admin' ? 'Administrator' : 'Operations Engineer');
    rEl.className = `profile-role badge ${role}`;
  }
  if (document.getElementById("popover-last-login")) {
    document.getElementById("popover-last-login").textContent = `Last Login: ${user.last_login_at ? formatDate(user.last_login_at) : 'Active now'}`;
  }
}

async function refreshTopbarStatus() {
  try {
    const status = await AdminAPI.get("/health/status");
    const pills = document.getElementById("topbar-pills");
    if (!pills) return;
    pills.innerHTML = "";
    const items = [
      { label: "Supabase", ok: status.supabase.reachable },
      { label: "Hub", ok: status.hub.reachable },
    ];
    items.forEach((it) => {
      const pill = document.createElement("span");
      pill.className = `pill ${it.ok ? "ok" : "bad"}`;
      pill.innerHTML = `<span class="dot"></span>${it.label}`;
      pills.appendChild(pill);
    });
  } catch (_) { /* non-critical status pill update */ }
}

// ---------------- Event Listeners ----------------
document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;
  const errorBox = document.getElementById("login-error");
  errorBox.style.display = "none";

  const btn = document.getElementById("login-submit");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';

  try {
    const res = await AdminAPI.login(email, password);
    toast(`Welcome, ${res.officer.name}!`, "success");
    showApp();
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.style.display = "block";
  } finally {
    btn.disabled = false;
    btn.textContent = "Sign In";
  }
});

// Profile Popover toggle
const userBadgeBtn = document.getElementById("user-badge");
if (userBadgeBtn) {
  userBadgeBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const popover = document.getElementById("user-profile-popover");
    if (popover) popover.classList.toggle("visible");
  });
}

document.addEventListener("click", (e) => {
  const popover = document.getElementById("user-profile-popover");
  if (popover && !popover.contains(e.target) && e.target !== userBadgeBtn) {
    popover.classList.remove("visible");
  }
});

// Log out triggers
const popoverLogoutBtn = document.getElementById("popover-logout-btn");
if (popoverLogoutBtn) {
  popoverLogoutBtn.addEventListener("click", () => {
    AdminAPI.logout();
  });
}

const headerLogoutBtn = document.getElementById("header-logout-btn");
if (headerLogoutBtn) {
  headerLogoutBtn.addEventListener("click", () => {
    AdminAPI.logout();
  });
}

// ---------------- Boot & Query Params ----------------
(function boot() {
  // Support inheriting token from URL search parameter (e.g. from parent portal iframe)
  const params = new URLSearchParams(window.location.search);
  const tokenFromUrl = params.get("token");
  if (tokenFromUrl) {
    AdminAPI.setSession(tokenFromUrl, null);
    // clean url
    window.history.replaceState({}, document.title, window.location.pathname + window.location.hash);
  }

  if (AdminAPI.getToken()) {
    showApp();
  } else {
    showLoginScreen();
  }
})();
