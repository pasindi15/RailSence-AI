// Incident Management — one screen, full CRUD.
//
// Consolidates what used to be two surfaces: the Control Room's "Incident
// Triage & Staff Briefing" create modal and the admin console's "Incident
// Review Queue". Create runs the real NLP pipeline via POST /incident-report;
// list/update/delete go to GET|PATCH|DELETE /incidents, which read and write
// the actual incident_reports store (Supabase primary, local JSONL fallback).
// Nothing on this screen is client-side state — every action persists.
window.ViewIncidents = (function () {
  // Matches nlp/classify_incident.CATEGORIES, so a correction can only be set
  // to a label the classifier could itself have produced.
  const TYPES = ["signal_fault", "mechanical", "weather", "track_obstruction", "staffing", "other"];
  const PAGE_SIZE = 20;

  let offset = 0;
  let lastCount = 0;
  let incidentMap = null;
  let themeObserver = null;
  let stations = [];

  // Approve/Reject is an administrator capability (m2.incidents.review); the
  // server enforces it, this only hides buttons that would be refused.
  function canReview() {
    const user = AdminAPI.getCurrentUser();
    return !!user && (user.role === "admin" ||
      (Array.isArray(user.permissions) && user.permissions.includes("m2.incidents.review")));
  }

  // The incident CRUD routes live on the agent itself, not under /admin/api.
  async function agentFetch(path, options = {}) {
    const headers = options.headers || {};
    const token = AdminAPI.getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    if (options.body) headers["Content-Type"] = "application/json";

    let resp;
    try {
      resp = await fetch(path, { ...options, headers });
    } catch (_) {
      throw new Error("Unable to reach the M2 Operations service.");
    }
    let data = null;
    try { data = await resp.json(); } catch (_) { /* empty body */ }
    if (!resp.ok) {
      const detail = data && data.detail ? data.detail : resp.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  }

  function render() {
    const container = document.getElementById("view-incidents");
    container.innerHTML = `
      <p class="section-title">Incident Management</p>
      <p class="section-sub">
        Report, review, correct, and remove staff incidents. Submitted text is sanitised, classified and
        summarised by the NLP pipeline, then indexed so RAG can cite it as precedent.
      </p>

      <div id="inc-offline-banner"></div>

      <div class="card" style="margin-bottom:18px;">
        <div class="toolbar" style="margin-bottom:10px;">
          <div>
            <strong>Verified incident map</strong>
            <div class="muted" style="font-size:12px;">Incidents approved today (since 00:00 Sri Lanka time) · also shown in the Control Room and on the passenger portal · updates every 5 s</div>
          </div>
          <span class="spacer"></span>
          <span class="source-tag" id="inc-map-count">—</span>
        </div>
        <div id="inc-map" style="height:360px;"></div>
        <div class="muted" id="inc-map-unmapped" style="font-size:12px;margin-top:8px;"></div>
      </div>

      <div class="card" style="margin-bottom:18px;">
        <div class="toolbar" style="flex-wrap:wrap;gap:8px;">
          <input id="inc-search" placeholder="Search summary, train, station…" style="min-width:220px;" />
          <select id="inc-type-filter">
            <option value="">All classifications</option>
            ${TYPES.map((t) => `<option value="${t}">${t}</option>`).join("")}
          </select>
          <select id="inc-status-filter">
            <option value="">All statuses</option>
            <option value="pending">pending</option>
            <option value="corrected">corrected</option>
            <option value="approved">approved</option>
            <option value="verified">verified</option>
            <option value="rejected">rejected</option>
          </select>
          <button class="btn btn-ghost btn-sm" id="inc-apply">Apply</button>
          <span class="spacer"></span>
          <span class="source-tag" id="inc-source-tag">…</span>
          <button class="btn btn-primary btn-sm" id="inc-new-btn">+ Report Incident</button>
        </div>

        <div class="table-wrap"><table class="data-table">
          <thead><tr>
            <th>Received</th><th>Train</th><th>Station</th><th>Summary</th>
            <th>Classified As</th><th>NLP Method</th><th>Status</th><th></th>
          </tr></thead>
          <tbody id="inc-tbody"><tr><td colspan="8" style="text-align:center;padding:30px;"><span class="spinner"></span></td></tr></tbody>
        </table></div>

        <div class="toolbar" style="margin-top:12px;">
          <button class="btn btn-ghost btn-sm" id="inc-prev">◀ Prev</button>
          <span class="muted" id="inc-page-info">—</span>
          <button class="btn btn-ghost btn-sm" id="inc-next">Next ▶</button>
        </div>
      </div>
    `;

    document.getElementById("inc-apply").onclick = () => { offset = 0; fetchRows(); };
    document.getElementById("inc-new-btn").onclick = openCreateModal;
    document.getElementById("inc-prev").onclick = () => {
      if (offset > 0) { offset = Math.max(0, offset - PAGE_SIZE); fetchRows(); }
    };
    document.getElementById("inc-next").onclick = () => {
      if (offset + PAGE_SIZE < lastCount) { offset += PAGE_SIZE; fetchRows(); }
    };
  }

  function showOfflineBanner(offline, source) {
    const el = document.getElementById("inc-offline-banner");
    if (!el) return;
    el.innerHTML = offline
      ? `<div class="card" style="border-left:4px solid var(--operations);margin-bottom:16px;padding:12px 16px;">
           <strong>Offline mode — showing local data.</strong>
           <span class="muted"> Supabase is unreachable; incidents are read from and written to the local
           store (source: ${escapeHtml(source)}). They will need re-syncing once Supabase returns.</span>
         </div>`
      : "";
  }

  async function fetchRows() {
    const tbody = document.getElementById("inc-tbody");
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:30px;"><span class="spinner"></span></td></tr>`;

    const params = new URLSearchParams({ limit: PAGE_SIZE, offset });
    const search = document.getElementById("inc-search").value.trim();
    const type = document.getElementById("inc-type-filter").value;
    const status = document.getElementById("inc-status-filter").value;
    if (search) params.set("search", search);
    if (type) params.set("classified_type", type);
    if (status) params.set("review_status", status);

    try {
      const result = await agentFetch(`/incidents?${params.toString()}`);
      const rows = result.rows || [];
      lastCount = result.count || rows.length;

      showOfflineBanner(result.offline, result.source);
      const tag = document.getElementById("inc-source-tag");
      tag.textContent = result.source;
      tag.className = `source-tag ${result.source === "supabase" ? "supabase" : "fallback"}`;

      document.getElementById("inc-page-info").textContent = lastCount
        ? `${offset + 1}–${Math.min(offset + rows.length, lastCount)} of ${lastCount}`
        : "0 incidents";

      if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><div class="icon">📋</div>
          No incidents recorded yet. Use <strong>+ Report Incident</strong> to file one.</div></td></tr>`;
        return;
      }

      tbody.innerHTML = rows.map((r) => {
        const payload = encodeURIComponent(JSON.stringify(r));
        return `
        <tr>
          <td style="font-size:12px;color:var(--muted);white-space:nowrap;">${formatDate(r.received_at)}</td>
          <td class="mono">${escapeHtml(r.train_id)}</td>
          <td>${escapeHtml(r.station)}</td>
          <td style="max-width:300px;">${escapeHtml(r.summary || r.raw_text || "")}</td>
          <td><span class="badge none">${escapeHtml(r.classified_type || "—")}</span></td>
          <td><span class="muted" style="font-size:11.5px;">${escapeHtml(r.nlp_method || "—")}</span></td>
          <td><span class="badge ${escapeHtml(r.review_status || "pending")}">${escapeHtml(r.review_status || "pending")}</span></td>
          <td style="white-space:nowrap;">
            ${reviewButtons(r)}
            <button class="btn btn-ghost btn-sm" onclick="ViewIncidents.edit('${payload}')">Edit</button>
            <button class="btn btn-danger btn-sm" onclick="ViewIncidents.remove('${escapeHtml(r.incident_id)}')">Delete</button>
          </td>
        </tr>`;
      }).join("");
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state">${escapeHtml(err.message)}</div></td></tr>`;
    }
  }

  // ------------------------------------------------------------- CREATE
  function openCreateModal() {
    openModal("Report Operational Incident", `
      <p class="card-desc" style="margin-bottom:12px;">
        The raw text is sanitised, then classified and summarised by the NLP pipeline before it is stored.
      </p>
      <div class="field"><label>Station</label><select id="inc-fld-station">
        <option value="">— select a station —</option>
        ${stations.map((s) => `<option value="${escapeHtml(s.station)}">${escapeHtml(s.station)}</option>`).join("")}
      </select></div>
      <div class="field"><label>Train</label><input id="inc-fld-train" /></div>
      <div class="field">
        <label>Raw incident report</label>
        <textarea id="inc-fld-text" rows="4" placeholder="Describe what the field staff reported…"></textarea>
      </div>
    `, async () => {
      if (!trainPicker.validate()) {
        toast("Choose the train from the list.", "error");
        return;
      }
      const train_id = trainPicker.value;
      const station = document.getElementById("inc-fld-station").value.trim();
      const raw_text = document.getElementById("inc-fld-text").value.trim();
      if (!train_id || !station || raw_text.length < 5) {
        toast("Train, station and a report of at least 5 characters are required.", "error");
        return;
      }
      try {
        const created = await agentFetch("/incident-report", {
          method: "POST",
          body: JSON.stringify({ train_id, station, raw_text }),
        });
        toast(`Filed as ${created.classified_type} (${created.nlp_method})`, "success");
        closeModal();
        offset = 0;
        fetchRows();
      } catch (err) {
        toast(err.message, "error");
      }
    }, "File Incident");

    // Pick the train by name ("Podi Menike") instead of recalling its id.
    const stationEl = document.getElementById("inc-fld-station");
    const trainPicker = RailSenseTrainPicker.attach(document.getElementById("inc-fld-train"), {
      getStation: () => stationEl.value,
    });
    stationEl.addEventListener("change", () => trainPicker.refresh());
  }

  // ------------------------------------------------------------- UPDATE
  function edit(encoded) {
    let row;
    try { row = JSON.parse(decodeURIComponent(encoded)); } catch (_) { return; }

    openModal("Correct Incident", `
      <p class="card-desc" style="margin-bottom:12px;">
        Corrections are written back to the incident's stored row and the retrieval index, not just this table.
      </p>
      <div class="field">
        <label>Classified Type</label>
        <select id="inc-edit-type">
          ${TYPES.map((t) => `<option value="${t}" ${row.classified_type === t ? "selected" : ""}>${t}</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label>Summary</label>
        <textarea id="inc-edit-summary" rows="3">${escapeHtml(row.summary || "")}</textarea>
      </div>
      <div class="field">
        <label>Review Status</label>
        <select id="inc-edit-status">
          ${["corrected", "rejected", "pending"].map((s) =>
            `<option value="${s}" ${row.review_status === s ? "selected" : ""}>${s}</option>`).join("")}
        </select>
      </div>
      ${row.review_status === "verified" ? `<p class="muted" style="font-size:12px;margin:-4px 0 10px;">
        This incident is verified. Saving a correction takes it off the map until it is approved again.</p>` : ""}
      <div class="field">
        <label>Original report (read-only)</label>
        <textarea rows="3" readonly style="background:var(--surface-2);">${escapeHtml(row.raw_text || "")}</textarea>
      </div>
    `, async () => {
      const payload = {
        classified_type: document.getElementById("inc-edit-type").value,
        summary: document.getElementById("inc-edit-summary").value.trim(),
        review_status: document.getElementById("inc-edit-status").value,
      };
      if (payload.summary.length < 3) {
        toast("Summary must be at least 3 characters.", "error");
        return;
      }
      try {
        const result = await agentFetch(`/incidents/${encodeURIComponent(row.incident_id)}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        if (result.write_error) {
          // Reachable but rejected — not the same thing as offline mode.
          toast(`Database rejected the update: ${result.write_error}`, "error");
        } else {
          toast(result.offline ? "Saved to local store (offline)" : "Incident updated", "success");
        }
        closeModal();
        fetchRows();
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  // ------------------------------------------------------------- DELETE
  async function remove(incidentId) {
    if (!confirm(`Delete incident ${incidentId}?\n\nIts embedding is removed too, so RAG stops citing it. This cannot be undone.`)) return;
    try {
      const result = await agentFetch(`/incidents/${encodeURIComponent(incidentId)}`, { method: "DELETE" });
      toast(result.offline ? "Deleted from local store (offline)" : "Incident deleted", "success");
      fetchRows();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // ------------------------------------------------------------- REVIEW
  function reviewButtons(r) {
    if (!canReview()) return "";
    const id = escapeHtml(r.incident_id);
    const status = r.review_status || "pending";
    const approve = status !== "verified"
      ? `<button class="btn btn-primary btn-sm" onclick="ViewIncidents.review('${id}','approve')">Approve</button>` : "";
    const reject = status !== "rejected"
      ? `<button class="btn btn-danger btn-sm" onclick="ViewIncidents.review('${id}','reject')">Reject</button>` : "";
    return approve + " " + reject;
  }

  async function review(incidentId, action) {
    try {
      const result = await agentFetch(`/incidents/${encodeURIComponent(incidentId)}/${action}`, { method: "POST" });
      if (result.write_error) {
        toast(`Database rejected the review: ${result.write_error}`, "error");
      } else if (action === "approve") {
        toast(result.mapped
          ? `Verified — now on the incident map at ${result.station}`
          : `Verified, but "${result.station}" has no known map location, so it is not shown on the map`,
          result.mapped ? "success" : "error");
      } else {
        toast("Incident rejected — it will not appear on any map", "success");
      }
      fetchRows();
      if (incidentMap) incidentMap.refresh();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function loadStations() {
    try {
      const res = await agentFetch("/api/stations");
      stations = res.stations || [];
    } catch (_) { stations = []; }
  }

  function startMap() {
    if (incidentMap) { incidentMap.destroy(); incidentMap = null; }
    const el = document.getElementById("inc-map");
    if (!el || !window.RailSenseIncidentMap) return;
    const theme = () => document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
    incidentMap = RailSenseIncidentMap.create(el, {
      theme: theme(),
      scrollWheelZoom: false,
      onUpdate: (items, feed) => {
        const count = document.getElementById("inc-map-count");
        if (count) count.textContent = `${items.length} today`;
        const note = document.getElementById("inc-map-unmapped");
        if (note) note.textContent = feed.unmapped
          ? `${feed.unmapped} incident(s) approved today are at stations with no known map location and are not shown.` : "";
      },
    });
    if (!themeObserver) {
      themeObserver = new MutationObserver(() => incidentMap && incidentMap.setTheme(theme()));
      themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    }
  }

  function load() { render(); fetchRows(); loadStations(); startMap(); }
  return { load, edit, remove, review, refresh: fetchRows };
})();
