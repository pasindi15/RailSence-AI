window.ViewHome = (function () {
  const tiles = [
    { id: "data", icon: "🗄️", color: "var(--operations)", bg: "var(--operations-light)",
      title: "Data Management", desc: "Browse, edit, import, and quality-check the operations_history dataset." },
    { id: "incidents", icon: "📋", color: "var(--brand)", bg: "var(--brand-light)",
      title: "Incident Review Queue", desc: "Review, correct, and approve incident reports submitted by staff." },
    { id: "health", icon: "💻", color: "var(--security)", bg: "var(--security-light)",
      title: "System Health & Config", desc: "See which data sources are live vs. falling back, right now." },
    { id: "model", icon: "🧠", color: "var(--maintenance)", bg: "var(--maintenance-light)",
      title: "Model Operations", desc: "Retrain the delay model, inspect feature importances, roll back versions." },
    { id: "hub", icon: "🔗", color: "var(--passenger)", bg: "#e0f4ff",
      title: "Hub & Event Control", desc: "Check Hub connectivity, view events, trigger a test delay_alert." },
    { id: "audit", icon: "🛡️", color: "#b91c1c", bg: "var(--danger-light)",
      title: "Audit & Access Control", desc: "Inspect the audit trail and see which inputs were rejected." },
  ];

  async function load() {
    const container = document.getElementById("view-home");
    container.innerHTML = `
      <div class="home-hero">
        <h1>RailSense AI — Operations Admin</h1>
        <p>Manage the data, models, incidents, and integrations behind the Operations &amp; Delay-Prediction Agent from one place.</p>
      </div>
      <div class="grid grid-4" id="home-stats"></div>
      <h3 style="margin: 26px 0 14px 0; font-size: 15px;">Dashboards</h3>
      <div class="grid grid-3" id="home-tiles"></div>
    `;

    const tileGrid = document.getElementById("home-tiles");
    tileGrid.innerHTML = tiles.map((t) => `
      <div class="card dash-tile" onclick="window.location.hash='#${t.id}'">
        <div class="tile-icon" style="background:${t.bg}; color:${t.color};">${t.icon}</div>
        <div class="tile-title">${t.title}</div>
        <div class="tile-desc">${t.desc}</div>
      </div>
    `).join("");

    const statsGrid = document.getElementById("home-stats");
    statsGrid.innerHTML = `
      <div class="card stat-card"><div class="label">Supabase</div><div class="value" id="stat-supabase">…</div></div>
      <div class="card stat-card"><div class="label">Hub</div><div class="value" id="stat-hub">…</div></div>
      <div class="card stat-card"><div class="label">Pending Incidents</div><div class="value accent-ops" id="stat-incidents">…</div></div>
      <div class="card stat-card"><div class="label">Recent Audit Events</div><div class="value accent-brand" id="stat-audit">…</div></div>
    `;

    try {
      const status = await AdminAPI.get("/health/status");
      document.getElementById("stat-supabase").textContent = status.supabase.reachable ? "Online" : "Offline";
      document.getElementById("stat-hub").textContent = status.hub.reachable ? "Online" : "Offline";
    } catch (_) {}

    try {
      const incidents = await AdminAPI.get("/incidents?status=pending&limit=1");
      document.getElementById("stat-incidents").textContent = incidents.count ?? incidents.rows.length;
    } catch (_) { document.getElementById("stat-incidents").textContent = "—"; }

    try {
      const audit = await AdminAPI.get("/audit/events?limit=1");
      document.getElementById("stat-audit").textContent = audit.count ?? audit.rows.length;
    } catch (_) { document.getElementById("stat-audit").textContent = "—"; }
  }

  return { load };
})();
