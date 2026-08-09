window.ViewHub = (function () {
  function render() {
    const container = document.getElementById("view-hub");
    container.innerHTML = `
      <p class="section-title">Hub & Event Control</p>
      <p class="section-sub">Check Hub connectivity, review recent events, and demo the delay_alert flow on demand.</p>

      <div class="grid grid-3" style="margin-bottom: 18px;">
        <div class="card stat-card"><div class="label">Hub Connection</div><div class="value" id="hub-conn-status">…</div></div>
        <div class="card stat-card">
          <div class="label">Alert Threshold (minutes)</div>
          <div style="display:flex; gap:8px; align-items:center; margin-top:6px;">
            <input id="hub-threshold-input" type="number" step="0.5" style="width:70px; padding:6px 8px; border:1.5px solid var(--border); border-radius:8px;" />
            <button class="btn btn-ghost btn-sm" id="hub-threshold-save">Save</button>
          </div>
        </div>
        <div class="card stat-card">
          <div class="label">Demo Trigger</div>
          <button class="btn btn-primary btn-sm" id="hub-test-alert-btn" style="margin-top:8px;">🚨 Fire Test delay_alert</button>
        </div>
      </div>

      <div class="card">
        <div class="toolbar"><h3 class="mb-0">Recent Events</h3><span class="spacer"></span><button class="btn btn-ghost btn-sm" id="hub-refresh">Refresh</button></div>
        <div class="table-wrap"><table class="data-table">
          <thead><tr><th>Time</th><th>Type</th><th>Route</th><th>Train</th><th>Delay (min)</th><th>Source</th></tr></thead>
          <tbody id="hub-events-tbody"><tr><td colspan="6"><span class="spinner"></span></td></tr></tbody>
        </table></div>
      </div>
    `;
    document.getElementById("hub-refresh").onclick = loadEvents;
    document.getElementById("hub-test-alert-btn").onclick = fireTestAlert;
    document.getElementById("hub-threshold-save").onclick = saveThreshold;
  }

  async function load() {
    render();
    await Promise.all([loadStatus(), loadEvents(), loadThreshold()]);
  }

  async function loadStatus() {
    const el = document.getElementById("hub-conn-status");
    try {
      const status = await AdminAPI.get("/hub/status");
      el.innerHTML = status.reachable
        ? `<span class="accent-success">● Reachable</span>`
        : `<span class="accent-danger">○ Unreachable</span>`;
      el.title = status.hub_base_url;
    } catch (err) {
      el.textContent = "Error";
    }
  }

  async function loadEvents() {
    const tbody = document.getElementById("hub-events-tbody");
    tbody.innerHTML = `<tr><td colspan="6"><span class="spinner"></span></td></tr>`;
    try {
      const result = await AdminAPI.get("/hub/events?limit=50");
      const rows = result.rows || [];
      if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="icon">📭</div>No events recorded yet.</div></td></tr>`;
        return;
      }
      tbody.innerHTML = rows.map((r) => `
        <tr>
          <td>${formatDate(r.created_at)}</td>
          <td><span class="badge none">${escapeHtml(r.event_type)}</span></td>
          <td>${escapeHtml(r.route)}</td>
          <td>${escapeHtml(r.train_id)}</td>
          <td>${escapeHtml(r.predicted_delay_minutes)}</td>
          <td class="muted" style="font-size:11px;">${escapeHtml(r.source || "—")}</td>
        </tr>
      `).join("");
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state">${escapeHtml(err.message)}</div></td></tr>`;
    }
  }

  async function loadThreshold() {
    try {
      const data = await AdminAPI.get("/hub/threshold");
      document.getElementById("hub-threshold-input").value = data.delay_alert_threshold_minutes;
    } catch (_) {}
  }

  async function saveThreshold() {
    const val = parseFloat(document.getElementById("hub-threshold-input").value);
    if (isNaN(val)) { toast("Enter a valid number", "error"); return; }
    try {
      await AdminAPI.put("/hub/threshold", { delay_alert_threshold_minutes: val });
      toast("Threshold updated", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function fireTestAlert() {
    const btn = document.getElementById("hub-test-alert-btn");
    btn.disabled = true;
    try {
      const result = await AdminAPI.post("/hub/test-alert");
      toast(`Test alert published to: ${result.published_to.join(", ") || "local log only"}`, "success");
      loadEvents();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      btn.disabled = false;
    }
  }

  return { load };
})();
