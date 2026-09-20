// Security & Operations Audit Trail View
window.ViewAudit = (function () {
  let currentActionFilter = "";

  function render() {
    const container = document.getElementById("view-audit");
    container.innerHTML = `
      <div style="margin-bottom:18px;">
        <p class="section-title" style="font-size:20px;font-weight:700;margin:0 0 4px 0;">Security &amp; Access Audit Logs</p>
        <p class="section-sub" style="color:var(--muted);font-size:13px;margin:0;">Immutable audit trail of authentication events, officer modifications, role reassignments, and security incidents.</p>
      </div>

      <div class="grid grid-2" style="margin-bottom:18px;">
        <div class="card">
          <h3 style="margin-top:0;font-size:15px;">Security Events by Action</h3>
          <p class="card-desc" style="font-size:12px;color:var(--muted);">Distribution of audited security actions</p>
          <div id="audit-by-type" style="margin-top:12px;"><span class="spinner"></span></div>
        </div>
        <div class="card">
          <h3 style="margin-top:0;font-size:15px;">Active RBAC Session</h3>
          <p class="card-desc" style="font-size:12px;color:var(--muted);">Multi-user officer authentication is enforced via PyJWT &amp; bcrypt.</p>
          <div style="margin-top:12px;">
            <div class="badge approved" style="padding:4px 10px;font-size:12px;">🔒 Multi-User RBAC Active</div>
          </div>
          <p class="muted" style="font-size:12px; margin-top:12px;line-height:1.5;">
            Every officer authentication attempt, role change, password reset, and access violation is permanently recorded in the database.
          </p>
        </div>
      </div>

      <!-- Security Audit Log Table -->
      <div class="card" style="padding:0;overflow:hidden;">
        <div class="toolbar" style="padding:14px 18px;margin-bottom:0;border-bottom:1px solid var(--border);">
          <h3 class="mb-0" style="font-size:15px;">Security Audit Stream</h3>
          <select id="audit-action-filter" style="margin-left:14px;">
            <option value="">All Actions</option>
            <option value="LOGIN">LOGIN</option>
            <option value="LOGOUT">LOGOUT</option>
            <option value="OFFICER_CREATED">OFFICER_CREATED</option>
            <option value="ROLE_CHANGED">ROLE_CHANGED</option>
            <option value="OFFICER_DEACTIVATED">OFFICER_DEACTIVATED</option>
            <option value="PASSWORD_RESET">PASSWORD_RESET</option>
            <option value="UNAUTHORIZED_ACCESS_ATTEMPT">UNAUTHORIZED_ACCESS_ATTEMPT</option>
          </select>
          <span class="spacer"></span>
          <span class="source-tag" id="audit-source-tag">…</span>
          <button class="btn btn-ghost btn-sm" id="audit-refresh">⟳ Refresh</button>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Security Action</th>
                <th>Actor (Officer)</th>
                <th>Target Officer</th>
                <th>Audit Details</th>
              </tr>
            </thead>
            <tbody id="audit-tbody">
              <tr><td colspan="5" style="text-align:center;padding:30px;"><span class="spinner"></span></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    `;

    document.getElementById("audit-refresh").onclick = loadEvents;
    const filterEl = document.getElementById("audit-action-filter");
    filterEl.onchange = () => {
      currentActionFilter = filterEl.value;
      loadEvents();
    };
  }

  async function load() {
    render();
    await Promise.all([loadSummary(), loadEvents()]);
  }

  async function loadSummary() {
    const el = document.getElementById("audit-by-type");
    try {
      const data = await AdminAPI.get("/officers/audit?limit=200");
      const rows = data.rows || [];
      const byAction = {};
      rows.forEach(r => {
        const a = r.action || "UNKNOWN";
        byAction[a] = (byAction[a] || 0) + 1;
      });

      const entries = Object.entries(byAction);
      if (!entries.length) {
        el.innerHTML = `<div class="empty-state" style="padding:15px;">No security actions recorded yet.</div>`;
        return;
      }
      const max = Math.max(...entries.map(([, v]) => v), 1);
      el.innerHTML = entries.map(([act, count]) => `
        <div class="bar-row">
          <div class="bar-label"><span class="badge action-tag">${escapeHtml(act)}</span></div>
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
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:30px;"><span class="spinner"></span></td></tr>`;
    try {
      const query = currentActionFilter ? `&action=${encodeURIComponent(currentActionFilter)}` : "";
      const result = await AdminAPI.get(`/officers/audit?limit=100${query}`);
      const rows = result.rows || [];
      const tag = document.getElementById("audit-source-tag");
      if (tag) {
        tag.textContent = result.source;
        tag.className = `source-tag ${result.source === "supabase" ? "supabase" : "fallback"}`;
      }

      if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><div class="icon">🛡️</div>No security audit events recorded.</div></td></tr>`;
        return;
      }

      tbody.innerHTML = rows.map((r) => {
        let badgeClass = "none";
        const act = (r.action || "").toUpperCase();
        if (act === "LOGIN") badgeClass = "approved";
        else if (act === "LOGOUT") badgeClass = "pending";
        else if (act.includes("DEACTIVATED") || act.includes("UNAUTHORIZED")) badgeClass = "rejected";
        else if (act.includes("ROLE") || act.includes("CREATED")) badgeClass = "corrected";

        const actorDisplay = r.actor_name
          ? `${escapeHtml(r.actor_name)} <small class="muted">(${escapeHtml(r.actor_role || '')})</small>`
          : (r.actor_email || "System");

        return `
          <tr>
            <td style="font-size:12px;color:var(--muted);white-space:nowrap;">${formatDate(r.timestamp)}</td>
            <td><span class="badge ${badgeClass} action-tag">${escapeHtml(r.action || "—")}</span></td>
            <td><strong>${actorDisplay}</strong></td>
            <td>${r.target_officer_email ? `<span class="mono">${escapeHtml(r.target_officer_email)}</span>` : '<span class="muted">—</span>'}</td>
            <td class="mono" style="font-size:11px; max-width:360px; overflow-wrap:anywhere;">${escapeHtml(JSON.stringify(r.details || {}))}</td>
          </tr>
        `;
      }).join("");
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state">${escapeHtml(err.message)}</div></td></tr>`;
    }
  }

  return { load };
})();
