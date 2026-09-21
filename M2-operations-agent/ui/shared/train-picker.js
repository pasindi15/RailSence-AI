/* RailSense AI — searchable train picker (shared).
 *
 * Staff filing an incident rarely remember a train id, but they do remember
 * "Podi Menike" or "the Kandy train". This turns a plain text input into a
 * combobox over GET /api/trains:
 *   - empty query  -> named passenger services, those serving the chosen
 *                     station first, then other trains seen at that station
 *   - typed query  -> matches on name, id or route across every train
 * The input shows "Podi Menike · 1005"; picker.value is the train id.
 *
 * Used by the Control Room and Admin Console incident forms.
 */
(function (global) {
  'use strict';

  var catalogPromise = null;
  function loadCatalog(url) {
    if (!catalogPromise) {
      catalogPromise = fetch(url).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      }).catch(function (err) { catalogPromise = null; throw err; });
    }
    return catalogPromise;
  }

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function injectStyles() {
    if (document.getElementById('rs-train-picker-styles')) return;
    var st = document.createElement('style');
    st.id = 'rs-train-picker-styles';
    st.textContent = [
      '.rs-tp{position:relative}',
      '.rs-tp-list{margin-top:4px;max-height:240px;overflow-y:auto;',
      '  border-radius:10px;border:1px solid var(--border-hi,rgba(96,165,250,.5));background:var(--card-hi,#16203a);',
      '  box-shadow:0 10px 26px rgba(0,0,0,.30);padding:4px;display:none}',
      '.rs-tp.open .rs-tp-list{display:block}',
      '.rs-tp-head{padding:8px 10px 4px;font:700 10px/1.2 system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--muted,#8291a8)}',
      '.rs-tp-opt{display:flex;justify-content:space-between;gap:10px;align-items:baseline;padding:8px 10px;border-radius:7px;cursor:pointer;color:var(--ink-bright,#fff)}',
      '.rs-tp-opt.active,.rs-tp-opt:hover{background:var(--brand-tint,rgba(59,130,246,.16))}',
      '.rs-tp-opt b{font-weight:700;font-size:13px}',
      '.rs-tp-opt code{font:600 11.5px "Share Tech Mono",ui-monospace,monospace;color:var(--brand-light,#60a5fa);margin-left:6px}',
      '.rs-tp-opt small{font-size:11px;color:var(--muted,#8291a8);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:48%}',
      '.rs-tp-empty{padding:12px 10px;font-size:12px;color:var(--muted,#8291a8)}',
      '.rs-tp-hint{margin-top:5px;font-size:11px;color:var(--muted,#8291a8)}',
      '.rs-tp-hint.ok{color:var(--sig-g,var(--success,#10b981))}'
    ].join('\n');
    document.head.appendChild(st);
  }

  function attach(input, options) {
    options = options || {};
    var url = options.trainsUrl || '/api/trains';
    var getStation = options.getStation || function () { return ''; };
    injectStyles();

    var wrap = document.createElement('div');
    wrap.className = 'rs-tp';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var list = document.createElement('div');
    list.className = 'rs-tp-list';
    list.setAttribute('role', 'listbox');
    wrap.appendChild(list);
    var hint = document.createElement('div');
    hint.className = 'rs-tp-hint';
    wrap.parentNode.insertBefore(hint, wrap.nextSibling);

    input.setAttribute('autocomplete', 'off');
    input.setAttribute('role', 'combobox');
    input.placeholder = 'Search by train name, number or route…';

    var catalog = null, options_ = [], active = -1, selected = null;

    function servesStation(t, station) {
      if (!station) return false;
      var stations = catalog.corridor_stations[t.corridor || t.route] || [];
      return stations.indexOf(station) >= 0 || String(t.route || '').indexOf(station) >= 0;
    }

    function label(t) { return t.name ? t.name + ' · ' + t.train_id : t.train_id; }

    function compute(query) {
      var station = getStation();
      var trains = catalog.trains;
      var q = query.trim().toLowerCase();
      var groups = [];
      if (!q) {
        var named = trains.filter(function (t) { return t.name; });
        named.sort(function (a, b) { return servesStation(b, station) - servesStation(a, station); });
        groups.push({ title: station ? 'Passenger services · via ' + station + ' first' : 'Passenger services', items: named });
        if (station) {
          var local = trains.filter(function (t) { return !t.name && servesStation(t, station); }).slice(0, 25);
          if (local.length) groups.push({ title: 'Other trains on the ' + station + ' line', items: local });
        }
      } else {
        var terms = q.split(/\s+/);
        var hits = trains.filter(function (t) {
          var hay = (t.train_id + ' ' + (t.name || '') + ' ' + (t.route || '')).toLowerCase();
          return terms.every(function (term) { return hay.indexOf(term) >= 0; });
        });
        hits.sort(function (a, b) {
          var ea = a.train_id.toLowerCase() === q, eb = b.train_id.toLowerCase() === q;
          if (ea !== eb) return eb - ea;
          if (!!a.name !== !!b.name) return (b.name ? 1 : 0) - (a.name ? 1 : 0);
          return servesStation(b, station) - servesStation(a, station);
        });
        groups.push({ title: hits.length > 40 ? 'Top 40 of ' + hits.length + ' matches' : hits.length + ' match' + (hits.length === 1 ? '' : 'es'),
                      items: hits.slice(0, 40) });
      }
      return groups;
    }

    function render() {
      if (!catalog) { list.innerHTML = '<div class="rs-tp-empty">Loading trains…</div>'; return; }
      var groups = compute(selected && input.value === label(selected) ? '' : input.value);
      options_ = [];
      var html = '';
      groups.forEach(function (g) {
        if (!g.items.length) return;
        html += '<div class="rs-tp-head">' + esc(g.title) + '</div>';
        g.items.forEach(function (t) {
          var i = options_.push(t) - 1;
          html += '<div class="rs-tp-opt" role="option" data-i="' + i + '"><span><b>' + esc(t.name || 'Train') + '</b><code>' +
            esc(t.train_id) + '</code></span><small>' + esc(t.route || '') + '</small></div>';
        });
      });
      list.innerHTML = html || '<div class="rs-tp-empty">No train matches “' + esc(input.value) + '”.</div>';
      active = -1;
    }

    function setActive(i) {
      var opts = list.querySelectorAll('.rs-tp-opt');
      if (!opts.length) return;
      active = (i + opts.length) % opts.length;
      opts.forEach(function (o, k) { o.classList.toggle('active', k === active); });
      opts[active].scrollIntoView({ block: 'nearest' });
    }

    function choose(t) {
      selected = t;
      input.value = label(t);
      input.setCustomValidity('');
      hint.textContent = 'Selected train ' + t.train_id + (t.route ? ' · ' + t.route : '');
      hint.className = 'rs-tp-hint ok';
      close();
      if (typeof options.onSelect === 'function') options.onSelect(t);
    }

    function open() {
      wrap.classList.add('open');
      if (!catalog) {
        render();
        loadCatalog(url).then(function (c) { catalog = c; if (wrap.classList.contains('open')) render(); })
          .catch(function () { list.innerHTML = '<div class="rs-tp-empty">Train list unavailable. Type the exact train id.</div>'; });
      } else {
        render();
      }
    }
    function close() { wrap.classList.remove('open'); }

    // A typed exact id (e.g. from a field radio call) still resolves.
    function resolveTyped() {
      if (!catalog || (selected && input.value === label(selected))) return;
      var v = input.value.trim().toLowerCase();
      var match = catalog.trains.filter(function (t) { return t.train_id.toLowerCase() === v; })[0];
      if (match) { choose(match); return; }
      selected = null;
      hint.textContent = input.value.trim() ? 'Pick a train from the list.' : '';
      hint.className = 'rs-tp-hint';
    }

    input.addEventListener('focus', open);
    input.addEventListener('click', open);
    input.addEventListener('input', function () { selected = null; hint.textContent = ''; open(); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); if (!wrap.classList.contains('open')) open(); setActive(active + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(active - 1); }
      else if (e.key === 'Enter' && wrap.classList.contains('open') && active >= 0) { e.preventDefault(); choose(options_[active]); }
      else if (e.key === 'Escape' && wrap.classList.contains('open')) { e.stopPropagation(); close(); }
    });
    input.addEventListener('blur', function () { setTimeout(function () { close(); resolveTyped(); }, 150); });
    list.addEventListener('mousedown', function (e) {
      var opt = e.target.closest('.rs-tp-opt');
      if (opt) { e.preventDefault(); choose(options_[Number(opt.dataset.i)]); }
    });

    loadCatalog(url).then(function (c) { catalog = c; }).catch(function () {});

    return {
      get value() {
        if (!catalog) return input.value.trim();  // list unavailable: accept a typed id
        if (selected && input.value === label(selected)) return selected.train_id;
        return '';
      },
      // Station changed: re-rank if the list is showing.
      refresh: function () { if (wrap.classList.contains('open')) render(); },
      reset: function () { selected = null; input.value = ''; hint.textContent = ''; hint.className = 'rs-tp-hint'; close(); },
      validate: function () {
        if (!catalog) return !!input.value.trim();
        resolveTyped();
        var ok = !!(selected && input.value === label(selected));
        input.setCustomValidity(ok ? '' : 'Choose a train from the list');
        return ok;
      }
    };
  }

  global.RailSenseTrainPicker = { attach: attach };
})(window);
