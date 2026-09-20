// Audit & Agent Communication Log — STRICTLY READ-ONLY.
//
// Reads real rows from audit_events (Supabase) or data/audit_log.jsonl when
// offline. Every row shown was written by main.py's _audit() when an agent
// message or an operator action actually happened; nothing here is sampled or
// synthesised. There are deliberately no edit or delete controls: the trail is
// tamper-evident, so the console can inspect and filter it but never change it.
window.ViewAudit = (function () {
  const PAGE_SIZE = 50;
  let offset = 0;
  let lastCount = 0;

  function filters() {
    return {
      agent: (document.getElementById("audit-agent")?.value || "").trim(),
      intent: (document.getElementById("audit-intent")?.value || "").trim(),
      date_from: document.getElementById("audit-from")?.value || "",
      date_to: document.getElementById("audit-to")?.value || "",
    };
  }

  function render() {
    const container = document.getElementById("view-audit");
    container.innerHTML = `
      <p class="section-title">Audit &amp; Agent Communication Log</p>
      <p class="section-sub">
        Every inter-agent message and operator action M2 has handled, straight from
        <span class="mono">audit_events</span>. Read-only by design — no row can be edited or removed from here.
      </p>

      <div id="audit-offline-banner"></div>

      <div class="grid grid-2" style="margin-bottom:18px;">
        <div class="card">
          <h3 style="margin-top:0;font-size:15px;">Messages by Intent</h3>
          <p class="card-desc">Distribution across the logged trail.</p>
          <div id="audit-by-intent" style="margin-top:12px;"><span class="spinner"></span></div>
        </div>
        <div class="card">
          <h3 style="margin-top:0;font-size:15px;">Messages by Sender Agent</h3>
          <p class="card-desc">Which agents have called into M2.</p>
          <div id="audit-by-agent" style="margin-top:12px;"><span class="spinner"></span></div>
        </div>
      </div>

      <div class="card" style="padding:0;overflow:hidden;">
        <div class="toolbar" style="padding:14px 18px;margin-bottom:0;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:8px;">
          <input id="audit-agent" placeholder="Agent (sender or receiver)…" style="min-width:190px;" />
          <input id="audit-intent" placeholder="Intent…" style="min-width:150px;" />
          <label class="muted" style="font-size:11.5px;">From <input id="audit-from" type="date" /></label>
          <label class="muted" style="font-size:11.5px;">To <input id="audit-to" type="date" /></label>
          <button class="btn btn-primary btn-sm" id="audit-apply">Apply</button>
          <button class="btn btn-ghost btn-sm" id="audit-clear">Clear</button>
          <span class="spacer"></span>
          <span class="source-tag" id="audit-source-tag">…</span>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Timestamp</th><th>Message ID</th><th>Intent</th>
                <th>Sender</th><th>Receiver</th><th>Outcome</th><th>Context</th>
              </tr>
            </thead>
            <tbody id="audit-tbody">
              <tr><td colspan="7" style="text-align:center;padding:30px;"><span class="spinner"></span></td></tr>
            </tbody>
          </table>
        </div>
        <div class="toolbar" style="padding:12px 18px;border-top:1px solid var(--border);">
          <button class="btn btn-ghost btn-sm" id="audit-prev">◀ Prev</button>
          <span class="muted" id="audit-page-info">—</span>
          <button class="btn btn-ghost btn-sm" id="audit-next">Next ▶</button>
          <span class="spacer"></span>
          <button class="btn btn-ghost btn-sm" id="audit-refresh">⟳ Refresh</button>
        </div>
      </div>
    `;

    document.getElementById("audit-apply").onclick = () => { offset = 0; loadEvents(); };
    document.getElementById("audit-clear").onclick = () => {
      ["audit-agent", "audit-intent", "audit-from", "audit-to"].forEach((id) => {
        document.getElementById(id).value = "";
      });
      offset = 0;
      load();
    };
    document.getElementById("audit-refresh").onclick = load;
    document.getElementById("audit-prev").onclick = () => {
      if (offset > 0) { offset = Math.max(0, offset - PAGE_SIZE); loadEvents(); }
    };
    document.getElementById("audit-next").onclick = () => {
      if (offset + PAGE_SIZE < lastCount) { offset += PAGE_SIZE; loadEvents(); }
    };
  }

  function bars(elementId, distribution, emptyText) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const entries = Object.entries(distribution || {}).sort((a, b) => b[1] - a[1]);
    if (!entries.length) {
      el.innerHTML = `<div class="empty-state" style="padding:15px;">${emptyText}</div>`;
      return;
    }
    const max = Math.max(...entries.map(([, v]) => v), 1);
    el.innerHTML = entries.map(([label, count]) => `
      <div class="bar-row">
        <div class="bar-label"><span class="badge action-tag">${escapeHtml(label)}</span></div>
        <div class="bar-track"><div class="bar-fill" style="width:${(count / max) * 100}%"></div></div>
        <div class="bar-value">${count}</div>
      </div>
    `).join("");
  }

  async function loadSummary() {
    try {
      const data = await AdminAPI.get("/audit/summary");
      bars("audit-by-intent", data.by_intent, "No agent messages recorded yet.");
      bars("audit-by-agent", data.by_agent, "No agent messages recorded yet.");
    } catch (err) {
      const message = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
      document.getElementById("audit-by-intent").innerHTML = message;
      document.getElementById("audit-by-agent").innerHTML = message;
    }
  }

  function showOfflineBanner(offline, source) {
    const el = document.getElementById("audit-offline-banner");
    if (!el) return;
    el.innerHTML = offline
      ? `<div class="card" style="border-left:4px solid var(--operations);margin-bottom:16px;padding:12px 16px;">
           <strong>Offline mode — showing local data.</strong>
           <span class="muted"> Supabase is unreachable; rows are read from
           <span class="mono">data/audit_log.jsonl</span> (source: ${escapeHtml(source)}).</span>
         </div>`
      : "";
  }

  async function loadEvents() {
    const tbody = document.getElementById("audit-tbody");
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:30px;"><span class="spinner"></span></td></tr>`;

    const f = filters();
    const params = new URLSearchParams({ limit: PAGE_SIZE, offset });
    Object.entries(f).forEach(([k, v]) => { if (v) params.set(k, v); });

    try {
      const result = await AdminAPI.get(`/audit/events?${params.toString()}`);
      const rows = result.rows || [];
      lastCount = result.count || rows.length;

      showOfflineBanner(result.offline, result.source);
      const tag = document.getElementById("audit-source-tag");
      if (tag) {
        tag.textContent = result.source;
        tag.className = `source-tag ${result.source === "supabase" ? "supabase" : "fallback"}`;
      }

      document.getElementById("audit-page-info").textContent = lastCount
        ? `${offset + 1}–${Math.min(offset + rows.length, lastCount)} of ${lastCount}`
        : "0 events";

      if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="icon">🛡️</div>
          No audit events match these filters.</div></td></tr>`;
        return;
      }

      tbody.innerHTML = rows.map((r) => {
        const outcome = String(r.outcome || "");
        let badge = "none";
        if (outcome.startsWith("created") || outcome === "success") badge = "approved";
        else if (outcome.startsWith("deleted") || outcome.includes("error")) badge = "rejected";
        else if (outcome.startsWith("updated")) badge = "corrected";

        const context = [
          r.route ? `route=${r.route}` : null,
          r.train_id ? `train=${r.train_id}` : null,
          (r.predicted_delay_minutes !== null && r.predicted_delay_minutes !== undefined)
            ? `delay=${r.predicted_delay_minutes}m` : null,
          r.model_version ? `model=${r.model_version}` : null,
          r.classified_type ? `type=${r.classified_type}` : null,
        ].filter(Boolean).join(" · ");

        return `
          <tr>
            <td style="font-size:12px;color:var(--muted);white-space:nowrap;">${formatDate(r.timestamp)}</td>
            <td class="mono" style="font-size:11px;">${escapeHtml(String(r.message_id || "—").slice(0, 12))}</td>
            <td><span class="badge action-tag">${escapeHtml(r.intent || "—")}</span></td>
            <td><strong>${escapeHtml(r.sender_agent || "—")}</strong></td>
            <td>${escapeHtml(r.receiver_agent || "—")}</td>
            <td><span class="badge ${badge}">${escapeHtml(outcome || "—")}</span></td>
            <td class="mono" style="font-size:11px;max-width:340px;overflow-wrap:anywhere;">${escapeHtml(context || "—")}</td>
          </tr>
        `;
      }).join("");
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state">${escapeHtml(err.message)}</div></td></tr>`;
    }
  }

  async function load() {
    if (!document.getElementById("audit-tbody")) render();
    await Promise.all([loadSummary(), loadEvents()]);
  }

  return { load: () => { render(); return load(); } };
})();
