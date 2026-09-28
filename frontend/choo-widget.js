/*!
 * Choo chat widget — animated train mascot launcher + chat panel.
 * Framework-free. Load once on the page where you want the bot.
 *
 * Optional config (set BEFORE this script loads):
 *   window.CHOO_CONFIG = {
 *     endpoint: '/svc/m1/chat',                 // your chat backend (via the gateway)
 *     left: 20, bottom: 20,                     // px from the viewport edge
 *     buildBody: function (text, sessionId) { return { message: text, session_id: sessionId }; },
 *     parseReply: function (data) { return data.reply; }
 *   };
 *
 * API: window.Choo.open(), window.Choo.close(), window.Choo.destroy()
 */
(function () {
  'use strict';
  if (window.Choo) return;

  var cfg = Object.assign({
    endpoint: '/svc/m1/chat',
    left: 20,
    right: null,  // set this (instead of/alongside left) to dock the widget to the right edge
    bottom: 20,
    size: 96,     // mascot/launcher width in px; the SVG scales proportionally
    greetings: ['Hi! 👋', 'ආයුබෝවන්! 👋', 'வணக்கம்! 👋'],
    welcome: "Hi, I'm Choo. Ask me about train times, fares, delays or bookings.",
    firstHelloDelay: 1000,   // ms before the first greeting burst
    helloStep: 2200,         // ms each language stays shown within one burst
    helloGap: 12000,         // ms fully hidden between bursts
    buildBody: null,
    parseReply: null
  }, window.CHOO_CONFIG || {});

  var onRight = cfg.right != null;
  var edge = onRight ? cfg.right : cfg.left;

  /* ---------- styles ---------- */
  var CSS = [
    '.choo-root{position:fixed;', (onRight ? 'right:' : 'left:'), edge, 'px;bottom:', cfg.bottom, 'px;width:', cfg.size, 'px;z-index:2147483000;',
    'font-family:system-ui,-apple-system,"Segoe UI","Noto Sans Sinhala","Noto Sans Tamil",sans-serif;font-size:15px;line-height:1.45;color:#14213D}',
    '.choo-root *{box-sizing:border-box}',
    '.choo-launch{display:block;width:', cfg.size, 'px;padding:0;border:0;background:none;cursor:pointer;border-radius:20px}',
    '.choo-launch:focus-visible{outline:3px solid #2F5BEA;outline-offset:4px}',
    '.choo-svg{display:block;width:100%;height:auto;overflow:visible}',
    '.choo-svg *{transform-origin:0 0}',

    /* idle motion */
    '.choo-bob{animation:choo-bob 2.4s ease-in-out infinite alternate}',
    '.choo-shadow{animation:choo-shadow 2.4s ease-in-out infinite alternate}',
    '@keyframes choo-bob{from{transform:translateY(0)}to{transform:translateY(-5px)}}',
    '@keyframes choo-shadow{from{transform:scaleX(1);opacity:.22}to{transform:scaleX(.9);opacity:.13}}',
    '.choo-eye{animation:choo-blink 4.2s infinite}',
    '@keyframes choo-blink{0%,90%,100%{transform:scaleY(1)}94%{transform:scaleY(.08)}}',
    '.choo-lamp{opacity:.2;animation:choo-lamp 2s ease-in-out infinite alternate}',
    '@keyframes choo-lamp{from{opacity:.15}to{opacity:.5}}',
    '.choo-dot{animation:choo-dot 1.4s ease-in-out infinite}',
    '.choo-d2{animation-delay:.2s}.choo-d3{animation-delay:.4s}',
    '@keyframes choo-dot{0%,60%,100%{opacity:.35;transform:scale(.8)}30%{opacity:1;transform:scale(1.25)}}',
    '.choo-puff{opacity:0;animation:choo-puff 2.6s ease-out infinite}',
    '.choo-p2{animation-delay:.87s}.choo-p3{animation-delay:1.73s}',
    '@keyframes choo-puff{0%{opacity:0;transform:translate(0,0) scale(.4)}20%{opacity:.95}100%{opacity:0;transform:translate(12px,-38px) scale(1.7)}}',

    /* hello: wave + talk + headlight flash (only while .is-hello) */
    '.choo-arm{transform:rotate(-8deg)}',
    '.choo-mouth{transform:scaleY(1)}',
    '.choo-flash{opacity:0}',
    '.is-hello .choo-arm{animation:choo-wave 4.5s ease-in-out both}',
    '.is-hello .choo-mouth{animation:choo-talk 4.5s both}',
    '.is-hello .choo-flash{animation:choo-flash 4.5s both}',
    '@keyframes choo-wave{0%{transform:rotate(-8deg)}6%{transform:rotate(-150deg)}12%{transform:rotate(-172deg)}20%{transform:rotate(-143deg)}',
    '28%{transform:rotate(-172deg)}36%{transform:rotate(-143deg)}44%{transform:rotate(-168deg)}52%{transform:rotate(-143deg)}',
    '60%{transform:rotate(-172deg)}72%,100%{transform:rotate(-8deg)}}',
    '@keyframes choo-talk{0%,60%,100%{transform:scaleY(1)}8%,24%,40%{transform:scaleY(1.6)}16%,32%,48%{transform:scaleY(1)}}',
    '@keyframes choo-flash{0%{opacity:0}4%{opacity:.9}8%{opacity:.1}12%{opacity:.9}18%,100%{opacity:0}}',

    /* greeting bubble */
    '.choo-hi{position:absolute;', (onRight ? 'right:0' : 'left:0'), ';bottom:calc(100% - 4px);padding:8px 14px;border-radius:16px;background:#fff;color:#14213D;',
    'font-weight:600;font-size:16px;white-space:nowrap;box-shadow:0 3px 0 rgba(20,33,61,.18),0 6px 18px rgba(20,33,61,.12);',
    'transform:scale(0);transform-origin:', (onRight ? 'calc(100% - 26px)' : '26px'), ' 100%;pointer-events:none}',
    '.choo-hi::after{content:"";position:absolute;', (onRight ? 'right:18px' : 'left:18px'), ';bottom:-8px;border:8px solid transparent;border-top-color:#fff;border-bottom:0}',
    '.is-hello .choo-hi{animation:choo-pop .5s both}',
    /* Pops in once at the start of a greeting burst and holds at scale(1)
       while showGreetingBurst() swaps the text underneath for each language;
       hiding is done in JS by removing is-hello at the end of the burst,
       which drops back to .choo-hi's base transform:scale(0). */
    '@keyframes choo-pop{0%{transform:scale(0)}60%{transform:scale(1.12)}100%{transform:scale(1)}}',
    '.is-open .choo-hi{display:none}',

    /* chat panel */
    '.choo-panel{position:absolute;', (onRight ? 'right:0' : 'left:0'), ';bottom:calc(100% + 8px);width:min(360px,calc(100vw - ', (edge * 2), 'px));',
    'height:min(480px,calc(100vh - 180px));display:flex;flex-direction:column;overflow:hidden;background:#fff;',
    'border-radius:20px;box-shadow:0 10px 40px rgba(20,33,61,.28);border:1px solid rgba(20,33,61,.12);',
    'transform-origin:', (onRight ? '100%' : '0'), ' 100%;animation:choo-open .18s ease-out}',
    '.choo-panel[hidden]{display:none}',
    '@keyframes choo-open{from{opacity:0;transform:scale(.92)}to{opacity:1;transform:scale(1)}}',
    '.choo-head{display:flex;align-items:center;gap:10px;padding:14px 16px;background:#2F5BEA;color:#fff}',
    '.choo-head b{display:block;font-size:16px;line-height:1.2}',
    '.choo-head small{display:flex;align-items:center;gap:6px;font-size:13px;opacity:.9}',
    '.choo-head small::before{content:"";width:8px;height:8px;border-radius:50%;background:#2BD48A}',
    '.choo-x{margin-left:auto;width:32px;height:32px;border:0;border-radius:50%;background:rgba(255,255,255,.18);color:#fff;font-size:20px;line-height:1;cursor:pointer}',
    '.choo-x:hover{background:rgba(255,255,255,.3)}',
    '.choo-x:focus-visible,.choo-send:focus-visible{outline:3px solid #FFB000;outline-offset:2px}',
    '.choo-msgs{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px;background:#F3F6FB}',
    '.choo-msg{max-width:84%;padding:9px 13px;border-radius:16px;white-space:pre-wrap;overflow-wrap:anywhere}',
    '.choo-bot{align-self:flex-start;background:#fff;border:1px solid rgba(20,33,61,.1);border-bottom-left-radius:5px}',
    '.choo-me{align-self:flex-end;background:#2F5BEA;color:#fff;border-bottom-right-radius:5px}',
    '.choo-err{color:#9B1C1C}',
    '.choo-typing{display:inline-flex;gap:4px;padding:12px 14px}',
    '.choo-typing i{width:7px;height:7px;border-radius:50%;background:#9AA8C2;animation:choo-dot 1.2s ease-in-out infinite}',
    '.choo-typing i:nth-child(2){animation-delay:.15s}.choo-typing i:nth-child(3){animation-delay:.3s}',
    '.choo-form{display:flex;gap:8px;padding:12px;border-top:1px solid rgba(20,33,61,.1);background:#fff}',
    '.choo-input{flex:1;min-width:0;padding:11px 14px;border:1.5px solid rgba(20,33,61,.25);border-radius:999px;font:inherit;color:#14213D;background:#fff}',
    '.choo-input:focus{outline:3px solid rgba(47,91,234,.35);border-color:#2F5BEA}',
    '.choo-send{padding:0 18px;border:0;border-radius:999px;background:#FFB000;color:#14213D;font:inherit;font-weight:600;cursor:pointer}',
    '.choo-send:disabled{opacity:.55;cursor:default}',

    '@media (prefers-reduced-motion:reduce){.choo-root *{animation:none!important}.is-hello .choo-hi{transform:scale(1)}}'
  ].join('');

  /* ---------- markup ---------- */
  var SVG =
    '<svg class="choo-svg" viewBox="84 20 206 240" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">' +
    '<g transform="translate(56 30)">' +
      '<g transform="translate(120 214)"><ellipse class="choo-shadow" rx="64" ry="7" fill="#14213D" opacity=".22"/></g>' +
      '<g class="choo-bob">' +
        '<g transform="translate(76 24)"><circle class="choo-puff choo-p1" r="5" fill="#fff" stroke="#B4C4DA" stroke-width="1"/></g>' +
        '<g transform="translate(76 24)"><circle class="choo-puff choo-p2" r="5" fill="#fff" stroke="#B4C4DA" stroke-width="1"/></g>' +
        '<g transform="translate(76 24)"><circle class="choo-puff choo-p3" r="5" fill="#fff" stroke="#B4C4DA" stroke-width="1"/></g>' +
        '<rect x="64" y="34" width="24" height="24" rx="4" fill="#14213D"/>' +
        '<rect x="58" y="28" width="36" height="9" rx="4.5" fill="#FFB000"/>' +
        '<circle class="choo-lamp" cx="150" cy="44" r="19" fill="#FFB000"/>' +
        '<rect x="140" y="46" width="20" height="12" rx="3" fill="#14213D"/>' +
        '<circle cx="150" cy="44" r="9" fill="#FFC53D"/>' +
        '<circle cx="147" cy="41" r="2.6" fill="#fff" opacity=".8"/>' +
        '<rect x="52" y="54" width="136" height="132" rx="38" fill="#2F5BEA"/>' +
        '<path d="M66 96 Q66 68 94 62" fill="none" stroke="#fff" stroke-opacity=".28" stroke-width="5" stroke-linecap="round"/>' +
        '<rect x="54" y="150" width="132" height="8" fill="#FFB000"/>' +
        '<rect x="68" y="72" width="104" height="68" rx="26" fill="#0D1836"/>' +
        '<circle cx="88" cy="122" r="5.5" fill="#FF8FA3" opacity=".55"/>' +
        '<circle cx="152" cy="122" r="5.5" fill="#FF8FA3" opacity=".55"/>' +
        '<g transform="translate(100 104)"><g class="choo-eye"><ellipse rx="8.5" ry="11" fill="#7DF0FF"/><circle cx="-2.5" cy="-4" r="2.4" fill="#fff"/></g></g>' +
        '<g transform="translate(140 104)"><g class="choo-eye"><ellipse rx="8.5" ry="11" fill="#7DF0FF"/><circle cx="-2.5" cy="-4" r="2.4" fill="#fff"/></g></g>' +
        '<g transform="translate(120 123)"><path class="choo-mouth" d="M-14 0 Q0 10 14 0" fill="none" stroke="#7DF0FF" stroke-width="4.5" stroke-linecap="round"/></g>' +
        '<circle class="choo-flash" cx="72" cy="171" r="18" fill="#FFE08A"/>' +
        '<circle class="choo-flash" cx="168" cy="171" r="18" fill="#FFE08A"/>' +
        '<circle cx="72" cy="171" r="9" fill="#FFF3C4" stroke="#FFB000" stroke-width="3"/>' +
        '<circle cx="168" cy="171" r="9" fill="#FFF3C4" stroke="#FFB000" stroke-width="3"/>' +
        '<rect x="96" y="163" width="48" height="16" rx="8" fill="#0D1836"/>' +
        '<g transform="translate(108 171)"><circle class="choo-dot" r="3" fill="#2BD48A"/></g>' +
        '<g transform="translate(120 171)"><circle class="choo-dot choo-d2" r="3" fill="#2BD48A"/></g>' +
        '<g transform="translate(132 171)"><circle class="choo-dot choo-d3" r="3" fill="#2BD48A"/></g>' +
        '<rect x="44" y="184" width="152" height="16" rx="8" fill="#14213D"/>' +
        '<polygon points="66,184 76,184 70,200 60,200" fill="#FFB000"/>' +
        '<polygon points="88,184 98,184 92,200 82,200" fill="#FFB000"/>' +
        '<polygon points="110,184 120,184 114,200 104,200" fill="#FFB000"/>' +
        '<polygon points="132,184 142,184 136,200 126,200" fill="#FFB000"/>' +
        '<polygon points="154,184 164,184 158,200 148,200" fill="#FFB000"/>' +
        '<g transform="translate(52 118) rotate(8)">' +
          '<rect x="-6" y="0" width="12" height="40" rx="6" fill="#1E3FB0"/>' +
          '<rect x="-7.5" y="33" width="15" height="7" rx="3.5" fill="#14213D"/>' +
          '<circle cx="0" cy="47" r="13" fill="#FFB000"/>' +
          '<ellipse cx="11" cy="44" rx="5" ry="7.5" fill="#FFB000" transform="rotate(-20 11 44)"/>' +
          '<circle r="8" fill="#1E3FB0"/>' +
        '</g>' +
        '<g transform="translate(188 118)"><g class="choo-arm">' +
          '<rect x="-6" y="0" width="12" height="40" rx="6" fill="#1E3FB0"/>' +
          '<rect x="-7.5" y="33" width="15" height="7" rx="3.5" fill="#14213D"/>' +
          '<circle cx="0" cy="47" r="13" fill="#FFB000"/>' +
          '<ellipse cx="-11" cy="44" rx="5" ry="7.5" fill="#FFB000" transform="rotate(20 -11 44)"/>' +
          '<circle r="8" fill="#1E3FB0"/>' +
        '</g></g>' +
      '</g>' +
    '</g></svg>';

  var styleEl = document.createElement('style');
  styleEl.id = 'choo-style';
  styleEl.textContent = CSS;
  document.head.appendChild(styleEl);

  var root = document.createElement('div');
  root.className = 'choo-root';
  root.id = 'choo-root';
  root.innerHTML =
    '<div class="choo-panel" id="choo-panel" role="dialog" aria-label="Choo, railway assistant" hidden>' +
      '<div class="choo-head"><div><b>Choo</b><small>Railway assistant</small></div>' +
        '<button type="button" class="choo-x" aria-label="Close chat">&times;</button></div>' +
      '<div class="choo-msgs" role="log" aria-live="polite"></div>' +
      '<form class="choo-form" autocomplete="off">' +
        '<input class="choo-input" type="text" name="message" placeholder="Type your message" aria-label="Message" maxlength="1000">' +
        '<button class="choo-send" type="submit">Send</button>' +
      '</form>' +
    '</div>' +
    '<div class="choo-hi" aria-hidden="true"></div>' +
    '<button type="button" class="choo-launch" aria-label="Chat with Choo" aria-expanded="false" aria-controls="choo-panel">' + SVG + '</button>';
  document.body.appendChild(root);

  var $ = function (s) { return root.querySelector(s); };
  var panel = $('.choo-panel'), msgs = $('.choo-msgs'), form = $('.choo-form'),
      input = $('.choo-input'), sendBtn = $('.choo-send'), launch = $('.choo-launch'),
      hi = $('.choo-hi');

  /* ---------- hello (wave + bubble): shows every language once in sequence
     ("a burst"), then hides completely for helloGap ms, then bursts again -
     forever, until the panel is opened or the widget is destroyed. ---------- */
  var helloTimer = null, firstTimer = null;

  function showGreetingBurst() {
    if (root.classList.contains('is-open') || root.classList.contains('is-hello')) {
      helloTimer = setTimeout(showGreetingBurst, cfg.helloGap);
      return;
    }
    var idx = 0;
    root.classList.add('is-hello');
    (function showStep() {
      hi.textContent = cfg.greetings[idx];
      idx++;
      if (idx < cfg.greetings.length) {
        helloTimer = setTimeout(showStep, cfg.helloStep);
      } else {
        helloTimer = setTimeout(function () {
          root.classList.remove('is-hello');
          helloTimer = setTimeout(showGreetingBurst, cfg.helloGap);
        }, cfg.helloStep);
      }
    })();
  }
  firstTimer = setTimeout(showGreetingBurst, cfg.firstHelloDelay);
  launch.addEventListener('mouseenter', function () {
    if (!root.classList.contains('is-open') && !root.classList.contains('is-hello')) {
      clearTimeout(helloTimer);
      showGreetingBurst();
    }
  });

  /* ---------- chat ---------- */
  var sessionId;
  try {
    sessionId = localStorage.getItem('choo_session');
    if (!sessionId) {
      sessionId = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2);
      localStorage.setItem('choo_session', sessionId);
    }
  } catch (e) { sessionId = String(Date.now()); }

  function addMsg(text, kind) {
    var el = document.createElement('div');
    el.className = 'choo-msg ' + (kind === 'me' ? 'choo-me' : 'choo-bot') + (kind === 'err' ? ' choo-err' : '');
    el.textContent = text;
    msgs.appendChild(el);
    msgs.scrollTop = msgs.scrollHeight;
    return el;
  }
  function addTyping() {
    var el = document.createElement('div');
    el.className = 'choo-msg choo-bot choo-typing';
    el.setAttribute('aria-label', 'Choo is typing');
    el.innerHTML = '<i></i><i></i><i></i>';
    msgs.appendChild(el);
    msgs.scrollTop = msgs.scrollHeight;
    return el;
  }
  function defaultParse(d, depth) {
    depth = depth || 0;
    if (typeof d === 'string') return d;
    if (d && typeof d === 'object' && depth < 3) {
      var keys = ['reply', 'response', 'answer', 'message', 'text', 'output', 'data'];
      for (var i = 0; i < keys.length; i++) {
        if (d[keys[i]] != null) { var r = defaultParse(d[keys[i]], depth + 1); if (r) return r; }
      }
    }
    return d ? JSON.stringify(d) : '';
  }

  var welcomed = false;
  function open() {
    root.classList.remove('is-hello');
    root.classList.add('is-open');
    panel.hidden = false;
    launch.setAttribute('aria-expanded', 'true');
    if (!welcomed) { addMsg(cfg.welcome, 'bot'); welcomed = true; }
    setTimeout(function () { input.focus(); }, 30);
  }
  function close() {
    root.classList.remove('is-open');
    panel.hidden = true;
    launch.setAttribute('aria-expanded', 'false');
    launch.focus();
  }
  launch.addEventListener('click', function () { panel.hidden ? open() : close(); });
  $('.choo-x').addEventListener('click', close);
  function onKey(e) { if (e.key === 'Escape' && !panel.hidden) close(); }
  document.addEventListener('keydown', onKey);

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || sendBtn.disabled) return;
    input.value = '';
    addMsg(text, 'me');
    sendBtn.disabled = true;
    var typing = addTyping();

    var body = cfg.buildBody ? cfg.buildBody(text, sessionId) : { message: text, session_id: sessionId };
    var ctrl = new AbortController();
    var to = setTimeout(function () { ctrl.abort(); }, 30000);

    fetch(cfg.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal
    })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.text();
      })
      .then(function (raw) {
        var data; try { data = JSON.parse(raw); } catch (_) { data = raw; }
        var reply = cfg.parseReply ? cfg.parseReply(data) : defaultParse(data);
        typing.remove();
        addMsg(reply || 'Sorry, I did not get a reply. Please try again.', reply ? 'bot' : 'err');
      })
      .catch(function () {
        typing.remove();
        addMsg("Sorry, I can't reach the assistant right now. Please try again in a moment.", 'err');
      })
      .then(function () {
        clearTimeout(to);
        sendBtn.disabled = false;
        input.focus();
      });
  });

  /* ---------- public API ---------- */
  window.Choo = {
    open: open,
    close: close,
    destroy: function () {
      clearTimeout(firstTimer); clearTimeout(helloTimer);
      document.removeEventListener('keydown', onKey);
      root.remove(); styleEl.remove();
      delete window.Choo;
    }
  };
})();
