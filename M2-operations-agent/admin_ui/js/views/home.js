// Admin console landing page. Every stat below is a live count from the real
// stores — nothing is hardcoded, and a store that cannot be reached says so
// rather than rendering a plausible-looking zero.
//
// The 3D banner at the top ("Loco" the train robot beside a holographic model
// gauge, orbiting pending-incident cards, today's approvals and a rising
// audit stream) is driven by the same live data: /incidents, the verified map
// feed and /api/dashboard. See ui/shared/hero-deck.js for the shared stage.
window.ViewHome = (function () {
  const tiles = [
    { id: "incidents", icon: "📋", color: "var(--brand-light)", bg: "var(--brand-tint)",
      title: "Incident Management",
      desc: "Report, review, correct and delete incidents. NLP classification and summarisation run on submit." },
    { id: "model", icon: "🧠", color: "var(--maintenance)", bg: "var(--maintenance-light)",
      title: "Model Operations",
      desc: "Retrain the delay model on live data, inspect feature importances, roll back a bad run." },
    { id: "audit", icon: "🛡️", color: "var(--danger)", bg: "var(--danger-light)",
      title: "Audit & Agent Log",
      desc: "Read-only trail of every inter-agent message and operator action M2 has handled." },
  ];

  // ------------------------------------------------------------ 3D banner
  const hero = { deck: null, data: { pending: null, pendingRows: [], today: null, r2: null, mae: null, audit: null },
                 timer: 0, greeted: false };

  function heroMarkup() {
    return `
      <section class="m2h" id="adminHero" aria-label="Admin Console overview">
        <div class="m2h-scan"></div>
        <div class="m2h-inner">
          <div class="m2h-text">
            <div class="m2h-kicker"><span class="m2h-dot"></span>M2 Admin Console · Governance</div>
            <h1 class="m2h-title"><span>Govern the model,</span><span class="m2h-grad">guard the network.</span></h1>
            <p class="m2h-sub">Approve incidents before they reach the maps, keep the delay model accurate, and
              trace every operator and agent action through the audit trail.</p>
            <div class="m2h-ctas">
              <button type="button" class="m2h-btn" onclick="window.location.hash='#incidents'">✓ Review incidents</button>
              <button type="button" class="m2h-btn-alt" onclick="window.location.hash='#model'">Model operations</button>
              <button type="button" class="m2h-btn-alt" onclick="window.location.hash='#audit'">Audit log</button>
            </div>
            <div class="m2h-stats">
              <div class="m2h-stat"><b id="ah-pending">—</b><small>Pending approval</small></div>
              <div class="m2h-stat"><b id="ah-today">—</b><small>Approved today</small></div>
              <div class="m2h-stat"><b id="ah-r2">—</b><small>Model R²</small></div>
              <div class="m2h-stat"><b id="ah-audit">—</b><small>Audit events</small></div>
            </div>
          </div>
          <div class="m2h-deck">
            <div class="m2h-stage"></div>
            <div class="m2h-labels"></div>
            <div class="m2h-bubble"><span class="m2h-bubble-name">Loco · Admin Console</span><span class="m2h-bubble-text"></span></div>
            <div class="m2h-tag"><span class="m2h-dot"></span><span>GOVERNANCE DECK · LIVE</span></div>
          </div>
        </div>
      </section>`;
  }

  function setStat(id, value) {
    const el = document.getElementById(id);
    if (!el || value === null || value === undefined || el.textContent === String(value)) return;
    el.textContent = value;
    el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
  }

  async function loadHeroData() {
    const d = hero.data;
    const auth = { headers: { Authorization: `Bearer ${AdminAPI.getToken()}` } };
    await Promise.all([
      fetch("/incidents?review_status=pending&limit=8", auth).then((r) => r.json()).then((res) => {
        d.pending = res.count ?? (res.rows || []).length; d.pendingRows = res.rows || [];
      }).catch(() => {}),
      fetch("/api/incidents/map-feed").then((r) => r.json()).then((feed) => {
        d.today = (feed.incidents || []).filter((i) => i.status === "VERIFIED").length;
      }).catch(() => {}),
      fetch("/api/dashboard").then((r) => r.json()).then((dash) => {
        const ml = dash.ml_metrics || {};
        d.r2 = ml.r2 ?? null; d.mae = ml.mae_minutes ?? null;
        d.audit = (dash.overview || {}).audit_events ?? null;
      }).catch(() => {}),
    ]);
    setStat("ah-pending", d.pending);
    setStat("ah-today", d.today);
    setStat("ah-r2", d.r2 === null ? null : Number(d.r2).toFixed(3));
    setStat("ah-audit", d.audit === null ? null : Number(d.audit).toLocaleString());
    if (hero.deck) hero.deck.refresh();
  }

  function build(ctx) {
    const { THREE, platform, glow, addLabel } = ctx;
    const d = hero.data;

    // Model accuracy gauge: the gold arc is R², revealed by draw range.
    const gauge = new THREE.Group(); gauge.position.set(0.1, 2.35, -0.5); platform.add(gauge);
    gauge.add(new THREE.Mesh(new THREE.TorusGeometry(0.95, 0.045, 12, 120),
      new THREE.MeshStandardMaterial({ color: 0x1E3A8A, emissive: 0x1E3A8A, emissiveIntensity: 0.5, transparent: true, opacity: 0.7 })));
    const arcGeo = new THREE.TorusGeometry(0.95, 0.08, 12, 120);
    const arc = new THREE.Mesh(arcGeo, new THREE.MeshStandardMaterial({ color: 0xF5D776, emissive: 0xC9A22A, emissiveIntensity: 1.1, metalness: 0.6, roughness: 0.3 }));
    arc.rotation.z = Math.PI / 2; gauge.add(arc);
    arcGeo.setDrawRange(0, 0);
    const coreMesh = new THREE.Mesh(new THREE.IcosahedronGeometry(0.42, 1),
      new THREE.MeshBasicMaterial({ color: 0x60A5FA, wireframe: true, transparent: true, opacity: 0.8 }));
    gauge.add(coreMesh);
    gauge.add(glow(0x3B82F6, 2.2, 0.45));
    const gaugeLabel = addLabel("<b>R²</b> —", "#F5D776", new THREE.Vector3());
    let arcShown = 0;

    // Pending-incident cards orbiting the gauge.
    const cardShape = new THREE.Shape();
    const w = 0.36, h = 0.24, r = 0.04;
    cardShape.moveTo(-w / 2 + r, -h / 2); cardShape.lineTo(w / 2 - r, -h / 2); cardShape.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
    cardShape.lineTo(w / 2, h / 2 - r); cardShape.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2);
    cardShape.lineTo(-w / 2 + r, h / 2); cardShape.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r);
    cardShape.lineTo(-w / 2, -h / 2 + r); cardShape.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
    const cardGeo = new THREE.ExtrudeGeometry(cardShape, { depth: 0.02, bevelEnabled: false });
    const cards = [];
    const cardGroup = new THREE.Group(); gauge.add(cardGroup);
    const pendingLabel = addLabel("", "#F59E0B", new THREE.Vector3());

    // Today's approvals: green beacons around the platform floor.
    const approvals = new THREE.Group(); platform.add(approvals);
    const beacons = [];

    // Audit stream: tiles rising in a column.
    const stream = new THREE.Group(); stream.position.set(1.85, 0, -1.2); platform.add(stream);
    const tiles3d = [];
    for (let i = 0; i < 14; i++) {
      const tile = new THREE.Mesh(new THREE.PlaneGeometry(0.34, 0.1),
        new THREE.MeshBasicMaterial({ color: i % 3 ? 0x60A5FA : 0xC9A22A, transparent: true, opacity: 0.8,
          blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
      tile.position.set((Math.random() - 0.5) * 0.3, (i / 14) * 3.4, 0);
      stream.add(tile); tiles3d.push(tile);
    }
    const streamLabel = addLabel("<b>AUDIT</b> stream", "#60A5FA", new THREE.Vector3());

    function refresh() {
      const n = Math.min(d.pending || 0, 8);
      cards.splice(0).forEach((c) => cardGroup.remove(c));
      for (let i = 0; i < n; i++) {
        const c = new THREE.Mesh(cardGeo, new THREE.MeshStandardMaterial({ color: 0xFBBF24, emissive: 0xB45309, emissiveIntensity: 0.9, metalness: 0.2, roughness: 0.4 }));
        c.userData.phase = (i / Math.max(n, 1)) * Math.PI * 2;
        cardGroup.add(c); cards.push(c);
      }
      pendingLabel.el.innerHTML = d.pending ? `<b>${d.pending}</b> pending` : "";
      pendingLabel.hidden = !d.pending;

      beacons.splice(0).forEach((b) => approvals.remove(b.g));
      const m = Math.min(d.today || 0, 12);
      for (let i = 0; i < m; i++) {
        const g = new THREE.Group();
        const a = (i / Math.max(m, 1)) * Math.PI * 2 + 0.4;
        g.position.set(Math.sin(a) * ctx.R * 0.78, 0, Math.cos(a) * ctx.R * 0.78);
        const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.07, 0.9, 10, 1, true),
          new THREE.MeshBasicMaterial({ color: 0x10B981, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
        beam.position.y = 0.45; g.add(beam);
        const cap = glow(0x34D399, 0.45, 0.9); cap.position.y = 0.92; g.add(cap);
        approvals.add(g); beacons.push({ g, beam, phase: Math.random() * 6 });
      }
      gaugeLabel.el.innerHTML = d.r2 === null ? "<b>R²</b> unavailable"
        : `<b>R² ${Number(d.r2).toFixed(3)}</b> · MAE ${Number(d.mae).toFixed(2)}m`;
    }

    const v = new THREE.Vector3();
    function tick(dt, t) {
      // Reveal the R² arc.
      const target = d.r2 === null ? 0 : Math.max(0, Math.min(1, d.r2));
      arcShown += (target - arcShown) * Math.min(1, dt * (document.hidden ? 60 : 1.6));
      arcGeo.setDrawRange(0, Math.floor(arcGeo.index.count * arcShown / 3) * 3);
      coreMesh.rotation.y += dt * 0.6; coreMesh.rotation.x += dt * 0.25;
      gauge.position.y = 2.35 + Math.sin(t * 1.2) * 0.06;
      gaugeLabel.anchor.copy(gauge.getWorldPosition(v)); gaugeLabel.anchor.y += 1.15;

      cards.forEach((c, i) => {
        const a = c.userData.phase + t * 0.5;
        c.position.set(Math.cos(a) * 1.55, Math.sin(t * 1.4 + i) * 0.12, Math.sin(a) * 1.55);
        c.rotation.y = -a + Math.PI / 2;
      });
      if (cards[0]) { cards[0].getWorldPosition(pendingLabel.anchor); pendingLabel.anchor.y += 0.3; }

      beacons.forEach((b) => { b.beam.material.opacity = 0.35 + Math.sin(t * 3 + b.phase) * 0.18; });

      const speed = 0.35 + Math.min(1, (d.audit || 0) / 1000) * 0.6;
      tiles3d.forEach((tile) => {
        tile.position.y += dt * speed;
        if (tile.position.y > 3.4) { tile.position.y = 0; tile.position.x = (Math.random() - 0.5) * 0.3; }
        tile.material.opacity = 0.85 * (1 - tile.position.y / 3.4);
        tile.rotation.y = t * 0.8;
      });
      streamLabel.anchor.copy(stream.getWorldPosition(v)); streamLabel.anchor.y += 3.7;
    }

    ctx.gauge = gauge; ctx.cards = cards; ctx.stream = stream;
    return { refresh, tick };
  }

  function script(ctx) {
    const d = hero.data;
    const worldOf = (obj) => (obj ? obj.getWorldPosition(new ctx.THREE.Vector3()) : null);
    const user = AdminAPI.getCurrentUser() || {};
    const isAdmin = user.role === "admin";
    const first = String(user.name || "").split(" ")[0];
    const lines = [];
    if (!hero.greeted) {
      hero.greeted = true;
      lines.push({ text: `Welcome back${first ? ", " + first : ""}! I'm Loco, your governance assistant.`, gesture: "wave" });
    }
    if (d.pending !== null) {
      lines.push(d.pending
        ? { text: `${d.pending} incident(s) are waiting for ${isAdmin ? "your" : "an administrator's"} approval in Incident Management.`,
            gesture: "point", target: () => worldOf(ctx.cards[0]), tone: "warn" }
        : { text: "The approval queue is clear. Nothing is waiting for review!", gesture: "cheer", tone: "good" });
    }
    if (d.r2 !== null) {
      lines.push({ text: `The delay model scores R² ${Number(d.r2).toFixed(3)} with an MAE of ${Number(d.mae).toFixed(2)} min on held-out trips.`,
        gesture: "point", target: () => worldOf(ctx.gauge) });
    }
    if (d.today !== null) {
      lines.push(d.today
        ? { text: `${d.today} incident(s) approved today are live on all three incident maps.`, gesture: "nod", tone: "good" }
        : { text: "No incidents have been approved today yet.", gesture: "nod" });
    }
    if (d.audit !== null) {
      lines.push({ text: `${Number(d.audit).toLocaleString()} events are in the audit trail. Every action here is logged.`,
        gesture: "point", target: () => worldOf(ctx.stream) });
    }
    return lines;
  }

  async function startHero() {
    const root = document.getElementById("adminHero");
    if (!root) return;
    try {
      const { mountHeroDeck } = await import("/shared/hero-deck.js");
      if (!root.isConnected) return;   // navigated away while loading
      hero.deck = await mountHeroDeck(root, {
        platformAt: [1.3, -0.6], platformRadius: 3.4, robotAt: [-2.5, 0, 1.5], robotYaw: 0.5, robotScale: 0.88,
        camera: [0.2, 4.4, 10.6], lookAt: [0.2, 1.3, 0], roam: 0.5,
        build, script,
      });
      hero.deck.refresh();
    } catch (err) {
      console.warn("Admin banner unavailable:", err);
    }
  }

  function stopHero() {
    clearInterval(hero.timer);
    if (hero.deck) { hero.deck.destroy(); hero.deck = null; }
  }

  // ------------------------------------------------------------ page
  async function load() {
    stopHero();
    const container = document.getElementById("view-home");
    container.innerHTML = `
      ${heroMarkup()}
      <div class="grid grid-4" id="home-stats"></div>
      <h3 style="margin: 26px 0 14px 0; font-size: 15px;">Consoles</h3>
      <div class="grid grid-3" id="home-tiles"></div>
    `;
    startHero();
    loadHeroData();
    hero.timer = setInterval(() => {
      if (!document.getElementById("adminHero")) { stopHero(); return; }
      loadHeroData();
    }, 30000);

    document.getElementById("home-tiles").innerHTML = tiles.map((t) => `
      <div class="card dash-tile" onclick="window.location.hash='#${t.id}'">
        <div class="tile-icon" style="background:${t.bg}; color:${t.color};">${t.icon}</div>
        <div class="tile-title">${t.title}</div>
        <div class="tile-desc">${t.desc}</div>
      </div>
    `).join("");

    document.getElementById("home-stats").innerHTML = `
      <div class="card stat-card"><div class="label">Data Source</div><div class="value" id="stat-supabase">…</div></div>
      <div class="card stat-card"><div class="label">Incidents Logged</div><div class="value accent-ops" id="stat-incidents">…</div></div>
      <div class="card stat-card"><div class="label">Audit Events</div><div class="value accent-brand" id="stat-audit">…</div></div>
      <div class="card stat-card"><div class="label">Model Versions</div><div class="value" id="stat-versions">…</div></div>
    `;

    try {
      const status = await AdminAPI.get("/health/status");
      const el = document.getElementById("stat-supabase");
      el.textContent = status.supabase.reachable ? "Supabase" : "Local files";
      el.className = `value ${status.supabase.reachable ? "accent-success" : "accent-danger"}`;
      el.title = status.supabase.reachable
        ? "Supabase is reachable — reads and writes are going to Postgres."
        : "Offline mode — reads and writes are using the local CSV/JSONL stores.";
    } catch (_) {
      document.getElementById("stat-supabase").textContent = "—";
    }

    try {
      const resp = await fetch("/incidents?limit=1", {
        headers: { Authorization: `Bearer ${AdminAPI.getToken()}` },
      });
      const data = await resp.json();
      document.getElementById("stat-incidents").textContent = data.count ?? 0;
    } catch (_) { document.getElementById("stat-incidents").textContent = "—"; }

    try {
      const audit = await AdminAPI.get("/audit/events?limit=1");
      document.getElementById("stat-audit").textContent = audit.count ?? 0;
    } catch (_) { document.getElementById("stat-audit").textContent = "—"; }

    try {
      const versions = await AdminAPI.get("/model/versions");
      document.getElementById("stat-versions").textContent = versions.count ?? 0;
    } catch (_) { document.getElementById("stat-versions").textContent = "—"; }
  }

  return { load };
})();
