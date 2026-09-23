/* RailSense AI — verified incident map (shared).
 *
 * Served by M2 at /shared/incident-map.js and used by three pages:
 *   - Control Room dashboard      (M2 :8005 /)
 *   - Admin Console incidents     (M2 :8005 /admin)
 *   - Passenger home page         (gateway :3000 /user)
 *
 * Reads GET /api/incidents/map-feed, which only ever returns VERIFIED
 * incidents with allowlisted fields. The client re-checks status too, and each
 * poll REPLACES the marker set, so an incident that is later rejected or
 * edited back to unverified disappears on the next cycle.
 *
 * Leaflet is loaded on demand from cdnjs. If it (or the map tiles) cannot load,
 * the card degrades to a plain list of verified incidents rather than failing.
 */
(function (global) {
  'use strict';

  var LEAFLET_VERSION = '1.9.4';
  var LEAFLET_BASE = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/' + LEAFLET_VERSION + '/';
  var SRI_LANKA_BOUNDS = [[5.85, 79.55], [9.9, 81.95]];

  // One palette for every incident surface (map markers, legends and the
  // Control Room "Cause of delay" chart), so a type always has one colour.
  var TYPE_STYLES = {
    signal_fault:      { color: '#F59E0B', glyph: '🚦', label: 'Signal fault' },
    mechanical:        { color: '#EF4444', glyph: '⚙',  label: 'Mechanical' },
    weather:           { color: '#3B82F6', glyph: '🌧', label: 'Weather' },
    track_obstruction: { color: '#A855F7', glyph: '⛔', label: 'Track obstruction' },
    staffing:          { color: '#14B8A6', glyph: '👷', label: 'Staffing' },
    other:             { color: '#94A3B8', glyph: '•',  label: 'Other' }
  };

  // Standard OpenStreetMap tiles: no API key. Dark mode is a CSS filter on
  // the tile pane (see .rs-imap.dark below), so markers keep their colours.
  var TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  var TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

  function styleFor(type) { return TYPE_STYLES[type] || TYPE_STYLES.other; }

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function relativeTime(iso) {
    if (!iso) return 'time unknown';
    var t = new Date(iso).getTime();
    if (isNaN(t)) return 'time unknown';
    var s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 45) return 'just now';
    var m = Math.round(s / 60);
    if (m < 60) return m + ' min ago';
    var h = Math.round(m / 60);
    if (h < 24) return h + (h === 1 ? ' hour ago' : ' hours ago');
    var d = Math.round(h / 24);
    return d + (d === 1 ? ' day ago' : ' days ago');
  }

  /* ------------------------------ Leaflet loader ------------------------------ */
  var leafletPromise = null;
  function ensureLeaflet() {
    if (global.L && global.L.map) return Promise.resolve(global.L);
    if (leafletPromise) return leafletPromise;
    leafletPromise = new Promise(function (resolve, reject) {
      var css = document.createElement('link');
      css.rel = 'stylesheet';
      css.href = LEAFLET_BASE + 'leaflet.min.css';
      document.head.appendChild(css);
      var js = document.createElement('script');
      js.src = LEAFLET_BASE + 'leaflet.min.js';
      js.onload = function () { global.L ? resolve(global.L) : reject(new Error('Leaflet missing')); };
      js.onerror = function () { leafletPromise = null; reject(new Error('Leaflet unavailable')); };
      document.head.appendChild(js);
    });
    return leafletPromise;
  }

  /* ---------------------------------- styles ---------------------------------- */
  function injectStyles() {
    if (document.getElementById('rs-incident-map-styles')) return;
    var st = document.createElement('style');
    st.id = 'rs-incident-map-styles';
    st.textContent = [
      '.rs-imap{position:relative;width:100%;height:100%;min-height:260px;border-radius:14px;overflow:hidden;background:#0B1220;font-family:inherit}',
      '.rs-imap.light{background:#EEF2F7}',
      '.rs-imap-canvas{position:absolute;inset:0;z-index:1}',
      '.rs-imap .leaflet-container{background:transparent;font-family:inherit}',
      '.rs-imap.dark .leaflet-tile-pane{filter:invert(1) hue-rotate(185deg) brightness(.82) contrast(.92) saturate(.55)}',
      '.rs-imap.dark .leaflet-control-attribution{background:rgba(8,14,28,.7);color:#94A3B8}',
      '.rs-imap.dark .leaflet-control-attribution a{color:#93C5FD}',
      '.rs-imap-status{position:absolute;top:10px;right:10px;z-index:500;display:flex;align-items:center;gap:6px;padding:5px 10px;border-radius:99px;font:700 10.5px/1 system-ui,sans-serif;letter-spacing:.04em;background:rgba(8,14,28,.78);color:#E2E8F0;backdrop-filter:blur(8px);border:1px solid rgba(148,163,184,.25)}',
      '.rs-imap.light .rs-imap-status{background:rgba(255,255,255,.88);color:#1E293B;border-color:rgba(100,116,139,.25)}',
      '.rs-imap-dot{width:7px;height:7px;border-radius:50%;background:#22C55E;box-shadow:0 0 0 0 rgba(34,197,94,.6);animation:rs-imap-live 1.8s infinite}',
      '.rs-imap-status.stale .rs-imap-dot{background:#F59E0B;animation:none}',
      '@keyframes rs-imap-live{70%{box-shadow:0 0 0 7px rgba(34,197,94,0)}100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}',
      '.rs-imap-legend{position:absolute;bottom:10px;left:10px;z-index:500;display:flex;flex-wrap:wrap;gap:4px 10px;max-width:calc(100% - 20px);padding:7px 10px;border-radius:10px;font:600 10.5px/1.3 system-ui,sans-serif;background:rgba(8,14,28,.78);color:#CBD5E1;backdrop-filter:blur(8px);border:1px solid rgba(148,163,184,.2)}',
      '.rs-imap.light .rs-imap-legend{background:rgba(255,255,255,.9);color:#334155;border-color:rgba(100,116,139,.2)}',
      '.rs-imap-legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:-1px}',
      '.rs-imap-empty{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:450;padding:9px 14px;border-radius:12px;font:600 12px/1.4 system-ui,sans-serif;text-align:center;background:rgba(8,14,28,.72);color:#CBD5E1;pointer-events:none}',
      '.rs-imap.light .rs-imap-empty{background:rgba(255,255,255,.88);color:#475569}',
      '.rs-imap-pin{position:relative;width:30px;height:30px}',
      '.rs-imap-pin b{position:absolute;inset:3px;display:flex;align-items:center;justify-content:center;border-radius:50%;font-size:13px;line-height:1;color:#fff;border:2px solid #fff;box-shadow:0 3px 10px rgba(0,0,0,.35)}',
      '.rs-imap-pin.new b{animation:rs-imap-drop .6s cubic-bezier(.2,1.5,.4,1) both}',
      '.rs-imap-pin.recent:before{content:"";position:absolute;inset:0;border-radius:50%;background:var(--c);opacity:.45;animation:rs-imap-pulse 2s ease-out infinite}',
      '@keyframes rs-imap-drop{from{transform:translateY(-22px) scale(.4);opacity:0}to{transform:none;opacity:1}}',
      '@keyframes rs-imap-pulse{from{transform:scale(.8);opacity:.5}to{transform:scale(2.3);opacity:0}}',
      '.rs-imap-pop{min-width:190px;max-width:240px;font:13px/1.45 system-ui,sans-serif;color:#0F172A}',
      '.rs-imap-pop h4{margin:0 0 2px;font-size:14px}',
      '.rs-imap-pop .t{display:inline-block;margin:3px 0 6px;padding:2px 8px;border-radius:99px;font-size:10.5px;font-weight:700;color:#fff}',
      '.rs-imap-pop p{margin:0 0 6px}',
      '.rs-imap-pop small{color:#64748B}',
      '.rs-imap-list{position:absolute;inset:0;overflow:auto;padding:44px 12px 12px;font:12.5px/1.45 system-ui,sans-serif;color:#CBD5E1}',
      '.rs-imap.light .rs-imap-list{color:#334155}',
      '.rs-imap-list div{padding:7px 0;border-bottom:1px solid rgba(148,163,184,.2)}',
      '@media (prefers-reduced-motion:reduce){.rs-imap-dot,.rs-imap-pin b,.rs-imap-pin.recent:before{animation:none!important}}'
    ].join('\n');
    document.head.appendChild(st);
  }

  /* ---------------------------------- widget ---------------------------------- */
  function create(container, options) {
    options = options || {};
    var feedUrl = options.feedUrl || '/api/incidents/map-feed';
    var pollMs = options.pollMs || 5000;
    var theme = options.theme === 'light' ? 'light' : 'dark';

    injectStyles();
    container.innerHTML = '';
    var root = document.createElement('div');
    root.className = 'rs-imap ' + theme;
    root.innerHTML =
      '<div class="rs-imap-canvas"></div>' +
      '<div class="rs-imap-status"><span class="rs-imap-dot"></span><span class="rs-imap-status-text">Connecting…</span></div>' +
      '<div class="rs-imap-legend">' + Object.keys(TYPE_STYLES).map(function (k) {
        return '<span><i style="background:' + TYPE_STYLES[k].color + '"></i>' + esc(TYPE_STYLES[k].label) + '</span>';
      }).join('') + '</div>';
    container.appendChild(root);

    var canvas = root.querySelector('.rs-imap-canvas');
    var statusEl = root.querySelector('.rs-imap-status');
    var statusText = root.querySelector('.rs-imap-status-text');
    var L = null, map = null, tileLayer = null;
    var markers = {};          // id -> { marker, item }
    var lastItems = [];
    var firstRender = true;
    var timer = null, destroyed = false, inFlight = false;
    var emptyEl = null, listEl = null;

    function popupHtml(item) {
      var s = styleFor(item.incident_type);
      return '<div class="rs-imap-pop">' +
        '<h4>' + esc(item.station) + '</h4>' +
        '<span class="t" style="background:' + s.color + '">' + esc(s.label) + '</span>' +
        '<p>' + esc(item.summary || 'No summary provided.') + '</p>' +
        '<small>Train <b>' + esc(item.train_id || '—') + '</b> · verified ' + esc(relativeTime(item.verified_at)) + '</small>' +
        '</div>';
    }

    function iconFor(item, isNew) {
      var s = styleFor(item.incident_type);
      var recent = item.verified_at && (Date.now() - new Date(item.verified_at).getTime()) < 30 * 60 * 1000;
      return L.divIcon({
        className: '',
        iconSize: [30, 30], iconAnchor: [15, 15], popupAnchor: [0, -14],
        html: '<div class="rs-imap-pin' + (isNew ? ' new' : '') + (recent ? ' recent' : '') + '" style="--c:' + s.color + '">' +
              '<b style="background:' + s.color + '">' + s.glyph + '</b></div>'
      });
    }

    function setEmpty(text) {
      if (!text) { if (emptyEl) { emptyEl.remove(); emptyEl = null; } return; }
      if (!emptyEl) { emptyEl = document.createElement('div'); emptyEl.className = 'rs-imap-empty'; root.appendChild(emptyEl); }
      emptyEl.textContent = text;
    }

    // Multiple verified incidents at one station would sit on top of each
    // other; fan them out slightly so every marker stays clickable.
    function offsetPositions(items) {
      var seen = {};
      return items.map(function (it) {
        var key = it.lat + ',' + it.lon;
        var n = seen[key] = (seen[key] || 0) + 1;
        if (n === 1) return [it.lat, it.lon];
        var angle = n * 2.4, r = 0.012 * Math.sqrt(n);
        return [it.lat + r * Math.sin(angle), it.lon + r * Math.cos(angle)];
      });
    }

    function renderMarkers(items) {
      var positions = offsetPositions(items);
      var keep = {};
      items.forEach(function (item, i) {
        keep[item.id] = true;
        var existing = markers[item.id];
        if (existing) {
          existing.marker.setLatLng(positions[i]);
          existing.marker.setIcon(iconFor(item, false));
          existing.marker.setPopupContent(popupHtml(item));
          existing.item = item;
        } else {
          var marker = L.marker(positions[i], { icon: iconFor(item, !firstRender), riseOnHover: true })
            .bindPopup(popupHtml(item))
            .addTo(map);
          markers[item.id] = { marker: marker, item: item };
        }
      });
      Object.keys(markers).forEach(function (id) {
        if (!keep[id]) { map.removeLayer(markers[id].marker); delete markers[id]; }
      });
      firstRender = false;
    }

    function renderList(items) {
      if (!listEl) { listEl = document.createElement('div'); listEl.className = 'rs-imap-list'; root.appendChild(listEl); }
      listEl.innerHTML = items.length ? items.map(function (it) {
        var s = styleFor(it.incident_type);
        return '<div><b style="color:' + s.color + '">' + s.glyph + ' ' + esc(s.label) + '</b> — ' + esc(it.station) +
          ' <small>(' + esc(it.train_id || '—') + ', ' + esc(relativeTime(it.verified_at)) + ')</small><br>' + esc(it.summary) + '</div>';
      }).join('') : '';
    }

    function render(feed) {
      // Defence in depth: the server only sends VERIFIED rows, and the client
      // refuses anything else, so nothing unapproved can flash onto a map.
      var items = (feed.incidents || []).filter(function (it) {
        return it && it.status === 'VERIFIED' && typeof it.lat === 'number' && typeof it.lon === 'number';
      });
      lastItems = items;
      if (map) renderMarkers(items); else renderList(items);
      var note = feed.stale ? 'Offline · last known' : feed.offline ? 'Live · local data' : 'Live';
      statusText.textContent = note + ' · ' + items.length + ' verified today';
      statusEl.classList.toggle('stale', !!feed.stale);
      setEmpty(items.length ? '' : 'No incidents verified today');
      if (typeof options.onUpdate === 'function') options.onUpdate(items, feed);
    }

    function poll() {
      if (destroyed || inFlight) return;
      inFlight = true;
      fetch(feedUrl, { cache: 'no-store' })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(render)
        .catch(function () {
          // Keep the last markers on screen; just flag that they may be stale.
          statusText.textContent = 'Offline · last known · ' + lastItems.length + ' verified today';
          statusEl.classList.add('stale');
        })
        .then(function () { inFlight = false; });
    }

    function start() {
      poll();
      timer = setInterval(function () { if (!document.hidden) poll(); }, pollMs);
    }
    function onVisible() { if (!document.hidden) poll(); }
    document.addEventListener('visibilitychange', onVisible);

    ensureLeaflet().then(function (leaflet) {
      if (destroyed) return;
      L = leaflet;
      map = L.map(canvas, { zoomControl: true, attributionControl: true, scrollWheelZoom: options.scrollWheelZoom !== false,
                            minZoom: 6, zoomSnap: 0.25, maxBounds: [[4.5, 78.5], [11, 83]] });
      map.fitBounds(SRI_LANKA_BOUNDS);
      tileLayer = L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom: 18 }).addTo(map);
      if (listEl) { listEl.remove(); listEl = null; }
      if (typeof ResizeObserver !== 'undefined') new ResizeObserver(function () { map.invalidateSize(); }).observe(root);
      if (lastItems.length) renderMarkers(lastItems);
    }).catch(function () {
      statusText.textContent = 'Map unavailable · list view';
    }).then(start);

    return {
      refresh: poll,
      setTheme: function (next) {
        theme = next === 'light' ? 'light' : 'dark';
        root.className = 'rs-imap ' + theme;
      },
      destroy: function () {
        destroyed = true;
        clearInterval(timer);
        document.removeEventListener('visibilitychange', onVisible);
        if (map) map.remove();
        container.innerHTML = '';
      }
    };
  }

  global.RailSenseIncidentMap = { create: create, TYPE_STYLES: TYPE_STYLES, relativeTime: relativeTime };
})(window);
