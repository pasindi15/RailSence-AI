// Roles & Permissions Matrix View
window.ViewRoles = (function () {
  function render() {
    const container = document.getElementById("view-roles");
    container.innerHTML = `
      <div style="margin-bottom:18px;">
        <p class="section-title" style="font-size:20px;font-weight:700;margin:0 0 4px 0;">Roles &amp; Permissions Matrix</p>
        <p class="section-sub" style="color:var(--muted);font-size:13px;margin:0;">Inspect defined operational capabilities, access boundaries, and role-permission mappings across the RailSense AI architecture.</p>
      </div>

      <!-- Capability Matrix Table -->
      <div class="card" style="padding:0;overflow:hidden;margin-bottom:20px;">
        <div style="padding:16px 20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;">
          <div>
            <h3 style="margin:0;font-size:15px;">Primary Access Matrix</h3>
            <span style="font-size:12px;color:var(--muted);">Enforced at both backend API middleware and frontend navigation levels</span>
          </div>
          <span class="badge approved">RBAC Active</span>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width:34%;">Feature / Capability</th>
                <th style="text-align:center;width:22%;">Admin</th>
                <th style="text-align:center;width:22%;">Operations Engineer</th>
                <th style="width:22%;">Scope &amp; Enforcement</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Control Room Dashboard</strong><br><small class="muted">Live train map, crossing monitors, delay pressure</small></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td><span class="badge active">Operational</span></td>
              </tr>
              <tr>
                <td><strong>Interactive Delay Prediction</strong><br><small class="muted">Live inference regressor, feature importance, triage</small></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td><span class="badge active">Operational</span></td>
              </tr>
              <tr>
                <td><strong>View Operational Data &amp; Events</strong><br><small class="muted">Live route delay heatmaps, incident feeds</small></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td><span class="badge active">Operational</span></td>
              </tr>
              <tr>
                <td><strong>M2 Admin Console</strong><br><small class="muted">System configuration, data CRUD, model retraining</small></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td style="text-align:center;"><span style="color:var(--danger);font-size:16px;font-weight:bold;">❌</span></td>
                <td><span class="badge admin">Admin Only</span></td>
              </tr>
              <tr>
                <td><strong>Officers &amp; Access Management</strong><br><small class="muted">View officer accounts, security audit trail</small></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td style="text-align:center;"><span style="color:var(--danger);font-size:16px;font-weight:bold;">❌</span></td>
                <td><span class="badge admin">Admin Only</span></td>
              </tr>
              <tr>
                <td><strong>Create Officer Accounts</strong><br><small class="muted">Provision credentials without public self-registration</small></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td style="text-align:center;"><span style="color:var(--danger);font-size:16px;font-weight:bold;">❌</span></td>
                <td><span class="badge admin">Admin Only</span></td>
              </tr>
              <tr>
                <td><strong>Edit / Change Officer Role</strong><br><small class="muted">Promote or demote roles with last-admin guard</small></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td style="text-align:center;"><span style="color:var(--danger);font-size:16px;font-weight:bold;">❌</span></td>
                <td><span class="badge admin">Admin Only</span></td>
              </tr>
              <tr>
                <td><strong>Deactivate Officer Accounts</strong><br><small class="muted">Revoke access without deleting historical data</small></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td style="text-align:center;"><span style="color:var(--danger);font-size:16px;font-weight:bold;">❌</span></td>
                <td><span class="badge admin">Admin Only</span></td>
              </tr>
              <tr>
                <td><strong>Reset Officer Passwords</strong><br><small class="muted">Generate new temporary bcrypt-hashed credentials</small></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td style="text-align:center;"><span style="color:var(--danger);font-size:16px;font-weight:bold;">❌</span></td>
                <td><span class="badge admin">Admin Only</span></td>
              </tr>
              <tr>
                <td><strong>Model Retraining &amp; Rollback</strong><br><small class="muted">Trigger ML retrain scripts and model version switches</small></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td style="text-align:center;"><span style="color:var(--danger);font-size:16px;font-weight:bold;">❌</span></td>
                <td><span class="badge admin">Admin Only</span></td>
              </tr>
              <tr>
                <td><strong>System &amp; Hub Configuration</strong><br><small class="muted">Adjust delay thresholds and inter-agent routes</small></td>
                <td style="text-align:center;"><span style="color:var(--success);font-size:16px;font-weight:bold;">✅</span></td>
                <td style="text-align:center;"><span style="color:var(--danger);font-size:16px;font-weight:bold;">❌</span></td>
                <td><span class="badge admin">Admin Only</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Extensible Architecture Section -->
      <div class="card">
        <h3 style="margin-top:0;font-size:15px;">Extensible Role Architecture (Future Roles Preview)</h3>
        <p style="font-size:12.5px;color:var(--muted);margin-bottom:14px;">
          The RBAC engine decouples capabilities from roles via <span class="mono">ROLE_PERMISSIONS</span> in <span class="mono">admin_auth.py</span>. Additional specialized roles can be activated seamlessly:
        </p>
        <div class="grid grid-3" style="display:grid;grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));gap:12px;">
          <div style="background:var(--surface-2);padding:12px 14px;border-radius:10px;border:1px solid var(--border);">
            <strong>Operations Manager</strong>
            <p style="font-size:12px;color:var(--muted);margin:4px 0 0 0;">Control room, prediction, audit reviews, and operational data management.</p>
          </div>
          <div style="background:var(--surface-2);padding:12px 14px;border-radius:10px;border:1px solid var(--border);">
            <strong>Train Dispatcher</strong>
            <p style="font-size:12px;color:var(--muted);margin:4px 0 0 0;">Live tracking, crossing control, and operational dispatch messaging.</p>
          </div>
          <div style="background:var(--surface-2);padding:12px 14px;border-radius:10px;border:1px solid var(--border);">
            <strong>Operations Analyst</strong>
            <p style="font-size:12px;color:var(--muted);margin:4px 0 0 0;">Delay prediction lab, model evaluation analytics, and historical query access.</p>
          </div>
        </div>
      </div>
    `;
  }

  function load() {
    render();
  }

  return { load };
})();
