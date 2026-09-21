// RailSense AI — Operations Assistant (shared floating chatbot).
//
// Served by M2 at /shared/ops-agent.js and used by the Control Room (/) and
// the Admin Console (/admin). Pages call RailSenseOpsAgent.init() once the
// officer is signed in and RailSenseOpsAgent.destroy() on logout.
//
// init() asks GET /api/ops-agent/capabilities with the officer token: the
// widget only appears when the role holds m2.assistant.use (administrators and
// operations engineers), and it shows that role's own example questions.
// Every answer carries an answer_type so "restricted", "not enough
// information", "out of scope" and "unavailable" replies are styled as the
// notices they are, not as data.
//
// Backend: POST /api/ops-agent/ask, GET /api/ops-agent/history.
// Replaying a history item shows the stored answer; it never re-runs the query.
window.RailSenseOpsAgent = (function () {
  const TOKEN_KEY = "railsense_m2_token";
  const THREAD_KEY = "railsense_ops_agent_thread";
  const METHOD_LABELS = {
    llm_tool_calling: "Gemini · tool calling",
    rule_based_fallback: "Rule-based fallback",
    template_after_guard: "Template (number check)",
  };
  const NOTICES = {
    restricted: { icon: "🔒", label: "Administrator only" },
    insufficient_data: { icon: "ℹ", label: "Not enough information" },
    out_of_scope: { icon: "↪", label: "Outside my scope" },
    unavailable: { icon: "⚠", label: "Live data unavailable" },
  };

  let root = null;
  let caps = null;         // capabilities of the signed-in role
  let thread = [];
  let history = [];
  let replay = null;
  let busy = false;

  const $ = (sel) => root.querySelector(sel);
  const token = () => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (_) { return ""; } };
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Minimal, safe markdown: escape first, then **bold**, _italic_, `code`, "- " lists.
  function md(text) {
    const inline = (s) => esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/(^|[\s(])_(.+?)_(?=[\s).,]|$)/g, "$1<em>$2</em>");
    const out = [];
    let list = null;
    String(text || "").split(/\n/).forEach((line) => {
      const m = line.match(/^\s*[-*•]\s+(.*)$/);
      if (m) { (list = list || []).push(`<li>${inline(m[1])}</li>`); return; }
      if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; }
      if (line.trim()) out.push(`<p>${inline(line)}</p>`);
    });
    if (list) out.push(`<ul>${list.join("")}</ul>`);
    return out.join("");
  }

  function relTime(iso) {
    const t = new Date(iso).getTime();
    if (isNaN(t)) return "";
    const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    return `${Math.round(s / 86400)} d ago`;
  }

  async function call(path, options = {}) {
    const headers = { "Content-Type": "application/json" };
    if (token()) headers.Authorization = `Bearer ${token()}`;
    const resp = await fetch(path, { ...options, headers });
    let data = null;
    try { data = await resp.json(); } catch (_) { /* empty */ }
    if (resp.status === 401) { const e = new Error("Your session has expired. Please sign in again."); e.status = 401; throw e; }
    if (!resp.ok) { const e = new Error((data && data.detail) || resp.statusText); e.status = resp.status; throw e; }
    return data;
  }

  /* ------------------------------------------------------------ styles */
  function injectStyles() {
    if (document.getElementById("oa-styles")) return;
    const st = document.createElement("style");
    st.id = "oa-styles";
    st.textContent = `
.oa-root{position:fixed;right:22px;bottom:22px;z-index:900;font-family:inherit;--oa-tint:var(--brand-tint,rgba(59,130,246,.12));--oa-gold:var(--gold,#C9A22A)}
.oa-ball{width:54px;height:54px;border-radius:50%;border:1px solid rgba(255,255,255,.25);display:grid;place-items:center;cursor:pointer;color:#1a1300;
  background:radial-gradient(circle at 32% 28%,#F5D776 0%,var(--oa-gold) 55%,#8A6B12 100%);
  box-shadow:0 8px 24px rgba(0,0,0,.45),0 0 0 0 rgba(201,162,42,.45);animation:oa-glow 4.5s ease-in-out infinite;transition:transform .2s ease}
.oa-ball svg{width:24px;height:24px;fill:currentColor}
.oa-ball:hover{transform:translateY(-2px) scale(1.05)}
.oa-root.open .oa-ball{animation:none;box-shadow:0 0 0 3px rgba(59,130,246,.55),0 8px 24px rgba(0,0,0,.45)}
@keyframes oa-glow{0%,100%{box-shadow:0 8px 24px rgba(0,0,0,.45),0 0 0 0 rgba(201,162,42,.40)}50%{box-shadow:0 8px 24px rgba(0,0,0,.45),0 0 0 12px rgba(201,162,42,0)}}
.oa-panel{position:absolute;right:0;bottom:68px;width:min(760px,calc(100vw - 44px));height:min(580px,calc(100vh - 120px));display:flex;border-radius:16px;overflow:hidden;
  background:linear-gradient(135deg,var(--card,#0e1424) 0%,var(--card-hi,#16203a) 100%);border:1px solid var(--border-hi,rgba(96,165,250,.5));
  backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);box-shadow:0 24px 70px rgba(0,0,0,.6);
  opacity:0;transform:translateY(12px) scale(.97);transform-origin:bottom right;pointer-events:none;visibility:hidden;
  transition:opacity .2s ease,transform .25s ease,visibility 0s linear .25s}
.oa-root.open .oa-panel{opacity:1;transform:none;pointer-events:auto;visibility:visible;transition:opacity .2s ease,transform .25s ease}
.oa-rail{width:220px;flex-shrink:0;display:flex;flex-direction:column;border-right:1px solid var(--border,rgba(59,130,246,.2));background:rgba(6,10,18,.35)}
.oa-rail-head{padding:14px 14px 8px;font:700 10.5px/1 'Share Tech Mono',monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--muted,#8291a8)}
.oa-history-list{flex:1;overflow-y:auto;padding:0 8px 10px}
.oa-history-empty{padding:10px 8px;font-size:12px;color:var(--muted,#8291a8)}
.oa-h-item{display:block;width:100%;text-align:left;padding:8px 9px;margin-bottom:3px;border-radius:8px;border:1px solid transparent;background:transparent;color:var(--ink,#cbd5e1);cursor:pointer;font-family:inherit}
.oa-h-item span{display:block;font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.oa-h-item small{font-size:10.5px;color:var(--muted,#8291a8)}
.oa-h-item:hover{background:var(--oa-tint)}
.oa-h-item.active{background:var(--oa-tint);border-color:rgba(59,130,246,.4)}
.oa-main{flex:1;min-width:0;display:flex;flex-direction:column}
.oa-head{display:flex;align-items:center;gap:8px;padding:12px 12px 10px 14px;border-bottom:1px solid var(--border,rgba(59,130,246,.2))}
.oa-title{flex:1;min-width:0}
.oa-title strong{display:block;font-family:'Playfair Display',serif;font-size:15.5px;color:var(--ink-bright,#fff)}
.oa-title small{font-size:11px;color:var(--muted,#8291a8)}
.oa-icon{width:30px;height:30px;border-radius:8px;border:1px solid var(--border,rgba(59,130,246,.2));background:transparent;color:var(--ink,#cbd5e1);cursor:pointer;font-size:14px}
.oa-icon:hover{border-color:var(--border-hi,rgba(96,165,250,.5));color:var(--ink-bright,#fff)}
.oa-rail-toggle{display:none}
.oa-replay{display:none;align-items:center;justify-content:space-between;gap:8px;padding:7px 14px;font-size:11.5px;color:var(--oa-gold);background:rgba(201,162,42,.10);border-bottom:1px solid rgba(201,162,42,.25)}
.oa-back{border:0;background:none;color:var(--brand-light,#60a5fa);font-weight:700;font-size:11.5px;cursor:pointer}
.oa-thread{flex:1;min-height:0;overflow-y:auto;padding:16px 14px;display:flex;flex-direction:column;gap:10px}
.oa-msg{max-width:88%;font-size:13px;line-height:1.55;animation:oa-rise .25s ease both}
@keyframes oa-rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.oa-msg.user{align-self:flex-end;padding:8px 12px;border-radius:12px 12px 3px 12px;color:#fff;background:var(--brand-grad,linear-gradient(135deg,#1D4ED8,#3B82F6))}
.oa-msg.agent{align-self:flex-start;width:100%;padding:11px 13px;border-radius:3px 12px 12px 12px;background:rgba(6,10,18,.45);border:1px solid var(--border,rgba(59,130,246,.2));color:var(--ink,#cbd5e1)}
.oa-msg.agent.error{color:#FCA5A5;border-color:rgba(239,68,68,.35)}
.oa-msg.agent.t-restricted{border-color:rgba(201,162,42,.5);background:rgba(201,162,42,.07)}
.oa-msg.agent.t-insufficient_data{border-color:rgba(96,165,250,.45);background:rgba(59,130,246,.07)}
.oa-msg.agent.t-out_of_scope{border-style:dashed}
.oa-msg.agent.t-unavailable{border-color:rgba(239,68,68,.45);background:rgba(239,68,68,.06)}
.oa-notice{display:inline-flex;align-items:center;gap:6px;margin-bottom:7px;padding:2px 9px;border-radius:99px;font:700 10.5px/1.6 system-ui,sans-serif;letter-spacing:.03em;text-transform:uppercase;border:1px solid currentColor}
.t-restricted .oa-notice{color:var(--oa-gold)}
.t-insufficient_data .oa-notice{color:var(--brand-light,#60a5fa)}
.t-out_of_scope .oa-notice{color:var(--muted,#8291a8)}
.t-unavailable .oa-notice{color:#F87171}
.oa-text p{margin:0 0 6px}
.oa-text p:last-child{margin-bottom:0}
.oa-text ul{margin:4px 0 6px;padding-left:18px}
.oa-text li{margin:2px 0}
.oa-text strong{color:var(--ink-bright,#fff)}
.oa-text code{font-family:'Share Tech Mono',monospace;font-size:12px;color:var(--brand-light,#60a5fa)}
.oa-stats{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:9px}
.oa-stat{padding:5px 10px;border-radius:9px;border:1px solid var(--border,rgba(59,130,246,.2));background:var(--oa-tint)}
.oa-stat small{display:block;font-size:9.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted,#8291a8)}
.oa-stat b{font-size:14px;color:var(--ink-bright,#fff)}
.oa-stat.good b{color:#34D399}.oa-stat.warn b{color:#FBBF24}.oa-stat.bad b{color:#F87171}
.oa-sources{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}
.oa-src{font-size:10.5px;padding:2px 8px;border-radius:99px;color:var(--oa-gold);border:1px solid rgba(201,162,42,.35);background:rgba(201,162,42,.08)}
.oa-meta{margin-top:6px;font:10px 'Share Tech Mono',monospace;color:var(--muted,#8291a8);letter-spacing:.04em}
.oa-typing{display:inline-flex;gap:4px}
.oa-typing i{width:6px;height:6px;border-radius:50%;background:var(--brand-light,#60a5fa);animation:oa-bounce 1s infinite ease-in-out}
.oa-typing i:nth-child(2){animation-delay:.15s}.oa-typing i:nth-child(3){animation-delay:.3s}
@keyframes oa-bounce{0%,80%,100%{opacity:.35;transform:none}40%{opacity:1;transform:translateY(-4px)}}
.oa-empty{margin:auto;max-width:440px;text-align:center;color:var(--muted,#8291a8);font-size:12.5px}
.oa-empty-icon{font-size:26px;color:var(--oa-gold)}
.oa-empty strong{display:block;margin:4px 0;font-size:15px;color:var(--ink-bright,#fff)}
.oa-empty em{display:block;margin-top:8px;font-style:normal;font-size:11.5px}
.oa-examples{display:flex;flex-wrap:wrap;justify-content:center;gap:7px;margin-top:14px}
.oa-chip{padding:6px 11px;border-radius:99px;border:1px solid var(--border-hi,rgba(96,165,250,.5));background:var(--oa-tint);color:var(--ink,#cbd5e1);font-size:12px;cursor:pointer;font-family:inherit}
.oa-chip:hover{color:var(--ink-bright,#fff);border-color:var(--oa-gold)}
.oa-input{display:flex;gap:8px;padding:10px 12px 12px;border-top:1px solid var(--border,rgba(59,130,246,.2))}
.oa-input input{flex:1;min-width:0;padding:10px 13px;border-radius:10px;border:1px solid var(--border,rgba(59,130,246,.2));background:rgba(6,10,18,.5);color:var(--ink-bright,#fff);font-size:13px;font-family:inherit;outline:none;width:auto}
.oa-input input:focus{border-color:var(--brand,#3B82F6);box-shadow:0 0 0 3px rgba(59,130,246,.15)}
.oa-send{width:42px;border:0;border-radius:10px;background:var(--brand-grad,linear-gradient(135deg,#1D4ED8,#3B82F6));color:#fff;cursor:pointer;font-size:15px}
.oa-send:disabled{opacity:.5;cursor:wait}
@media (max-width:820px){
  .oa-rail{position:absolute;top:0;bottom:0;left:0;z-index:2;width:230px;transform:translateX(-100%);transition:transform .2s ease;background:var(--card-hi,#16203a)}
  .oa-root.rail-open .oa-rail{transform:none;box-shadow:12px 0 30px rgba(0,0,0,.4)}
  .oa-rail-toggle{display:inline-block}
}
@media (max-width:480px){.oa-root{right:12px;bottom:12px}.oa-panel{width:calc(100vw - 24px);height:calc(100vh - 96px)}}
@media (prefers-reduced-motion:reduce){.oa-ball,.oa-msg,.oa-typing i{animation:none!important}}
[data-theme="light"] .oa-rail{background:rgba(241,245,253,.7)}
[data-theme="light"] .oa-msg.agent,[data-theme="light"] .oa-input input{background:#fff}
[data-theme="light"] .oa-src,[data-theme="light"] .oa-replay,[data-theme="light"] .t-restricted .oa-notice{color:#8A6B12}
`;
    document.head.appendChild(st);
  }

  /* --------------------------------------------------------- rendering */
  function agentHtml(d) {
    const type = d.answer_type || "answer";
    const notice = NOTICES[type];
    const stats = (d.highlights || []).map((h) =>
      `<div class="oa-stat ${esc(h.tone || "neutral")}"><small>${esc(h.label)}</small><b>${esc(h.value)}</b></div>`).join("");
    const sources = (d.sources || []).map((s) =>
      `<span class="oa-src" title="${esc(s.tool)}">${esc(s.label)}</span>`).join("");
    return `${notice ? `<div class="oa-notice">${notice.icon} ${esc(notice.label)}</div>` : ""}
      ${stats ? `<div class="oa-stats">${stats}</div>` : ""}
      <div class="oa-text">${md(d.answer)}</div>
      ${sources ? `<div class="oa-sources">${sources}</div>` : ""}
      ${d.answer_method ? `<div class="oa-meta">${esc(METHOD_LABELS[d.answer_method] || d.answer_method)}</div>` : ""}`;
  }

  function renderThread() {
    const box = $(".oa-thread");
    const items = replay ? [{ role: "user", text: replay.question }, { role: "agent", data: replay }] : thread;
    $(".oa-replay").style.display = replay ? "flex" : "none";
    if (replay) $(".oa-replay-when").textContent = relTime(replay.created_at);
    $(".oa-input").style.display = replay ? "none" : "flex";

    if (!items.length) {
      const restricted = (caps.restricted_topics || []);
      box.innerHTML = `
        <div class="oa-empty">
          <div class="oa-empty-icon">✦</div>
          <strong>Ask about live operations</strong>
          <span>Every answer comes from M2's own data and cites its source. I can help with ${esc((caps.can_help_with || []).join(", "))}.</span>
          ${restricted.length ? `<em>🔒 Administrator only: ${esc(restricted.join(", "))}.</em>` : ""}
          <div class="oa-examples">${(caps.examples || []).map((q) => `<button type="button" class="oa-chip">${esc(q)}</button>`).join("")}</div>
        </div>`;
      box.querySelectorAll(".oa-chip").forEach((b) => b.addEventListener("click", () => {
        const input = $(".oa-input input");
        input.value = b.textContent;   // fill, don't send
        input.focus();
      }));
      return;
    }
    box.innerHTML = items.map((m) => {
      if (m.role === "user") return `<div class="oa-msg user">${esc(m.text)}</div>`;
      if (m.pending) return `<div class="oa-msg agent"><span class="oa-typing"><i></i><i></i><i></i></span></div>`;
      if (m.error) return `<div class="oa-msg agent error">${esc(m.error)}</div>`;
      return `<div class="oa-msg agent t-${esc(m.data.answer_type || "answer")}">${agentHtml(m.data)}</div>`;
    }).join("");
    box.scrollTop = box.scrollHeight;
  }

  function renderHistory() {
    const list = $(".oa-history-list");
    if (!history.length) {
      list.innerHTML = `<div class="oa-history-empty">Your questions will appear here.</div>`;
      return;
    }
    list.innerHTML = history.map((h, i) => `
      <button type="button" class="oa-h-item ${replay && replay.id === h.id ? "active" : ""}" data-i="${i}">
        <span>${esc(h.question)}</span><small>${esc(relTime(h.created_at))}</small>
      </button>`).join("");
    list.querySelectorAll(".oa-h-item").forEach((b) => b.addEventListener("click", () => {
      replay = history[Number(b.dataset.i)];
      root.classList.remove("rail-open");
      renderHistory();
      renderThread();
    }));
  }

  function saveThread() {
    try { sessionStorage.setItem(THREAD_KEY, JSON.stringify(thread.filter((m) => !m.pending).slice(-40))); } catch (_) { /* ignore */ }
  }

  /* ----------------------------------------------------------- actions */
  async function loadHistory() {
    try { history = (await call("/api/ops-agent/history?limit=50")).rows || []; } catch (_) { history = []; }
    renderHistory();
  }

  async function ask(question) {
    if (busy || !question.trim()) return;
    busy = true;
    replay = null;
    const pending = { role: "agent", pending: true };
    thread.push({ role: "user", text: question }, pending);
    renderThread();
    $(".oa-send").disabled = true;
    try {
      const data = await call("/api/ops-agent/ask", { method: "POST", body: JSON.stringify({ question }) });
      thread[thread.indexOf(pending)] = { role: "agent", data };
      history.unshift({ id: data.id, question: data.question || question, answer: data.answer,
        answer_type: data.answer_type, sources: data.sources, highlights: data.highlights,
        answer_method: data.answer_method, created_at: data.created_at });
      renderHistory();
    } catch (err) {
      thread[thread.indexOf(pending)] = { role: "agent", error: err.message };
    } finally {
      busy = false;
      if (root) {
        $(".oa-send").disabled = false;
        saveThread();
        renderThread();
        $(".oa-input input").focus();
      }
    }
  }

  function open() { root.classList.add("open"); $(".oa-input input").focus(); loadHistory(); }
  function close() { root.classList.remove("open", "rail-open"); }
  function onOutside(e) { if (root && root.classList.contains("open") && !root.contains(e.target)) close(); }
  function onEscape(e) { if (e.key === "Escape" && root && root.classList.contains("open")) close(); }

  function render() {
    injectStyles();
    try { thread = JSON.parse(sessionStorage.getItem(THREAD_KEY) || "[]"); } catch (_) { thread = []; }
    root = document.createElement("div");
    root.className = "oa-root";
    root.innerHTML = `
      <button type="button" class="oa-ball" aria-label="Open Operations Assistant" title="Operations Assistant">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2l1.9 5.6L19.5 9.5l-5.6 1.9L12 17l-1.9-5.6L4.5 9.5l5.6-1.9z"/><path d="M18.5 15l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9z" opacity=".75"/></svg>
      </button>
      <section class="oa-panel" role="dialog" aria-label="Operations Assistant">
        <aside class="oa-rail"><div class="oa-rail-head">History</div><div class="oa-history-list"></div></aside>
        <div class="oa-main">
          <header class="oa-head">
            <button type="button" class="oa-icon oa-rail-toggle" title="History" aria-label="Show history">☰</button>
            <div class="oa-title"><strong>Operations Assistant</strong><small>Answers only from live M2 data · ${esc(caps.role_display || caps.role || "")}</small></div>
            <button type="button" class="oa-icon oa-new" title="New conversation" aria-label="New conversation">＋</button>
            <button type="button" class="oa-icon oa-close" title="Close" aria-label="Close">✕</button>
          </header>
          <div class="oa-replay"><span>Replay · asked <b class="oa-replay-when"></b> · read-only</span>
            <button type="button" class="oa-back">Back to conversation</button></div>
          <div class="oa-thread" aria-live="polite"></div>
          <form class="oa-input">
            <input type="text" maxlength="500" placeholder="Ask about delays, routes, incidents…" autocomplete="off" />
            <button type="submit" class="oa-send" aria-label="Send">➤</button>
          </form>
        </div>
      </section>`;
    document.body.appendChild(root);

    $(".oa-ball").addEventListener("click", () => (root.classList.contains("open") ? close() : open()));
    $(".oa-close").addEventListener("click", close);
    $(".oa-rail-toggle").addEventListener("click", () => root.classList.toggle("rail-open"));
    $(".oa-new").addEventListener("click", () => { thread = []; replay = null; saveThread(); renderThread(); renderHistory(); });
    $(".oa-back").addEventListener("click", () => { replay = null; renderHistory(); renderThread(); });
    $(".oa-input").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = $(".oa-input input");
      const q = input.value.trim();
      input.value = "";
      ask(q);
    });
    document.addEventListener("mousedown", onOutside);
    document.addEventListener("keydown", onEscape);
    renderThread();
    renderHistory();
  }

  /* -------------------------------------------------------- lifecycle */
  let initSeq = 0;
  async function init() {
    if (!token()) { destroy(); return; }
    const seq = ++initSeq;
    let next;
    try {
      next = await call("/api/ops-agent/capabilities");
    } catch (_) {
      // 401 / 403: not signed in, or a role without m2.assistant.use.
      if (seq === initSeq) destroy();
      return;
    }
    if (seq !== initSeq) return;
    if (root && caps && caps.role === next.role) return;  // already mounted for this role
    destroy(true);
    caps = next;
    render();
  }

  function destroy(keepThread) {
    if (root) {
      document.removeEventListener("mousedown", onOutside);
      document.removeEventListener("keydown", onEscape);
      root.remove();
      root = null;
    }
    caps = null; history = []; replay = null; thread = [];
    if (!keepThread) { try { sessionStorage.removeItem(THREAD_KEY); } catch (_) { /* ignore */ } }
  }

  return { init, destroy: () => destroy(false) };
})();
