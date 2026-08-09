// App shell: login flow, sidebar nav, hash routing, topbar status pills.

const VIEWS = [
  { id: "home", label: "Home", icon: "🏠", group: null, title: "Home" },
  { id: "data", label: "Data Management", icon: "🗄️", group: "Dashboards", title: "Data Management" },
  { id: "incidents", label: "Incident Review Queue", icon: "📋", group: "Dashboards", title: "Incident Review Queue" },
  { id: "health", label: "System Health & Config", icon: "💻", group: "Dashboards", title: "System Health & Config" },
  { id: "model", label: "Model Operations", icon: "🧠", group: "Dashboards", title: "Model Operations" },
  { id: "hub", label: "Hub & Event Control", icon: "🔗", group: "Dashboards", title: "Hub & Event Control" },
  { id: "audit", label: "Audit & Access Control", icon: "🛡️", group: "Dashboards", title: "Audit & Access Control" },
];

const VIEW_LOADERS = {
  home: () => window.ViewHome && window.ViewHome.load(),
  data: () => window.ViewData && window.ViewData.load(),
  incidents: () => window.ViewIncidents && window.ViewIncidents.load(),
  health: () => window.ViewHealth && window.ViewHealth.load(),
  model: () => window.ViewModel && window.ViewModel.load(),
  hub: () => window.ViewHub && window.ViewHub.load(),
  audit: () => window.ViewAudit && window.ViewAudit.load(),
};

function buildSidebar() {
  const nav = document.getElementById("sidebar-nav");
  nav.innerHTML = "";
  let currentGroup = null;
  VIEWS.forEach((v) => {
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
  const valid = VIEWS.some((v) => v.id === viewId) ? viewId : "home";

  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.view === valid);
  });
  document.querySelectorAll(".view").forEach((el) => {
    el.classList.toggle("active", el.id === `view-${valid}`);
  });

  const meta = VIEWS.find((v) => v.id === valid);
  document.getElementById("topbar-title").textContent = meta.title;

  const loader = VIEW_LOADERS[valid];
  if (loader) loader();
}

window.addEventListener("hashchange", () => {
  navigateTo(window.location.hash.replace("#", "") || "home");
});

// ---------------- Login ----------------
function showLoginScreen() {
  document.getElementById("login-screen").style.display = "flex";
  document.getElementById("app").classList.remove("visible");
}

function showApp() {
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("app").classList.add("visible");
  buildSidebar();
  navigateTo(window.location.hash.replace("#", "") || "home");
  refreshTopbarStatus();
  setInterval(refreshTopbarStatus, 30000);

  AdminAPI.get("/me").then((me) => {
    document.getElementById("current-username").textContent = me.username;
  }).catch(() => {});
}

async function refreshTopbarStatus() {
  try {
    const status = await AdminAPI.get("/health/status");
    const pills = document.getElementById("topbar-pills");
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
  } catch (_) { /* silent — non-critical UI element */ }
}

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  const errorBox = document.getElementById("login-error");
  errorBox.style.display = "none";

  const btn = document.getElementById("login-submit");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';

  try {
    await AdminAPI.login(username, password);
    showApp();
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.style.display = "block";
  } finally {
    btn.disabled = false;
    btn.textContent = "Sign in";
  }
});

document.getElementById("logout-link").addEventListener("click", () => {
  AdminAPI.clearToken();
  showLoginScreen();
});

// ---------------- Boot ----------------
(function boot() {
  if (AdminAPI.getToken()) {
    showApp();
  } else {
    showLoginScreen();
  }
})();
