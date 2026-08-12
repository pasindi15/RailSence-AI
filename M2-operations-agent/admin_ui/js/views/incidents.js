window.ViewIncidents = (function () {
  function render() {
    const container = document.getElementById("view-incidents");
    container.innerHTML = `
      <p class="section-title">Incident Review Queue</p>
      <p class="section-sub">Correct misclassified incidents and approve/reject submissions before they count as ground truth.</p>

      <div class="card">
        <div class="toolbar">
          <select id="iq-status-filter">
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="corrected">Corrected</option>
            <option value="">All</option>
          </select>
          <button class="btn btn-ghost btn-sm" id="iq-refresh">Refresh</button>
        </div>
        <div class="table-wrap"><table class="data-table">
          <thead><tr>
            <th>Received</th><th>Train</th><th>Station</th><th>Summary</th>
            <th>Classified As</th><th>Status</th><th></th>
          </tr></thead>
          <tbody id="iq-tbody"><tr><td colspan="7"><span class="spinner"></span></td></tr></tbody>
        </table></div>
      </div>
    `;
    document.getElementById("iq-status-filter").onchange = fetchRows;
    document.getElementById("iq-refresh").onclick = fetchRows;
  }

  async function fetchRows() {
    const tbody = document.getElementById("iq-tbody");
    tbody.innerHTML = `<tr><td colspan="7"><span class="spinner"></span></td></tr>`;
    const status = document.getElementById("iq-status-filter").value;
    try {
      const result = await AdminAPI.get(`/incidents?${status ? `status=${status}&` : ""}limit=100`);
      const rows = result.rows || [];
      if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="icon">✅</div>No incidents in this queue.<br><span style="font-size:11px;">New submissions appear here once your /incident-report handler is wired to insert into incident_reports (see admin_schema.sql).</span></div></td></tr>`;
        return;
      }
      tbody.innerHTML = rows.map((r) => `
        <tr>
          <td>${formatDate(r.received_at)}</td>
          <td>${escapeHtml(r.train_id)}</td>
          <td>${escapeHtml(r.station)}</td>
          <td style="max-width:280px;">${escapeHtml(r.summary || r.raw_text)}</td>
          <td><span class="badge none">${escapeHtml(r.classified_type)}</span></td>
          <td><span class="badge ${r.review_status || 'pending'}">${escapeHtml(r.review_status || 'pending')}</span></td>
          <td>
            <button class="btn btn-ghost btn-sm" onclick='ViewIncidents.correct(${JSON.stringify(r).replace(/'/g, "&#39;")})'>Correct</button>
            <button class="btn btn-success btn-sm" onclick="ViewIncidents.setStatus('${r.incident_id}','approved')">✓</button>
            <button class="btn btn-danger btn-sm" onclick="ViewIncidents.setStatus('${r.incident_id}','rejected')">✕</button>
          </td>
        </tr>
      `).join("");
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state">${escapeHtml(err.message)}</div></td></tr>`;
    }
  }

  function correct(row) {
    openModal("Correct Incident", `
      <div class="field">
        <label>Classified Type</label>
        <select id="iq-fld-type">
          ${["signal_fault","mechanical","weather","track_obstruction","staffing","other"].map((t) =>
            `<option value="${t}" ${row.classified_type === t ? "selected" : ""}>${t}</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label>Summary</label>
        <input id="iq-fld-summary" value="${escapeHtml(row.summary || "")}" />
      </div>
    `, async () => {
      try {
        await AdminAPI.post(`/incidents/${row.incident_id}/review`, {
          classified_type: document.getElementById("iq-fld-type").value,
          summary: document.getElementById("iq-fld-summary").value,
          review_status: "corrected",
        });
        toast("Incident corrected", "success");
        closeModal();
        fetchRows();
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  async function setStatus(incidentId, status) {
    try {
      await AdminAPI.post(`/incidents/${incidentId}/review`, { review_status: status });
      toast(`Marked ${status}`, "success");
      fetchRows();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function load() { render(); fetchRows(); }
  return { load, correct, setStatus };
})();
