window.ViewData = (function () {
  let currentPage = 0;
  const pageSize = 25;

  function render() {
    const container = document.getElementById("view-data");
    container.innerHTML = `
      <p class="section-title">Data Management</p>
      <p class="section-sub">Browse, edit, and validate the operations_history dataset that feeds the delay model and RAG corpus.</p>

      <div class="card" style="margin-bottom:18px;">
        <div class="toolbar">
          <input id="dm-search-route" placeholder="Filter by route…" />
          <select id="dm-filter-incident">
            <option value="">All incident types</option>
            <option value="none">none</option>
            <option value="signal_fault">signal_fault</option>
            <option value="mechanical">mechanical</option>
            <option value="weather">weather</option>
            <option value="track_obstruction">track_obstruction</option>
            <option value="staffing">staffing</option>
            <option value="other">other</option>
          </select>
          <button class="btn btn-ghost btn-sm" id="dm-apply-filter">Apply</button>
          <span class="spacer"></span>
          <span class="source-tag" id="dm-source-tag">…</span>
          <button class="btn btn-ghost btn-sm" id="dm-quality-btn">Run Quality Check</button>
          <label class="btn btn-ghost btn-sm" style="cursor:pointer;">
            Import CSV
            <input type="file" id="dm-csv-input" accept=".csv" style="display:none;" />
          </label>
          <button class="btn btn-primary btn-sm" id="dm-add-btn">+ Add Record</button>
        </div>
        <div id="dm-quality-summary"></div>
        <div class="table-wrap"><table class="data-table" id="dm-table">
          <thead><tr>
            <th>record_id</th><th>route</th><th>station</th><th>train_id</th>
            <th>scheduled_time</th><th>weather</th><th>incident_type</th><th>delay_min</th><th></th>
          </tr></thead>
          <tbody id="dm-tbody"><tr><td colspan="9"><span class="spinner"></span></td></tr></tbody>
        </table></div>
        <div class="toolbar" style="margin-top:12px;">
          <button class="btn btn-ghost btn-sm" id="dm-prev">◀ Prev</button>
          <span class="muted" id="dm-page-info">Page 1</span>
          <button class="btn btn-ghost btn-sm" id="dm-next">Next ▶</button>
        </div>
      </div>
    `;

    document.getElementById("dm-apply-filter").onclick = () => { currentPage = 0; fetchRows(); };
    document.getElementById("dm-prev").onclick = () => { if (currentPage > 0) { currentPage--; fetchRows(); } };
    document.getElementById("dm-next").onclick = () => { currentPage++; fetchRows(); };
    document.getElementById("dm-add-btn").onclick = () => openEditModal(null);
    document.getElementById("dm-quality-btn").onclick = runQualityCheck;
    document.getElementById("dm-csv-input").addEventListener("change", handleCsvImport);
  }

  async function fetchRows() {
    const tbody = document.getElementById("dm-tbody");
    tbody.innerHTML = `<tr><td colspan="9"><span class="spinner"></span></td></tr>`;
    const route = document.getElementById("dm-search-route").value.trim();
    const incidentType = document.getElementById("dm-filter-incident").value;

    const params = new URLSearchParams({ limit: pageSize, offset: currentPage * pageSize });
    if (route) params.set("route", route);
    if (incidentType) params.set("incident_type", incidentType);

    try {
      const result = await AdminAPI.get(`/data/operations?${params.toString()}`);
      const rows = result.rows || [];
      const tag = document.getElementById("dm-source-tag");
      tag.textContent = result.source;
      tag.className = `source-tag ${result.source === "supabase" ? "supabase" : "fallback"}`;

      if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="9"><div class="empty-state"><div class="icon">🗂️</div>No records found.</div></td></tr>`;
      } else {
        tbody.innerHTML = rows.map((r) => `
          <tr>
            <td class="mono">${escapeHtml(r.record_id ?? "—")}</td>
            <td>${escapeHtml(r.route)}</td>
            <td>${escapeHtml(r.station)}</td>
            <td>${escapeHtml(r.train_id)}</td>
            <td>${escapeHtml(r.scheduled_time)}</td>
            <td>${escapeHtml(r.weather)}</td>
            <td><span class="badge none">${escapeHtml(r.incident_type ?? "none")}</span></td>
            <td>${escapeHtml(r.delay_minutes)}</td>
            <td>
              <button class="btn btn-ghost btn-sm" onclick='ViewData.editRow(${JSON.stringify(r).replace(/'/g, "&#39;")})'>Edit</button>
              <button class="btn btn-danger btn-sm" onclick="ViewData.deleteRow('${r.record_id}')">Del</button>
            </td>
          </tr>
        `).join("");
      }
      document.getElementById("dm-page-info").textContent =
        `Page ${currentPage + 1}${result.count ? ` of ${Math.ceil(result.count / pageSize)}` : ""}`;
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="9"><div class="empty-state">${escapeHtml(err.message)}</div></td></tr>`;
    }
  }

  function openEditModal(row) {
    const isEdit = !!row;
    const fields = ["route", "station", "train_id", "scheduled_time", "actual_time", "weather", "day_type", "incident_type", "incident_note", "delay_minutes"];
    openModal(`${isEdit ? "Edit" : "Add"} Operations Record`, `
      ${fields.map((f) => `
        <div class="field">
          <label>${f}</label>
          <input id="fld-${f}" value="${escapeHtml(row ? row[f] ?? "" : "")}" ${f === "delay_minutes" ? 'type="number" step="0.1"' : ""} />
        </div>
      `).join("")}
    `, async () => {
      const payload = {};
      fields.forEach((f) => {
        const v = document.getElementById(`fld-${f}`).value;
        if (v !== "") payload[f] = f === "delay_minutes" ? parseFloat(v) : v;
      });
      try {
        if (isEdit) {
          await AdminAPI.put(`/data/operations/${row.record_id}`, payload);
          toast("Record updated", "success");
        } else {
          if (payload.delay_minutes === undefined) payload.delay_minutes = 0;
          await AdminAPI.post(`/data/operations`, payload);
          toast("Record added", "success");
        }
        closeModal();
        fetchRows();
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  async function deleteRow(recordId) {
    if (!confirm(`Delete record ${recordId}? This cannot be undone.`)) return;
    try {
      await AdminAPI.del(`/data/operations/${recordId}`);
      toast("Record deleted", "success");
      fetchRows();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function handleCsvImport(e) {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      toast("Importing CSV…", "info");
      const result = await AdminAPI.postForm("/data/operations/import-csv", formData);
      toast(`Imported ${result.inserted} rows (${result.failed_count} failed)`, result.failed_count ? "error" : "success");
      fetchRows();
    } catch (err) {
      toast(err.message, "error");
    }
    e.target.value = "";
  }

  async function runQualityCheck() {
    const box = document.getElementById("dm-quality-summary");
    box.innerHTML = `<div class="muted" style="margin-bottom:10px;"><span class="spinner"></span> Running quality check…</div>`;
    try {
      const r = await AdminAPI.get("/data/quality-check");
      box.innerHTML = `
        <div class="grid grid-3" style="margin-bottom:14px;">
          <div class="card stat-card"><div class="label">Duplicates</div><div class="value ${r.duplicate_count ? 'accent-danger' : 'accent-success'}">${r.duplicate_count}</div></div>
          <div class="card stat-card"><div class="label">Missing Fields</div><div class="value ${r.missing_field_count ? 'accent-danger' : 'accent-success'}">${r.missing_field_count}</div></div>
          <div class="card stat-card"><div class="label">Out of Range Delays</div><div class="value ${r.out_of_range_count ? 'accent-danger' : 'accent-success'}">${r.out_of_range_count}</div></div>
        </div>
      `;
      toast(`Quality check complete — checked ${r.checked_rows} rows`, "success");
    } catch (err) {
      box.innerHTML = "";
      toast(err.message, "error");
    }
  }

  function load() { render(); fetchRows(); }
  return { load, editRow: openEditModal, deleteRow };
})();
