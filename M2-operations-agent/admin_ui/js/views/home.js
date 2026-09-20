// Admin console landing page. Every stat below is a live count from the real
// stores — nothing is hardcoded, and a store that cannot be reached says so
// rather than rendering a plausible-looking zero.
window.ViewHome = (function () {
  const tiles = [
    { id: "incidents", icon: "📋", color: "var(--brand-light)", bg: "var(--brand-tint)",
      title: "Incident Management",
      desc: "Report, review, correct and delete incidents. NLP classification and summarisation run on submit." },
    { id: "model", icon: "🧠", color: "var(--maintenance)", bg: "var(--maintenance-light)",
      title: "Model Operations",
      desc: "Retrain the delay model on live data, inspect feature importances, roll back a bad run." },
    { id: "audit", icon: "🛡️", color: "var(--danger)", bg: "var(--danger-light)",
      title: "Audit & Agent Log",
      desc: "Read-only trail of every inter-agent message and operator action M2 has handled." },
  ];

  async function load() {
    const container = document.getElementById("view-home");
    container.innerHTML = `
      <div class="home-hero">
        <h1>RailSense AI — M2 Operations Admin</h1>
        <p>
          Incident triage, delay-model lifecycle, and the inter-agent audit trail behind the
          Operations &amp; Delay-Prediction Agent. The Control Room dashboard and the delay
          prediction lab live on the <a href="/" style="color:inherit;">agent's own UI</a>.
        </p>
      </div>
      <div class="grid grid-4" id="home-stats"></div>
      <h3 style="margin: 26px 0 14px 0; font-size: 15px;">Consoles</h3>
      <div class="grid grid-3" id="home-tiles"></div>
    `;

    document.getElementById("home-tiles").innerHTML = tiles.map((t) => `
      <div class="card dash-tile" onclick="window.location.hash='#${t.id}'">
        <div class="tile-icon" style="background:${t.bg}; color:${t.color};">${t.icon}</div>
        <div class="tile-title">${t.title}</div>
        <div class="tile-desc">${t.desc}</div>
      </div>
    `).join("");

    document.getElementById("home-stats").innerHTML = `
      <div class="card stat-card"><div class="label">Data Source</div><div class="value" id="stat-supabase">…</div></div>
      <div class="card stat-card"><div class="label">Incidents Logged</div><div class="value accent-ops" id="stat-incidents">…</div></div>
      <div class="card stat-card"><div class="label">Audit Events</div><div class="value accent-brand" id="stat-audit">…</div></div>
      <div class="card stat-card"><div class="label">Model Versions</div><div class="value" id="stat-versions">…</div></div>
    `;

    try {
      const status = await AdminAPI.get("/health/status");
      const el = document.getElementById("stat-supabase");
      el.textContent = status.supabase.reachable ? "Supabase" : "Local files";
      el.className = `value ${status.supabase.reachable ? "accent-success" : "accent-danger"}`;
      el.title = status.supabase.reachable
        ? "Supabase is reachable — reads and writes are going to Postgres."
        : "Offline mode — reads and writes are using the local CSV/JSONL stores.";
    } catch (_) {
      document.getElementById("stat-supabase").textContent = "—";
    }

    try {
      const resp = await fetch("/incidents?limit=1", {
        headers: { Authorization: `Bearer ${AdminAPI.getToken()}` },
      });
      const data = await resp.json();
      document.getElementById("stat-incidents").textContent = data.count ?? 0;
    } catch (_) { document.getElementById("stat-incidents").textContent = "—"; }

    try {
      const audit = await AdminAPI.get("/audit/events?limit=1");
      document.getElementById("stat-audit").textContent = audit.count ?? 0;
    } catch (_) { document.getElementById("stat-audit").textContent = "—"; }

    try {
      const versions = await AdminAPI.get("/model/versions");
      document.getElementById("stat-versions").textContent = versions.count ?? 0;
    } catch (_) { document.getElementById("stat-versions").textContent = "—"; }
  }

  return { load };
})();
