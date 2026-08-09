window.ViewHealth = (function () {
  function render() {
    const container = document.getElementById("view-health");
    container.innerHTML = `
      <p class="section-title">System Health & Config</p>
      <p class="section-sub">See exactly which data source is powering each part of the system right now — live or fallback.</p>

      <div class="grid grid-4" id="health-pills" style="margin-bottom:20px;"></div>

      <div class="grid grid-2">
        <div class="card">
          <h3>Data Source Status</h3>
          <p class="card-desc">Which backend each dashboard card is currently reading from.</p>
          <div id="health-sources"><span class="spinner"></span></div>
        </div>
        <div class="card">
          <h3>Environment Configuration</h3>
          <p class="card-desc">Values are masked — this confirms presence, not the secret itself.</p>
          <div id="health-config"><span class="spinner"></span></div>
        </div>
      </div>
    `;
  }

  async function load() {
    render();
    try {
      const status = await AdminAPI.get("/health/status");
      const pillsEl = document.getElementById("health-pills");
      const items = [
        { label: "Supabase", ok: status.supabase.reachable, sub: status.supabase.configured ? "configured" : "not configured" },
        { label: "Upstash Redis", ok: status.upstash.configured, sub: status.upstash.configured ? "configured" : "not configured" },
        { label: "Agent Hub", ok: status.hub.reachable, sub: status.hub.base_url },
        { label: "Anthropic API", ok: status.anthropic.configured, sub: status.anthropic.configured ? "key set" : "no key" },
      ];
      pillsEl.innerHTML = items.map((it) => `
        <div class="card stat-card">
          <div class="label">${it.label}</div>
          <div class="value ${it.ok ? "accent-success" : "accent-danger"}">${it.ok ? "● Live" : "○ Fallback"}</div>
          <div class="muted" style="font-size:11px; margin-top:4px;">${escapeHtml(it.sub)}</div>
        </div>
      `).join("");
    } catch (err) {
      document.getElementById("health-pills").innerHTML = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
    }

    try {
      const sources = await AdminAPI.get("/health/data-sources");
      const el = document.getElementById("health-sources");
      el.innerHTML = Object.entries(sources).map(([key, val]) => `
        <div style="display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--border);">
          <span>${key}</span>
          <span class="source-tag ${val === "supabase" || val === "local_json" ? "supabase" : "fallback"}">${val}</span>
        </div>
      `).join("");
    } catch (err) {
      document.getElementById("health-sources").innerHTML = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
    }

    try {
      const config = await AdminAPI.get("/health/config");
      const el = document.getElementById("health-config");
      el.innerHTML = Object.entries(config).map(([key, val]) => `
        <div style="display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--border);">
          <span class="mono">${key}</span>
          <span class="mono muted">${escapeHtml(val)}</span>
        </div>
      `).join("");
    } catch (err) {
      document.getElementById("health-config").innerHTML = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
    }
  }

  return { load };
})();
