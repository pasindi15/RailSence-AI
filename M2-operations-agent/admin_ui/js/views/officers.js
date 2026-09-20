// Officers & Access Management View (Admin Only)
window.ViewOfficers = (function () {
  let allOfficers = [];
  let currentSearch = "";
  let currentRoleFilter = "";
  let currentStatusFilter = "";

  function render() {
    const container = document.getElementById("view-officers");
    container.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:18px;">
        <div>
          <p class="section-title" style="font-size:20px;font-weight:700;margin:0 0 4px 0;">Officers &amp; Access Management</p>
          <p class="section-sub" style="color:var(--muted);font-size:13px;margin:0;">Provision officer accounts, assign role-based permissions, and manage operational credentials.</p>
        </div>
        <button class="btn btn-primary" id="btn-add-officer">
          <span>➕</span> Add Officer
        </button>
      </div>

      <!-- KPI Overview Cards -->
      <div class="grid grid-4" style="margin-bottom:20px;display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:14px;">
        <div class="card" style="padding:16px;">
          <div class="muted" style="font-size:11.5px;font-weight:600;text-transform:uppercase;">Total Officers</div>
          <div style="font-size:26px;font-weight:800;color:var(--ink);margin:6px 0;" id="kpi-total-officers">…</div>
          <div class="muted" style="font-size:11px;">Registered in system</div>
        </div>
        <div class="card" style="padding:16px;">
          <div class="muted" style="font-size:11.5px;font-weight:600;text-transform:uppercase;">Active Admins</div>
          <div style="font-size:26px;font-weight:800;color:var(--maintenance);margin:6px 0;" id="kpi-admin-count">…</div>
          <div class="muted" style="font-size:11px;">Full system control</div>
        </div>
        <div class="card" style="padding:16px;">
          <div class="muted" style="font-size:11.5px;font-weight:600;text-transform:uppercase;">Operations Engineers</div>
          <div style="font-size:26px;font-weight:800;color:var(--passenger);margin:6px 0;" id="kpi-ops-count">…</div>
          <div class="muted" style="font-size:11px;">Control room &amp; prediction</div>
        </div>
        <div class="card" style="padding:16px;">
          <div class="muted" style="font-size:11.5px;font-weight:600;text-transform:uppercase;">Inactive / Suspended</div>
          <div style="font-size:26px;font-weight:800;color:var(--danger);margin:6px 0;" id="kpi-inactive-count">…</div>
          <div class="muted" style="font-size:11px;">Access revoked</div>
        </div>
      </div>

      <!-- Toolbar -->
      <div class="card" style="margin-bottom:18px;padding:14px 18px;">
        <div class="toolbar" style="margin-bottom:0;">
          <input type="text" id="officer-search" placeholder="Search by name or email…" style="width:260px;" />
          <select id="filter-officer-role">
            <option value="">All Roles</option>
            <option value="admin">Administrator</option>
            <option value="operations_engineer">Operations Engineer</option>
          </select>
          <select id="filter-officer-status">
            <option value="">All Statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
          <span class="spacer"></span>
          <span class="source-tag" id="officer-source-tag">…</span>
          <button class="btn btn-ghost btn-sm" id="officers-refresh-btn">⟳ Refresh</button>
        </div>
      </div>

      <!-- Officers Table -->
      <div class="card" style="padding:0;overflow:hidden;">
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Officer</th>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last Active</th>
                <th>Created</th>
                <th style="text-align:right;">Actions</th>
              </tr>
            </thead>
            <tbody id="officers-tbody">
              <tr><td colspan="7" style="text-align:center;padding:30px;"><span class="spinner"></span></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    `;

    document.getElementById("btn-add-officer").onclick = openAddOfficerModal;
    document.getElementById("officers-refresh-btn").onclick = loadOfficers;

    const searchInput = document.getElementById("officer-search");
    searchInput.oninput = () => {
      currentSearch = searchInput.value.trim();
      renderTable();
    };

    const roleFilter = document.getElementById("filter-officer-role");
    roleFilter.onchange = () => {
      currentRoleFilter = roleFilter.value;
      renderTable();
    };

    const statusFilter = document.getElementById("filter-officer-status");
    statusFilter.onchange = () => {
      currentStatusFilter = statusFilter.value;
      renderTable();
    };
  }

  async function load() {
    render();
    await loadOfficers();
  }

  async function loadOfficers() {
    const tbody = document.getElementById("officers-tbody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:30px;"><span class="spinner"></span></td></tr>`;

    try {
      const data = await AdminAPI.get("/officers?limit=100");
      allOfficers = data.officers || [];
      const tag = document.getElementById("officer-source-tag");
      if (tag) {
        tag.textContent = data.source;
        tag.className = `source-tag ${data.source === "supabase" ? "supabase" : "fallback"}`;
      }
      updateKPIs();
      renderTable();
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state">${escapeHtml(err.message)}</div></td></tr>`;
      toast(err.message, "error");
    }
  }

  function updateKPIs() {
    const total = allOfficers.length;
    const admins = allOfficers.filter(o => o.role === "admin" && o.status === "active").length;
    const ops = allOfficers.filter(o => o.role === "operations_engineer" && o.status === "active").length;
    const inactive = allOfficers.filter(o => o.status === "inactive").length;

    if (document.getElementById("kpi-total-officers")) document.getElementById("kpi-total-officers").textContent = total;
    if (document.getElementById("kpi-admin-count")) document.getElementById("kpi-admin-count").textContent = admins;
    if (document.getElementById("kpi-ops-count")) document.getElementById("kpi-ops-count").textContent = ops;
    if (document.getElementById("kpi-inactive-count")) document.getElementById("kpi-inactive-count").textContent = inactive;
  }

  function renderTable() {
    const tbody = document.getElementById("officers-tbody");
    if (!tbody) return;

    let filtered = allOfficers;
    if (currentRoleFilter) {
      filtered = filtered.filter(o => o.role === currentRoleFilter);
    }
    if (currentStatusFilter) {
      filtered = filtered.filter(o => o.status === currentStatusFilter);
    }
    if (currentSearch) {
      const q = currentSearch.toLowerCase();
      filtered = filtered.filter(o =>
        (o.full_name || "").toLowerCase().includes(q) ||
        (o.email || "").toLowerCase().includes(q)
      );
    }

    if (!filtered.length) {
      tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="icon">👥</div>No officers match the current filter.</div></td></tr>`;
      return;
    }

    tbody.innerHTML = filtered.map(o => {
      const isSelf = o.email === (AdminAPI.getCurrentUser()?.email);
      const roleBadge = o.role === "admin"
        ? `<span class="badge admin">Admin</span>`
        : `<span class="badge operations_engineer">Operations Engineer</span>`;

      const statusBadge = o.status === "active"
        ? `<span class="badge active">Active</span>`
        : `<span class="badge inactive">Inactive</span>`;

      const toggleAction = o.status === "active"
        ? `<button class="btn-action danger" onclick="window.ViewOfficers.confirmDeactivate('${o.id}', '${escapeHtml(o.full_name)}')">Deactivate</button>`
        : `<button class="btn-action success" onclick="window.ViewOfficers.activateOfficer('${o.id}')">Activate</button>`;

      return `
        <tr>
          <td>
            <strong>${escapeHtml(o.full_name)}</strong>
            ${isSelf ? '<span class="muted" style="font-size:10.5px;margin-left:4px;">(You)</span>' : ''}
          </td>
          <td class="mono" style="font-size:12px;">${escapeHtml(o.email)}</td>
          <td>${roleBadge}</td>
          <td>${statusBadge}</td>
          <td style="font-size:12px;color:var(--muted);">${o.last_login_at ? formatDate(o.last_login_at) : 'Never'}</td>
          <td style="font-size:12px;color:var(--muted);">${formatDate(o.created_at)}</td>
          <td style="text-align:right;">
            <div class="table-actions" style="justify-content:flex-end;">
              <button class="btn-action" onclick="window.ViewOfficers.openEditModal('${o.id}')">Edit</button>
              <button class="btn-action" onclick="window.ViewOfficers.openRoleModal('${o.id}')">Role</button>
              <button class="btn-action" onclick="window.ViewOfficers.openResetPasswordModal('${o.id}')">Reset PWD</button>
              ${toggleAction}
            </div>
          </td>
        </tr>
      `;
    }).join("");
  }

  // ---------------- Add Officer Modal ----------------
  function openAddOfficerModal() {
    Modal.open({
      title: "Add New Officer",
      html: `
        <form id="add-officer-form">
          <div class="field">
            <label>Full Name</label>
            <input id="add-officer-name" type="text" required placeholder="e.g. Test Officer" />
          </div>
          <div class="field">
            <label>Email Address</label>
            <input id="add-officer-email" type="email" required placeholder="test@railsense.lk" />
          </div>
          <div class="field">
            <label>Temporary Password</label>
            <input id="add-officer-password" type="password" required minlength="6" placeholder="Minimum 6 characters" />
          </div>
          <div class="field">
            <label>Role</label>
            <select id="add-officer-role" style="width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:10px;">
              <option value="operations_engineer">Operations Engineer</option>
              <option value="admin">Administrator</option>
            </select>
          </div>
          <div class="field">
            <label>Account Status</label>
            <select id="add-officer-status" style="width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:10px;">
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>
          <div class="modal-actions">
            <button type="button" class="btn btn-ghost" onclick="Modal.close()">Cancel</button>
            <button type="submit" class="btn btn-primary" id="btn-submit-add-officer">Create Officer</button>
          </div>
        </form>
      `,
    });

    document.getElementById("add-officer-form").onsubmit = async (e) => {
      e.preventDefault();
      const btn = document.getElementById("btn-submit-add-officer");
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner"></span>`;

      const payload = {
        full_name: document.getElementById("add-officer-name").value.trim(),
        email: document.getElementById("add-officer-email").value.trim(),
        password: document.getElementById("add-officer-password").value,
        role: document.getElementById("add-officer-role").value,
        status: document.getElementById("add-officer-status").value,
      };

      try {
        await AdminAPI.post("/officers", payload);
        toast(`Officer ${payload.full_name} created successfully!`, "success");
        Modal.close();
        await loadOfficers();
      } catch (err) {
        toast(err.message, "error");
        btn.disabled = false;
        btn.textContent = "Create Officer";
      }
    };
  }

  // ---------------- Edit Officer Modal ----------------
  function openEditModal(officerId) {
    const officer = allOfficers.find(o => String(o.id) === String(officerId));
    if (!officer) return;

    Modal.open({
      title: `Edit Officer: ${escapeHtml(officer.full_name)}`,
      html: `
        <form id="edit-officer-form">
          <div class="field">
            <label>Full Name</label>
            <input id="edit-officer-name" type="text" required value="${escapeHtml(officer.full_name)}" />
          </div>
          <div class="field">
            <label>Email Address</label>
            <input id="edit-officer-email" type="email" required value="${escapeHtml(officer.email)}" />
          </div>
          <div class="field">
            <label>Role</label>
            <select id="edit-officer-role" style="width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:10px;">
              <option value="operations_engineer" ${officer.role === 'operations_engineer' ? 'selected' : ''}>Operations Engineer</option>
              <option value="admin" ${officer.role === 'admin' ? 'selected' : ''}>Administrator</option>
            </select>
          </div>
          <div class="field">
            <label>Status</label>
            <select id="edit-officer-status" style="width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:10px;">
              <option value="active" ${officer.status === 'active' ? 'selected' : ''}>Active</option>
              <option value="inactive" ${officer.status === 'inactive' ? 'selected' : ''}>Inactive</option>
            </select>
          </div>
          <div class="modal-actions">
            <button type="button" class="btn btn-ghost" onclick="Modal.close()">Cancel</button>
            <button type="submit" class="btn btn-primary" id="btn-submit-edit">Save Changes</button>
          </div>
        </form>
      `,
    });

    document.getElementById("edit-officer-form").onsubmit = async (e) => {
      e.preventDefault();
      const payload = {
        full_name: document.getElementById("edit-officer-name").value.trim(),
        email: document.getElementById("edit-officer-email").value.trim(),
        role: document.getElementById("edit-officer-role").value,
        status: document.getElementById("edit-officer-status").value,
      };

      try {
        await AdminAPI.put(`/officers/${officerId}`, payload);
        toast("Officer updated successfully.", "success");
        Modal.close();
        await loadOfficers();
      } catch (err) {
        toast(err.message, "error");
      }
    };
  }

  // ---------------- Role Change Modal ----------------
  function openRoleModal(officerId) {
    const officer = allOfficers.find(o => String(o.id) === String(officerId));
    if (!officer) return;

    Modal.open({
      title: `Change Officer Role`,
      html: `
        <p style="color:var(--muted);font-size:13px;margin-bottom:14px;">
          Changing the role for <strong>${escapeHtml(officer.full_name)}</strong> will instantly modify their permissions across all RailSense operations surfaces.
        </p>
        <form id="role-change-form">
          <div class="field">
            <label>Assigned Role</label>
            <select id="role-select" style="width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:10px;">
              <option value="operations_engineer" ${officer.role === 'operations_engineer' ? 'selected' : ''}>Operations Engineer (Control Room &amp; Prediction)</option>
              <option value="admin" ${officer.role === 'admin' ? 'selected' : ''}>Administrator (Full Console &amp; Officers Access)</option>
            </select>
          </div>
          <div class="modal-actions">
            <button type="button" class="btn btn-ghost" onclick="Modal.close()">Cancel</button>
            <button type="submit" class="btn btn-primary">Update Role</button>
          </div>
        </form>
      `,
    });

    document.getElementById("role-change-form").onsubmit = async (e) => {
      e.preventDefault();
      const newRole = document.getElementById("role-select").value;
      try {
        await AdminAPI.put(`/officers/${officerId}`, { role: newRole });
        toast(`Role changed to ${newRole === 'admin' ? 'Administrator' : 'Operations Engineer'}.`, "success");
        Modal.close();
        await loadOfficers();
      } catch (err) {
        toast(err.message, "error");
      }
    };
  }

  // ---------------- Reset Password Modal ----------------
  function openResetPasswordModal(officerId) {
    const officer = allOfficers.find(o => String(o.id) === String(officerId));
    if (!officer) return;

    Modal.open({
      title: `Reset Password: ${escapeHtml(officer.full_name)}`,
      html: `
        <p style="color:var(--muted);font-size:13px;margin-bottom:14px;">
          Set a new temporary password for <strong>${escapeHtml(officer.email)}</strong>. Existing passwords cannot be viewed.
        </p>
        <form id="reset-pwd-form">
          <div class="field">
            <label>New Password</label>
            <input id="reset-pwd-input" type="password" required minlength="6" placeholder="Enter new password" />
          </div>
          <div class="modal-actions">
            <button type="button" class="btn btn-ghost" onclick="Modal.close()">Cancel</button>
            <button type="submit" class="btn btn-danger">Set Password</button>
          </div>
        </form>
      `,
    });

    document.getElementById("reset-pwd-form").onsubmit = async (e) => {
      e.preventDefault();
      const newPassword = document.getElementById("reset-pwd-input").value;
      try {
        await AdminAPI.post(`/officers/${officerId}/reset-password`, { new_password: newPassword });
        toast("Password reset successfully.", "success");
        Modal.close();
      } catch (err) {
        toast(err.message, "error");
      }
    };
  }

  // ---------------- Deactivate Confirmation Dialog ----------------
  function confirmDeactivate(officerId, officerName) {
    Modal.open({
      title: "Deactivate Officer?",
      html: `
        <div style="padding:4px 0 14px 0;">
          <p style="font-size:14px;line-height:1.5;margin:0 0 12px 0;">
            <strong>${escapeHtml(officerName)}</strong> will no longer be able to access RailSense Operations.
          </p>
          <p style="font-size:12.5px;color:var(--muted);margin:0;">
            Historical records, operational logs, and past actions created by this officer will be preserved.
          </p>
        </div>
        <div class="modal-actions">
          <button type="button" class="btn btn-ghost" onclick="Modal.close()">Cancel</button>
          <button type="button" class="btn btn-danger" id="btn-confirm-deactivate">Deactivate</button>
        </div>
      `,
    });

    document.getElementById("btn-confirm-deactivate").onclick = async () => {
      try {
        await AdminAPI.post(`/officers/${officerId}/status`, { status: "inactive" });
        toast(`Officer ${officerName} deactivated.`, "info");
        Modal.close();
        await loadOfficers();
      } catch (err) {
        toast(err.message, "error");
      }
    };
  }

  async function activateOfficer(officerId) {
    try {
      await AdminAPI.post(`/officers/${officerId}/status`, { status: "active" });
      toast("Officer account reactivated.", "success");
      await loadOfficers();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  return {
    load,
    openAddOfficerModal,
    openEditModal,
    openRoleModal,
    openResetPasswordModal,
    confirmDeactivate,
    activateOfficer,
  };
})();
