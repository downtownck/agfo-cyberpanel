/* AGFO Firewall AI - istemci */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var CSRF = '', STATE = {}, DASH = {}, PROPS = [];

  /* ---------------- yardimcilar ---------------- */
  function toast(msg, ms) {
    var el = $('toast'); el.textContent = msg; el.hidden = false;
    clearTimeout(el._t); el._t = setTimeout(function () { el.hidden = true; }, ms || 3000);
  }
  function show(id, msg, ok) {
    var el = $(id); if (!el) return;
    if (!msg) { el.hidden = true; el.textContent = ''; return; }
    el.classList.toggle('ok', !!ok); el.textContent = msg; el.hidden = false;
  }
  function esc(s) { return String(s === null || s === undefined ? '' : s); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function api(path, body) {
    var opts = { method: body ? 'POST' : 'GET', headers: { Accept: 'application/json' }, credentials: 'same-origin' };
    if (body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-AGFO-CSRF'] = CSRF;
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (res.status === 401 && path !== '/api/login') { logoutUi(); throw new Error('Oturum süresi doldu'); }
        if (!res.ok || data.ok === false) {
          var map = {
            bad_password: 'Şifre hatalı.', locked: 'Çok fazla hatalı deneme, bir süre bekleyin.',
            csrf: 'Oturum doğrulaması başarısız, sayfayı yenileyin.',
            auth_required: 'Oturum gerekli.', too_short: 'Şifre en az 10 karakter olmalı.',
            ip_not_allowed: 'IP adresiniz izinli listede değil.',
            no_password_configured: 'Panel şifresi tanımlı değil.'
          };
          throw new Error(map[data.error] || data.error || ('HTTP ' + res.status));
        }
        return data;
      });
    });
  }
  function logoutUi() { $('app').hidden = true; $('login').hidden = false; }

  /* ---------------- durum panosu ---------------- */
  function badge(text, cls) { var b = el('span', 'pill ' + (cls || ''), text); return b; }

  function renderBadges(cs) {
    var box = $('cs-badges'); box.innerHTML = '';
    if (!cs || !cs.installed) { box.appendChild(badge('CrowdSec yok', 'bad')); return; }
    box.appendChild(badge('CrowdSec ' + (cs.version || ''), 'ok'));
    box.appendChild(badge(cs.agent_running ? 'ajan çalışıyor' : 'ajan durdu', cs.agent_running ? 'ok' : 'bad'));
    box.appendChild(badge(cs.bouncer_running ? 'bouncer aktif' : 'bouncer yok', cs.bouncer_running ? 'ok' : 'warn'));
    if (cs.bouncers && cs.bouncers.length) {
      box.appendChild(badge(cs.bouncers.length + ' bouncer kayıtlı'));
    }
  }

  function stat(k, v, s, cls) {
    var box = el('div', 'stat ' + (cls || ''));
    box.appendChild(el('div', 'k', k));
    box.appendChild(el('div', 'v', String(v)));
    if (s) box.appendChild(el('div', 's', s));
    return box;
  }

  function renderBars(target, rows, max) {
    var box = $(target); box.innerHTML = '';
    if (!rows || !rows.length) { box.appendChild(el('div', 'muted', 'Kayıt yok.')); return; }
    var top = rows.slice(0, 8);
    var peak = Math.max.apply(null, top.map(function (r) { return r[1]; })) || 1;
    top.forEach(function (r) {
      var row = el('div', 'bar-row');
      var lab = el('div', 'bar-label');
      var fill = el('div', 'bar-fill'); fill.style.width = Math.round((r[1] / peak) * 100) + '%';
      lab.appendChild(fill);
      lab.appendChild(el('span', 'bar-text', r[0]));
      row.appendChild(lab);
      row.appendChild(el('div', 'bar-count', String(r[1])));
      box.appendChild(row);
    });
  }

  function renderOverview() {
    var cs = DASH.crowdsec || {};
    $('cs-missing').hidden = !!cs.installed;
    renderBadges(cs);
    var s = DASH.summary || {}, dec = DASH.decisions || [];
    var cards = $('ov-cards'); cards.innerHTML = '';
    cards.appendChild(stat('Etkin karar', dec.length, 'engellenen adres', dec.length ? 'warn' : 'good'));
    cards.appendChild(stat('Uyarı', s.alert_count || 0, DASH.since + ' içinde'));
    cards.appendChild(stat('Benzersiz IP', s.unique_ips || 0, 'uyarı üreten'));
    cards.appendChild(stat('Senaryo', (s.scenarios || []).length, 'farklı saldırı türü'));
    cards.appendChild(stat('Koleksiyon', (DASH.collections || []).length, 'kurulu'));
    renderBars('ov-scenarios', s.scenarios || []);
    renderBars('ov-countries', s.countries || []);

    var tb = $('ov-ips').querySelector('tbody'); tb.innerHTML = '';
    var ips = (s.top_ips || []).slice(0, 25);
    if (!ips.length) {
      var tr = el('tr'); var td = el('td', 'empty', 'Bu pencerede uyarı yok.'); td.colSpan = 8; tr.appendChild(td); tb.appendChild(tr);
    }
    ips.forEach(function (r) {
      var tr = el('tr');
      tr.appendChild(el('td', 'ip', r.ip));
      tr.appendChild(el('td', '', r.country || '–'));
      tr.appendChild(el('td', '', (r.as_name || '–').slice(0, 28)));
      tr.appendChild(el('td', 'num', String(r.count)));
      tr.appendChild(el('td', 'num', String(r.events)));
      var sc = Object.keys(r.scenarios || {}).map(function (k) {
        return k.replace(/^crowdsecurity\//, '') + '×' + r.scenarios[k];
      }).slice(0, 3).join(', ');
      tr.appendChild(el('td', '', sc));
      var st = el('td');
      st.appendChild(badge(r.banned ? 'engelli' : 'serbest', r.banned ? 'bad' : ''));
      tr.appendChild(st);
      var act = el('td');
      if (!r.banned) {
        var b = el('button', 'btn small danger', 'Engelle');
        b.addEventListener('click', function () { banIp(r.ip, '24h', 'panel: ' + sc); });
        act.appendChild(b);
      }
      tr.appendChild(act);
      tb.appendChild(tr);
    });
    $('ov-updated').textContent = 'güncellendi: ' + new Date().toLocaleTimeString('tr-TR');
  }

  function renderDecisions() {
    var tb = $('dec-table').querySelector('tbody'); tb.innerHTML = '';
    var filter = ($('dec-filter').value || '').toLowerCase();
    var rows = (DASH.decisions || []).filter(function (d) {
      if (!filter) return true;
      return (d.value + ' ' + d.reason + ' ' + (d.country || '') + ' ' + (d.origin || '')).toLowerCase().indexOf(filter) >= 0;
    });
    if (!rows.length) {
      var tr = el('tr'); var td = el('td', 'empty', 'Etkin karar yok.'); td.colSpan = 7; tr.appendChild(td); tb.appendChild(tr);
    }
    rows.slice(0, 300).forEach(function (d) {
      var tr = el('tr');
      tr.appendChild(el('td', 'ip', d.value));
      tr.appendChild(el('td', '', d.type || 'ban'));
      tr.appendChild(el('td', '', (d.reason || '').replace(/^crowdsecurity\//, '')));
      tr.appendChild(el('td', '', d.origin || '–'));
      tr.appendChild(el('td', '', (d.until || '').slice(0, 19).replace('T', ' ') || d.duration || '–'));
      tr.appendChild(el('td', '', d.country || '–'));
      var act = el('td');
      var b = el('button', 'btn small', 'Kaldır');
      b.addEventListener('click', function () {
        b.disabled = true;
        api('/api/decisions', { action: 'delete', value: d.value }).then(function () {
          toast('Karar kaldırıldı: ' + d.value); refresh();
        }).catch(function (err) { b.disabled = false; toast(err.message, 5000); });
      });
      act.appendChild(b); tr.appendChild(act);
      tb.appendChild(tr);
    });
    var chips = $('collections'); chips.innerHTML = '';
    (DASH.collections || []).forEach(function (c) {
      chips.appendChild(el('span', 'chip', c.name + (c.version ? ' · ' + c.version : '')));
    });
    if (!(DASH.collections || []).length) chips.appendChild(el('span', 'muted', 'Koleksiyon bilgisi alınamadı.'));
  }

  function banIp(value, duration, reason) {
    api('/api/decisions', { action: 'add', value: value, duration: duration || '4h', reason: reason || 'panel' })
      .then(function () { toast(value + ' engellendi'); refresh(); })
      .catch(function (err) { toast(err.message, 6000); });
  }

  /* ---------------- AI ---------------- */
  function renderAnalysis(a) {
    if (!a) { $('ai-result').hidden = true; return; }
    $('ai-result').hidden = false;
    var riskMap = { low: ['düşük risk', 'ok'], medium: ['orta risk', 'warn'], high: ['yüksek risk', 'bad'] };
    var r = riskMap[a.risk] || ['risk: ' + (a.risk || '?'), ''];
    var pill = $('ai-risk'); pill.textContent = r[0]; pill.className = 'pill ' + r[1];
    $('ai-meta').textContent = [a.provider, a.model, a.window, a.generated_at,
      (a.elapsed ? a.elapsed + ' sn' : '')].filter(Boolean).join(' · ');
    $('ai-summary').textContent = a.summary || '';
    var box = $('ai-findings'); box.innerHTML = '';
    (a.findings || []).forEach(function (f) {
      var p = el('div', 'prop');
      var h = el('div', 'prop-head');
      h.appendChild(el('span', 'prop-action', f.title || 'Bulgu'));
      (f.ips || []).slice(0, 6).forEach(function (ip) { h.appendChild(el('span', 'prop-value', ip)); });
      p.appendChild(h);
      p.appendChild(el('div', 'prop-why', f.detail || ''));
      box.appendChild(p);
    });
  }

  var ACTION_LABEL = {
    ban: 'Engelle', ban_range: 'Aralığı engelle', allow: 'Korumalı listeye al',
    install_collection: 'Koleksiyon kur', note: 'Bilgi notu'
  };

  function renderProposals() {
    var box = $('proposals'); box.innerHTML = '';
    var onlyPending = $('prop-pending-only').checked;
    var rows = PROPS.filter(function (p) { return !onlyPending || p.status === 'pending'; });
    if (!rows.length) { box.appendChild(el('div', 'muted', 'Öneri yok. Yukarıdan bir analiz çalıştırın.')); return; }
    rows.slice(0, 60).forEach(function (p) {
      var card = el('div', 'prop ' + (p.status === 'applied' ? 'applied' : p.status === 'rejected' ? 'rejected' : ''));
      var head = el('div', 'prop-head');
      head.appendChild(el('span', 'prop-action', ACTION_LABEL[p.action] || p.action));
      if (p.value) head.appendChild(el('span', 'prop-value', p.value));
      if (p.action === 'ban' || p.action === 'ban_range') head.appendChild(el('span', 'muted', p.duration || ''));
      head.appendChild(el('span', 'conf', 'güven ' + Math.round((p.confidence || 0) * 100) + '%'));
      head.appendChild(el('span', 'spacer'));
      if (p.status !== 'pending') {
        var label = { applied: 'uygulandı', rejected: 'reddedildi', superseded: 'yenisiyle değişti' };
        head.appendChild(badge(label[p.status] || p.status, p.status === 'applied' ? 'ok' : ''));
      }
      card.appendChild(head);
      card.appendChild(el('div', 'prop-why', p.why || p.reason || ''));
      if (p.result) card.appendChild(el('div', 'muted', p.result));
      if (p.status === 'pending') {
        var row = el('div', 'btn-row');
        var ok = el('button', 'btn primary small', p.action === 'note' ? 'Okundu' : 'Uygula');
        var no = el('button', 'btn small', 'Reddet');
        ok.addEventListener('click', function () { decide(p.id, 'apply', ok, no); });
        no.addEventListener('click', function () { decide(p.id, 'reject', ok, no); });
        row.appendChild(ok); row.appendChild(no);
        card.appendChild(row);
      }
      box.appendChild(card);
    });
  }

  function decide(id, decision, ok, no) {
    ok.disabled = no.disabled = true;
    api('/api/proposal', { id: id, decision: decision }).then(function (res) {
      toast(decision === 'apply' ? ('Uygulandı: ' + (res.result || '')) : 'Öneri reddedildi');
      return loadProposals().then(refresh);
    }).catch(function (err) {
      ok.disabled = no.disabled = false;
      toast(err.message, 6000);
    });
  }

  function loadProposals() {
    return api('/api/proposals').then(function (res) {
      PROPS = res.proposals || [];
      renderProposals();
      if (res.analysis) renderAnalysis(res.analysis);
    });
  }

  function analyze() {
    show('ai-error', '');
    var btn = $('btn-analyze');
    btn.disabled = true;
    $('ai-status').innerHTML = '<span class="spin"></span> analiz ediliyor, bu 10-60 saniye sürebilir…';
    api('/api/analyze', {
      since: $('ai-window').value,
      provider: $('ai-provider').value,
      model: $('ai-model').value.trim(),
      note: $('ai-note').value.trim()
    }).then(function (res) {
      btn.disabled = false; $('ai-status').textContent = '';
      if (res.empty) { toast(res.message || 'Bu pencerede uyarı yok.', 5000); return; }
      renderAnalysis(res.analysis);
      return loadProposals();
    }).catch(function (err) {
      btn.disabled = false; $('ai-status').textContent = '';
      show('ai-error', err.message);
    });
  }

  /* ---------------- saglayicilar ---------------- */
  function renderProviders() {
    var box = $('provider-list'); box.innerHTML = '';
    var keys = STATE.keys || {};
    (STATE.providers || []).forEach(function (p) {
      var info = keys[p.id] || {};
      var row = el('div', 'prov');
      var left = el('div');
      left.appendChild(el('div', 'name', p.label));
      left.appendChild(el('div', 'sub', p.openai_compatible ? 'OpenAI uyumlu' : 'özel API'));
      row.appendChild(left);

      var keyIn = el('input'); keyIn.type = 'password'; keyIn.spellcheck = false;
      keyIn.placeholder = info.configured ? ('kayıtlı ' + (info.hint || '')) : 'API anahtarı';
      row.appendChild(keyIn);

      var modelIn = el('input'); modelIn.type = 'text'; modelIn.spellcheck = false;
      modelIn.value = info.model || '';
      modelIn.placeholder = (p.default_models && p.default_models[0]) || 'model';
      row.appendChild(modelIn);

      var acts = el('div', 'btn-row');
      var save = el('button', 'btn small primary', 'Kaydet');
      save.addEventListener('click', function () {
        save.disabled = true;
        api('/api/providers', { action: 'save', provider: p.id, key: keyIn.value, model: modelIn.value })
          .then(function (res) { STATE.keys = res.keys; keyIn.value = ''; toast(p.label + ' kaydedildi'); renderProviders(); })
          .catch(function (err) { save.disabled = false; show('prov-error', err.message); });
      });
      var test = el('button', 'btn small', 'Test');
      test.addEventListener('click', function () {
        test.disabled = true; test.textContent = '…';
        api('/api/providers', { action: 'test', provider: p.id }).then(function (res) {
          test.disabled = false; test.textContent = 'Test';
          toast(p.label + ': ' + res.message, 6000);
        }).catch(function (err) {
          test.disabled = false; test.textContent = 'Test'; show('prov-error', err.message);
        });
      });
      var del = el('button', 'btn small', 'Sil');
      del.addEventListener('click', function () {
        api('/api/providers', { action: 'delete', provider: p.id }).then(function (res) {
          STATE.keys = res.keys; toast(p.label + ' silindi'); renderProviders();
        }).catch(function (err) { show('prov-error', err.message); });
      });
      acts.appendChild(save); acts.appendChild(test);
      if (info.configured) acts.appendChild(del);
      row.appendChild(acts);
      box.appendChild(row);
    });
    var sel = $('ai-provider'); var current = (STATE.ai || {}).provider || '';
    sel.innerHTML = '';
    (STATE.providers || []).forEach(function (p) {
      var info = keys[p.id] || {};
      var o = el('option', '', p.label + (info.configured ? '' : ' (anahtar yok)'));
      o.value = p.id; o.disabled = !info.configured;
      sel.appendChild(o);
    });
    if (current) sel.value = current;
    sel.onchange = function () {
      api('/api/settings', { ai: { provider: sel.value } }).then(function () {
        toast('Varsayılan sağlayıcı: ' + sel.value);
      }).catch(function (err) { toast(err.message); });
    };
  }

  /* ---------------- ayarlar / denetim ---------------- */
  function renderSettings() {
    var guard = STATE.guard || {};
    $('never-ban').value = (guard.never_ban || []).join('\n');
    $('protect-private').checked = !!guard.protect_private_ranges;
    var cs = (DASH.crowdsec || STATE.crowdsec || {});
    var rows = [
      ['Panel sürümü', STATE.version || '-'],
      ['Sunucu', STATE.hostname || '-'],
      ['Panel adresi', STATE.public_url || '-'],
      ['Sizin IP', STATE.your_ip || '-'],
      ['CrowdSec', cs.installed ? (cs.version || 'kurulu') : 'kurulu değil'],
      ['Ajan', cs.agent_running ? 'çalışıyor' : 'durdu'],
      ['Bouncer', cs.bouncer_running ? 'aktif' : 'yok'],
      ['TLS', STATE.tls ? 'açık' : 'kapalı']
    ];
    var grid = $('sys-info'); grid.innerHTML = '';
    rows.forEach(function (r) {
      grid.appendChild(el('b', '', r[0]));
      grid.appendChild(el('span', '', String(r[1])));
    });
  }

  function loadAudit() {
    api('/api/audit').then(function (res) {
      var tb = $('audit-table').querySelector('tbody'); tb.innerHTML = '';
      (res.entries || []).forEach(function (e) {
        var tr = el('tr');
        tr.appendChild(el('td', '', (e.ts || '').replace('T', ' ').slice(0, 19)));
        tr.appendChild(el('td', '', e.action || ''));
        tr.appendChild(el('td', 'muted', JSON.stringify(e.detail || {})));
        tb.appendChild(tr);
      });
      if (!(res.entries || []).length) {
        var tr = el('tr'); var td = el('td', 'empty', 'Kayıt yok.'); td.colSpan = 3; tr.appendChild(td); tb.appendChild(tr);
      }
    }).catch(function (err) { toast(err.message); });
  }

  /* ---------------- yukleme ---------------- */
  function refresh() {
    return api('/api/dashboard?since=' + encodeURIComponent($('ov-window').value)).then(function (res) {
      DASH = res;
      renderOverview(); renderDecisions(); renderSettings();
    }).catch(function (err) { toast(err.message, 6000); });
  }

  function initApp(state) {
    STATE = state; CSRF = state.csrf || '';
    $('login').hidden = true; $('app').hidden = false;
    $('host-chip').textContent = state.hostname + ' · v' + state.version;
    renderProviders(); renderSettings();
    refresh(); loadProposals();
  }

  function boot() {
    api('/api/state').then(function (state) {
      if (state.authenticated) { initApp(state); }
      else {
        $('login').hidden = false;
        $('login-foot').textContent = state.app + ' v' + state.version + ' · ' + state.hostname +
          (state.tls ? ' · TLS açık' : ' · TLS KAPALI');
        if (!state.password_set) show('login-error', 'Panel şifresi tanımlı değil; kurulum betiğini çalıştırın.');
        $('login-pass').focus();
      }
    }).catch(function (err) { $('login').hidden = false; show('login-error', 'Sunucuya ulaşılamadı: ' + err.message); });
  }

  function wire() {
    $('login-form').addEventListener('submit', function (ev) {
      ev.preventDefault(); show('login-error', '');
      api('/api/login', { password: $('login-pass').value }).then(function () {
        $('login-pass').value = ''; boot();
      }).catch(function (err) { show('login-error', err.message); });
    });
    $('btn-logout').addEventListener('click', function () {
      api('/api/logout', { bye: 1 }).catch(function () {}).then(logoutUi);
    });
    $('btn-refresh').addEventListener('click', function () { refresh(); loadProposals(); toast('Yenilendi'); });
    $('ov-window').addEventListener('change', refresh);
    $('dec-filter').addEventListener('input', renderDecisions);
    $('btn-analyze').addEventListener('click', analyze);
    $('prop-pending-only').addEventListener('change', renderProposals);
    $('btn-ban').addEventListener('click', function () {
      show('man-error', '');
      var v = $('man-value').value.trim();
      if (!v) { show('man-error', 'IP veya CIDR girin.'); return; }
      api('/api/decisions', { action: 'add', value: v, duration: $('man-duration').value.trim(),
        reason: $('man-reason').value.trim() })
        .then(function () { $('man-value').value = ''; toast(v + ' engellendi'); refresh(); })
        .catch(function (err) { show('man-error', err.message); });
    });
    $('btn-save-guard').addEventListener('click', function () {
      show('guard-msg', '');
      var list = $('never-ban').value.split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
      api('/api/settings', { guard: { never_ban: list, protect_private_ranges: $('protect-private').checked } })
        .then(function (res) { STATE.guard = res.guard; show('guard-msg', 'Kaydedildi.', true); })
        .catch(function (err) { show('guard-msg', err.message); });
    });
    $('btn-pw').addEventListener('click', function () {
      show('pw-msg', '');
      api('/api/password', { current: $('pw-current').value, new: $('pw-new').value })
        .then(function () { $('pw-current').value = $('pw-new').value = ''; show('pw-msg', 'Şifre güncellendi.', true); })
        .catch(function (err) { show('pw-msg', err.message); });
    });
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (tab) {
      tab.addEventListener('click', function () {
        Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (t) { t.classList.remove('active'); });
        Array.prototype.forEach.call(document.querySelectorAll('.pane'), function (p) { p.classList.remove('active'); });
        tab.classList.add('active');
        $('pane-' + tab.dataset.tab).classList.add('active');
        if (tab.dataset.tab === 'audit') loadAudit();
      });
    });
  }

  wire(); boot();
})();
