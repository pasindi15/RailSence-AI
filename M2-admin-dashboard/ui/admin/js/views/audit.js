window.ViewAudit = (function () {
  function render() {
    const container = document.getElementById("view-audit");
    container.innerHTML = `
      <p class="section-title">Audit & Access Control</p>
      <p class="section-sub">Inspect the audit trail of every prediction, incident report, and Hub message this agent has processed.</p>

      <div class="grid grid-2" style="margin-bottom:18px;">
        <div class="card">
          <h3>Events by Type</h3>
          <p class="card-desc">Sampled from the last 1,000 audit rows.</p>
          <div id="audit-by-type"><span class="spinner"></span></div>
        </div>
        <div class="card">
          <h3>Admin Session</h3>
          <p class="card-desc">This dashboard's own login is a placeholder — swap it for the Hub's real JWT/auth system before submission.</p>
          <div style="margin-top:10px;">
            <div class="badge approved">Env-var admin login active</div>
          </div>
          <p class="muted" style="font-size:11.5px; margin-top:12px;">
            See <span class="mono">backend/admin_auth.py</span> for how to plug in the Security Agent's real auth once it's ready.
          </p>
        </div>
      </div>

      <div class="card">
        <div class="toolbar">
          <h3 class="mb-0">Audit Log</h3>
          <span class="spacer"></span>
          <span class="source-tag" id="audit-source-tag">…</span>
          <button class="btn btn-ghost btn-sm" id="audit-refresh">Refresh</button>
        </div>
        <div class="table-wrap"><table class="data-table">
          <thead><tr><th>Time</th><th>Intent / Event</th><th>Actor</th><th>Detail</th></tr></thead>
          <tbody id="audit-tbody"><tr><td colspan="4"><span class="spinner"></span></td></tr></tbody>
        </table></div>
      </div>
    `;
    document.getElementById("audit-refresh").onclick = loadEvents;
  }

  async function load() {
    render();
    await Promise.all([loadSummary(), loadEvents()]);
  }

  async function loadSummary() {
    const el = document.getElementById("audit-by-type");
    try {
      const data = await AdminAPI.get("/audit/summary");
      const entries = Object.entries(data.by_type);
      if (!entries.length) {
        el.innerHTML = `<div class="empty-state">No audit data yet.</div>`;
        return;
      }
      const max = Math.max(...entries.map(([, v]) => v));
      el.innerHTML = entries.map(([type, count]) => `
        <div class="bar-row">
          <div class="bar-label">${escapeHtml(type)}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${(count / max) * 100}%"></div></div>
          <div class="bar-value">${count}</div>
        </div>
      `).join("");
    } catch (err) {
      el.innerHTML = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
    }
  }

  async function loadEvents() {
    const tbody = document.getElementById("audit-tbody");
    tbody.innerHTML = `<tr><td colspan="4"><span class="spinner"></span></td></tr>`;
    try {
      const result = await AdminAPI.get("/audit/events?limit=100");
      const rows = result.rows || [];
      const tag = document.getElementById("audit-source-tag");
      tag.textContent = result.source;
      tag.className = `source-tag ${result.source === "supabase" ? "supabase" : "fallback"}`;

      if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="4"><div class="empty-state"><div class="icon">🗒️</div>No audit events yet.</div></td></tr>`;
        return;
      }
      tbody.innerHTML = rows.map((r) => `
        <tr>
          <td>${formatDate(r.created_at || r.timestamp)}</td>
          <td><span class="badge none">${escapeHtml(r.intent || r.event_type || r.action || "—")}</span></td>
          <td>${escapeHtml(r.actor || r.sender_agent || "—")}</td>
          <td class="mono" style="font-size:11px; max-width:360px; overflow-wrap:anywhere;">${escapeHtml(JSON.stringify(r.detail || r.payload || {}))}</td>
        </tr>
      `).join("");
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="4"><div class="empty-state">${escapeHtml(err.message)}</div></td></tr>`;
    }
  }

  return { load };
})();
