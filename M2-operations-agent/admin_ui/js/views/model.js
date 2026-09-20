// Model Operations — retrain the delay model and roll back a bad run.
//
// Retrain shells out to ml/train_delay_model.py against the live corpus
// (Supabase when online, the CSV otherwise). The script archives the outgoing
// delay_model.pkl to ml/model_versions/ with a metrics sidecar before writing
// the new one, so the version list below shows real files, real timestamps and
// the metrics each model actually scored.
window.ViewModel = (function () {
  function render() {
    const container = document.getElementById("view-model");
    container.innerHTML = `
      <p class="section-title">Model Operations</p>
      <p class="section-sub">
        Retrain the delay-prediction model against current operations data, inspect what it learned,
        and roll back to a previous version if a run regresses.
      </p>

      <div class="card" style="margin-bottom:18px;">
        <div class="toolbar">
          <h3 class="mb-0">Current Model</h3>
          <span class="spacer"></span>
          <span class="source-tag" id="model-source-tag">…</span>
          <button class="btn btn-primary btn-sm" id="model-retrain-btn">▶ Retrain Now</button>
        </div>
        <div id="model-current-metrics"><span class="spinner"></span></div>
      </div>

      <div class="grid grid-2">
        <div class="card">
          <h3>Feature Importances</h3>
          <p class="card-desc">Read live from <span class="mono">ml/feature_importances.json</span>, rewritten by each training run.</p>
          <div id="model-features"><span class="spinner"></span></div>
        </div>
        <div class="card">
          <h3>Version History &amp; Rollback</h3>
          <p class="card-desc">Timestamped backups on disk. Restoring one also restores its metrics and reloads the live predictor.</p>
          <div id="model-versions"><span class="spinner"></span></div>
        </div>
      </div>
    `;
    document.getElementById("model-retrain-btn").onclick = retrain;
  }

  function metricValue(metrics, ...keys) {
    if (!metrics) return "—";
    for (const key of keys) {
      if (metrics[key] !== undefined && metrics[key] !== null) return metrics[key];
    }
    return "—";
  }

  async function loadMetrics() {
    const el = document.getElementById("model-current-metrics");
    try {
      const data = await AdminAPI.get("/model/metrics-history");
      const m = data.current_metrics;
      const tag = document.getElementById("model-source-tag");
      if (tag) {
        const src = m && m.data_source ? m.data_source : "unknown";
        tag.textContent = `trained from: ${src}`;
        tag.className = `source-tag ${src === "supabase" ? "supabase" : "fallback"}`;
      }

      if (!m) {
        el.innerHTML = `<div class="empty-state">
          No metrics file yet — run a training pass to produce
          <span class="mono">evaluation/ml/delay_model_metrics.json</span>.</div>`;
        return;
      }

      const lastRun = data.runs && data.runs.length ? data.runs[data.runs.length - 1] : null;
      el.innerHTML = `
        <div class="grid grid-3">
          <div class="card stat-card"><div class="label">MAE (minutes)</div><div class="value accent-ops">${metricValue(m, "mae_minutes", "mae", "MAE")}</div></div>
          <div class="card stat-card"><div class="label">RMSE (minutes)</div><div class="value accent-ops">${metricValue(m, "rmse_minutes", "rmse", "RMSE")}</div></div>
          <div class="card stat-card"><div class="label">R²</div><div class="value accent-ops">${metricValue(m, "r2", "R2")}</div></div>
        </div>
        <p class="muted" style="margin-top:14px;font-size:12px;">
          ${escapeHtml(String(metricValue(m, "model")))} ·
          ${escapeHtml(String(metricValue(m, "n_train")))} train / ${escapeHtml(String(metricValue(m, "n_test")))} test rows ·
          data source: <strong>${escapeHtml(String(metricValue(m, "data_source")))}</strong>
          ${m.trained_at ? ` · trained ${formatDate(m.trained_at)}` : ""}
        </p>
        <p class="muted" style="font-size:12px;">
          ${data.run_count} logged run(s).
          ${lastRun ? `Last: <strong>${escapeHtml(lastRun.action || "retrain")}</strong> by ${escapeHtml(lastRun.triggered_by || "—")}${lastRun.backup_created ? `, backed up as <span class="mono">${escapeHtml(lastRun.backup_created)}</span>` : ""}.` : ""}
        </p>
      `;
    } catch (err) {
      el.innerHTML = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
    }
  }

  async function loadFeatures() {
    const el = document.getElementById("model-features");
    try {
      const data = await AdminAPI.get("/model/feature-importances");
      if (!data.available || !data.features.length) {
        el.innerHTML = `<div class="empty-state">No <span class="mono">feature_importances.json</span> yet — retrain to generate it.</div>`;
        return;
      }
      const top = data.features.slice(0, 10);
      const max = Math.max(...top.map((f) => f.importance ?? f.value ?? 0), 1e-9);
      el.innerHTML = top.map((f) => {
        const name = f.feature ?? f.name ?? "unknown";
        const val = f.importance ?? f.value ?? 0;
        return `
          <div class="bar-row">
            <div class="bar-label" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${(val / max) * 100}%"></div></div>
            <div class="bar-value">${Number(val).toFixed(4)}</div>
          </div>`;
      }).join("") + `<p class="muted" style="font-size:11px;margin-top:10px;">
        Artifact written ${formatDate(data.generated_at)}.</p>`;
    } catch (err) {
      el.innerHTML = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
    }
  }

  async function loadVersions() {
    const el = document.getElementById("model-versions");
    try {
      const data = await AdminAPI.get("/model/versions");
      if (!data.versions.length) {
        el.innerHTML = `<div class="empty-state">No archived versions yet — the first retrain creates one.</div>`;
        return;
      }
      el.innerHTML = data.versions.map((v) => {
        const m = v.metrics;
        const summary = m
          ? `MAE ${metricValue(m, "mae_minutes", "mae")} · RMSE ${metricValue(m, "rmse_minutes", "rmse")} · R² ${metricValue(m, "r2")}`
          : "metrics not recorded for this version";
        return `
          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border);">
            <div style="min-width:0;">
              <div class="mono" style="font-size:12px;overflow-wrap:anywhere;">${escapeHtml(v.filename)}</div>
              <div class="muted" style="font-size:11px;">${formatDate(v.created_at)} · ${(v.size_bytes / 1024).toFixed(0)} KB</div>
              <div class="muted" style="font-size:11px;">${escapeHtml(summary)}</div>
            </div>
            <button class="btn btn-ghost btn-sm" onclick="ViewModel.rollback('${escapeHtml(v.filename)}')">Restore</button>
          </div>`;
      }).join("");
    } catch (err) {
      el.innerHTML = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
    }
  }

  async function retrain() {
    const btn = document.getElementById("model-retrain-btn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Training…';
    toast("Training started — this can take a minute…", "info");
    try {
      const result = await AdminAPI.post("/model/retrain");
      const backup = result.backup_created ? `Backed up as ${result.backup_created}.` : "No prior model to back up.";
      const reload = result.model_reloaded ? "New model is live — no restart needed." : "Restart the service to serve the new model.";
      toast(`Retrain complete. ${backup} ${reload}`, "success");
      await load();
    } catch (err) {
      toast(`Retrain failed: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = "▶ Retrain Now";
    }
  }

  async function rollback(filename) {
    if (!confirm(`Restore model version ${filename}?\n\nThe current model is archived first, and its metrics are restored alongside it.`)) return;
    try {
      const result = await AdminAPI.post(`/model/rollback/${filename}`);
      const reload = result.model_reloaded ? "Restored model is live." : "Restart the service to serve the restored model.";
      toast(`Rolled back to ${filename}. ${reload}`, "success");
      await load();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function load() {
    if (!document.getElementById("model-current-metrics")) render();
    await Promise.all([loadMetrics(), loadFeatures(), loadVersions()]);
  }

  return { load: () => { render(); return load(); }, rollback };
})();
