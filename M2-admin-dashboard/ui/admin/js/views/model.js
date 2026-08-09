window.ViewModel = (function () {
  function render() {
    const container = document.getElementById("view-model");
    container.innerHTML = `
      <p class="section-title">Model Operations</p>
      <p class="section-sub">Retrain the delay-prediction model, inspect feature importances, and roll back if a retrain regresses.</p>

      <div class="card" style="margin-bottom:18px;">
        <div class="toolbar">
          <h3 class="mb-0">Current Model</h3>
          <span class="spacer"></span>
          <button class="btn btn-primary btn-sm" id="model-retrain-btn">▶ Retrain Now</button>
        </div>
        <div id="model-current-metrics"><span class="spinner"></span></div>
      </div>

      <div class="grid grid-2">
        <div class="card">
          <h3>Feature Importances</h3>
          <p class="card-desc">Top learned signals from the most recent training run.</p>
          <div id="model-features"><span class="spinner"></span></div>
        </div>
        <div class="card">
          <h3>Training History &amp; Rollback</h3>
          <p class="card-desc">Every retrain is backed up before overwrite — restore any previous version.</p>
          <div id="model-versions"><span class="spinner"></span></div>
        </div>
      </div>
    `;
    document.getElementById("model-retrain-btn").onclick = retrain;
  }

  async function load() {
    render();
    await Promise.all([loadMetrics(), loadFeatures(), loadVersions()]);
  }

  async function loadMetrics() {
    const el = document.getElementById("model-current-metrics");
    try {
      const data = await AdminAPI.get("/model/metrics-history");
      const m = data.current_metrics;
      if (!m) {
        el.innerHTML = `<div class="empty-state">No metrics file found yet — run a training pass.</div>`;
        return;
      }
      el.innerHTML = `
        <div class="grid grid-3">
          <div class="card stat-card"><div class="label">MAE</div><div class="value accent-ops">${m.mae ?? m.MAE ?? "—"}</div></div>
          <div class="card stat-card"><div class="label">RMSE</div><div class="value accent-ops">${m.rmse ?? m.RMSE ?? "—"}</div></div>
          <div class="card stat-card"><div class="label">R²</div><div class="value accent-ops">${m.r2 ?? m.R2 ?? "—"}</div></div>
        </div>
        <p class="muted" style="margin-top:14px; font-size:12px;">${data.runs.length} logged retrain run(s) this session.</p>
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
        el.innerHTML = `<div class="empty-state">No feature_importances.json found yet.</div>`;
        return;
      }
      const top = data.features.slice(0, 10);
      const max = Math.max(...top.map((f) => f.importance ?? f.value ?? 0));
      el.innerHTML = top.map((f) => {
        const name = f.feature ?? f.name ?? "unknown";
        const val = f.importance ?? f.value ?? 0;
        const pct = max ? (val / max) * 100 : 0;
        return `
          <div class="bar-row">
            <div class="bar-label" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
            <div class="bar-value">${Number(val).toFixed(3)}</div>
          </div>
        `;
      }).join("");
    } catch (err) {
      el.innerHTML = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
    }
  }

  async function loadVersions() {
    const el = document.getElementById("model-versions");
    try {
      const data = await AdminAPI.get("/model/versions");
      if (!data.versions.length) {
        el.innerHTML = `<div class="empty-state">No backed-up versions yet — they appear after your first retrain.</div>`;
        return;
      }
      el.innerHTML = data.versions.map((v) => `
        <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid var(--border);">
          <div>
            <div class="mono" style="font-size:12px;">${escapeHtml(v.filename)}</div>
            <div class="muted" style="font-size:11px;">${formatDate(v.created_at)}</div>
          </div>
          <button class="btn btn-ghost btn-sm" onclick="ViewModel.rollback('${v.filename}')">Restore</button>
        </div>
      `).join("");
    } catch (err) {
      el.innerHTML = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
    }
  }

  async function retrain() {
    const btn = document.getElementById("model-retrain-btn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Training…';
    toast("Training started — this can take a moment…", "info");
    try {
      const result = await AdminAPI.post("/model/retrain");
      toast("Retrain complete", "success");
      await Promise.all([loadMetrics(), loadFeatures(), loadVersions()]);
    } catch (err) {
      toast(`Retrain failed: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = "▶ Retrain Now";
    }
  }

  async function rollback(filename) {
    if (!confirm(`Restore model version ${filename}? The current model will be backed up first.`)) return;
    try {
      await AdminAPI.post(`/model/rollback/${filename}`);
      toast("Model restored", "success");
      await Promise.all([loadMetrics(), loadVersions()]);
    } catch (err) {
      toast(err.message, "error");
    }
  }

  return { load, rollback };
})();
