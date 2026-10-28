/* AGFO App Store - istemci */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var QS = new URLSearchParams(location.search);
  var CSRF = '', STATE = {}, APPS = [], CATS = [], FILTER = { q: '', cat: '' }, CURRENT = null, POLL = null;

  function toast(msg, ms) {
    var el = $('toast'); el.textContent = msg; el.hidden = false;
    clearTimeout(el._t); el._t = setTimeout(function () { el.hidden = true; }, ms || 3200);
  }
  function show(id, msg, ok) {
    var el = $(id); if (!el) return;
    if (!msg) { el.hidden = true; el.textContent = ''; return; }
    el.classList.toggle('ok', !!ok); el.textContent = msg; el.hidden = false;
  }
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
          var map = { bad_password: 'Şifre hatalı.', locked: 'Çok fazla hatalı deneme.',
            csrf: 'Oturum doğrulaması başarısız, sayfayı yenileyin.',
            too_short: 'Şifre en az 10 karakter olmalı.',
            ip_not_allowed: 'IP adresiniz izinli listede değil.' };
          throw new Error(map[data.error] || data.error || ('HTTP ' + res.status));
        }
        return data;
      });
    });
  }
  function logoutUi() { $('app').hidden = true; $('login').hidden = false; }

  /* ---------------- mağaza ---------------- */
  function renderCats() {
    var box = $('cats'); box.innerHTML = '';
    var all = el('div', 'chip' + (FILTER.cat ? '' : ' active'), 'Tümü (' + APPS.length + ')');
    all.addEventListener('click', function () { FILTER.cat = ''; renderCats(); renderGrid(); });
    box.appendChild(all);
    CATS.forEach(function (c) {
      var chip = el('div', 'chip' + (FILTER.cat === c.id ? ' active' : ''), c.label + ' (' + c.count + ')');
      chip.addEventListener('click', function () { FILTER.cat = c.id; renderCats(); renderGrid(); });
      box.appendChild(chip);
    });
  }

  function matches(app) {
    if (FILTER.cat && app.category !== FILTER.cat) return false;
    var q = FILTER.q.trim().toLowerCase();
    if (!q) return true;
    var hay = [app.name, app.tagline, app.description, app.category_label].concat(app.tags || []).join(' ').toLowerCase();
    return hay.indexOf(q) >= 0;
  }

  function renderGrid() {
    var grid = $('grid'); grid.innerHTML = '';
    var rows = APPS.filter(matches);
    $('grid-empty').hidden = rows.length > 0;
    rows.forEach(function (app) {
      var card = el('div', 'appcard');
      var head = el('div', 'appcard-head');
      var tile = el('div', 'tile t-' + (app.category || 'tools'), app.badge);
      var box = el('div');
      box.appendChild(el('h4', '', app.name));
      box.appendChild(el('div', 'cat', app.category_label || ''));
      head.appendChild(tile); head.appendChild(box);
      card.appendChild(head);
      card.appendChild(el('div', 'tag', app.tagline || ''));
      var foot = el('div', 'appcard-foot');
      var mode = el('span', 'mode' + (app.install_mode === 'cli' ? ' cli' : ''),
        app.install_mode === 'cli' ? 'tek tıkla kurulur' : 'sihirbazla tamamlanır');
      foot.appendChild(mode);
      foot.appendChild(el('span', 'spacer'));
      var btn = el('button', 'btn primary small', 'Kur');
      btn.addEventListener('click', function () { openInstall(app); });
      foot.appendChild(btn);
      card.appendChild(foot);
      grid.appendChild(card);
    });
  }

  /* ---------------- kurulum penceresi ---------------- */
  function openInstall(app) {
    CURRENT = app;
    show('im-error', '');
    $('im-title').textContent = app.name + ' kur';
    $('im-desc').textContent = app.description || app.tagline || '';
    $('im-php').value = (STATE.cyberpanel && STATE.cyberpanel.default_php) || '8.2';
    $('im-path').value = '/';
    $('im-note').textContent = app.install_mode === 'cli'
      ? 'Kurulum sonunda uygulama kullanıma hazır olacak.'
      : 'Dosyalar ve veritabanı hazırlanır, kurulumu tarayıcıdan tamamlarsınız.';
    var box = $('im-fields'); box.innerHTML = '';
    (app.fields || []).forEach(function (f) {
      var row = el('div', 'row');
      var lab = el('label', '', f.label); lab.setAttribute('for', 'f-' + f.id);
      var input = el('input');
      input.id = 'f-' + f.id;
      input.type = f.type === 'password' ? 'password' : (f.type === 'email' ? 'email' : 'text');
      input.value = f.default || '';
      row.appendChild(lab); row.appendChild(input);
      box.appendChild(row);
    });
    if (app.requires && app.requires.php) {
      var hint = el('div', 'muted', 'En az PHP ' + app.requires.php +
        (app.version_note ? ' · ' + app.version_note : ''));
      hint.style.fontSize = '11.5px';
      box.appendChild(hint);
    }
    $('install-modal').hidden = false;
    $('im-domain').focus();
  }

  function startInstall() {
    show('im-error', '');
    var params = {
      domain: $('im-domain').value.trim(),
      path: $('im-path').value.trim() || '/',
      email: $('im-email').value.trim(),
      php: $('im-php').value.trim(),
      title: CURRENT.name
    };
    (CURRENT.fields || []).forEach(function (f) {
      params[f.id] = ($('f-' + f.id) || {}).value || '';
    });
    if (!params.domain) { show('im-error', 'Alan adı girin.'); return; }
    if (!params.email) { show('im-error', 'E-posta girin.'); return; }
    var btn = $('im-start'); btn.disabled = true;
    api('/api/install', { app: CURRENT.id, params: params }).then(function (res) {
      btn.disabled = false;
      $('install-modal').hidden = true;
      watchJob(res.job, CURRENT.name + ' → ' + params.domain);
    }).catch(function (err) { btn.disabled = false; show('im-error', err.message); });
  }

  /* ---------------- iş izleme ---------------- */
  function watchJob(jobId, title, kind) {
    var removing = kind === 'uninstall';
    $('jm-title').textContent = title || 'Kurulum';
    $('jm-log').textContent = '';
    $('jm-result').hidden = true;
    $('jm-result').innerHTML = '';
    $('jm-status').textContent = removing ? 'kaldırılıyor' : 'kuruluyor'; $('jm-status').className = 'pill busy';
    $('job-modal').hidden = false;
    var offset = 0;
    clearInterval(POLL);
    POLL = setInterval(function () {
      api('/api/job/' + jobId + '?offset=' + offset).then(function (res) {
        if (res.lines && res.lines.length) {
          offset = res.total;
          var pre = $('jm-log');
          pre.textContent += res.lines.join('\n') + '\n';
          pre.scrollTop = pre.scrollHeight;
        }
        var st = (res.job || {}).status;
        if (st === 'done') {
          clearInterval(POLL);
          $('jm-status').textContent = 'tamamlandı'; $('jm-status').className = 'pill ok';
          if (removing || (res.job.result || {}).kind === 'uninstall') renderUninstallResult(res.job.result || {});
          else renderResult(res.job.result || {});
          loadInstalls();
        } else if (st === 'error') {
          clearInterval(POLL);
          $('jm-status').textContent = 'hata'; $('jm-status').className = 'pill bad';
          var box = $('jm-result'); box.hidden = false;
          box.style.background = '#2a1717'; box.style.borderColor = '#5a2c2c';
          box.appendChild(el('h4', '', removing ? 'Kaldırma tamamlanamadı' : 'Kurulum tamamlanamadı'));
          box.appendChild(el('div', '', (res.job || {}).error || 'Bilinmeyen hata'));
        }
      }).catch(function (err) { clearInterval(POLL); toast(err.message, 6000); });
    }, 1200);
  }

  function kv(parent, key, value, copy) {
    parent.appendChild(el('b', '', key));
    parent.appendChild(el('span', '', value));
    if (copy && value) {
      var btn = el('button', 'btn small', 'kopyala');
      btn.addEventListener('click', function () {
        if (navigator.clipboard && window.isSecureContext) {
          navigator.clipboard.writeText(value).then(function () { toast('Kopyalandı'); });
        } else { toast('Kopyalama için HTTPS gerekir'); }
      });
      parent.appendChild(btn);
    } else {
      parent.appendChild(el('span', '', ''));
    }
  }

  function renderResult(result) {
    var box = $('jm-result'); box.hidden = false; box.innerHTML = '';
    box.appendChild(el('h4', '', result.install_mode === 'cli'
      ? 'Kurulum tamamlandı' : 'Dosyalar hazır — kurulumu tarayıcıdan tamamlayın'));
    if (result.note) box.appendChild(el('p', 'muted', result.note));
    var grid = el('div', 'kv');
    kv(grid, 'Adres', result.url, true);
    if (result.admin_user) kv(grid, 'Yönetici', result.admin_user, true);
    if (result.admin_pass) kv(grid, 'Şifre', result.admin_pass, true);
    if (result.db_name) {
      kv(grid, 'Veritabanı', result.db_name, true);
      kv(grid, 'DB kullanıcı', result.db_user, true);
      kv(grid, 'DB şifre', result.db_pass, true);
    }
    box.appendChild(grid);
    var row = el('div', 'btn-row'); row.style.marginTop = '12px';
    var open = el('a', 'btn primary', 'Siteyi aç');
    open.href = result.url; open.target = '_blank'; open.rel = 'noopener';
    row.appendChild(open);
    box.appendChild(row);
    box.appendChild(el('div', 'muted', 'Şifreler bu ekranda bir kez gösterilir; kaydedin.'));
  }

  /* ---------------- kaldirma ---------------- */
  var UNINSTALL = null;
  function updateUninstallWarn() {
    var i = UNINSTALL; if (!i) return;
    var parts = [];
    var where = i.domain + ((i.path && i.path !== '/') ? i.path : '');
    if ($('um-site').checked) parts.push('CyberPanel sitesi ' + i.domain + ' tamamen silinecek.');
    else parts.push(where + ' altındaki tüm dosyalar kaldırılacak.');
    if (i.db_name && $('um-db').checked) parts.push('Veritabanı ' + i.db_name + ' silinecek.');
    parts.push($('um-backup').checked
      ? 'Önce yedek alınır; geri dönmek mümkündür.'
      : 'YEDEK ALINMAYACAK: bu işlem geri alınamaz.');
    var w = $('um-warn'); w.textContent = parts.join(' ');
    w.className = 'warnbox' + ($('um-backup').checked ? ' soft' : '');
    $('um-start').disabled = ($('um-confirm').value.trim().toLowerCase() !== i.domain);
  }
  function openUninstall(i) {
    UNINSTALL = i;
    $('um-title').textContent = (i.app_name || i.app) + ' kaldır';
    $('um-desc').textContent = i.url || i.domain;
    $('um-domain').textContent = i.domain;
    $('um-db-name').textContent = i.db_name || '';
    $('um-db-row').hidden = !i.db_name; $('um-db').checked = !!i.db_name;
    var canSite = !!i.created_site && (!i.path || i.path === '/');
    $('um-site-row').hidden = !canSite; $('um-site').checked = false;
    $('um-site-note').hidden = canSite || !(!i.path || i.path === '/');
    $('um-backup').checked = true;
    $('um-confirm').value = '';
    $('um-error').hidden = true;
    $('uninstall-modal').hidden = false;
    updateUninstallWarn();
    setTimeout(function () { $('um-confirm').focus(); }, 50);
  }
  function startUninstall() {
    var i = UNINSTALL; if (!i) return;
    var btn = $('um-start'); btn.disabled = true;
    api('/api/uninstall', {
      domain: i.domain, path: i.path || '/', confirm: $('um-confirm').value.trim(),
      drop_db: !!i.db_name && $('um-db').checked, backup: $('um-backup').checked,
      delete_site: !$('um-site-row').hidden && $('um-site').checked
    }).then(function (res) {
      $('uninstall-modal').hidden = true;
      watchJob(res.job, (i.app_name || i.app) + ' kaldırılıyor → ' + i.domain, 'uninstall');
    }).catch(function (err) { btn.disabled = false; show('um-error', err.message); });
  }
  function renderUninstallResult(r) {
    var box = $('jm-result'); box.hidden = false; box.innerHTML = '';
    box.appendChild(el('h4', '', r.site_deleted ? 'Uygulama ve site kaldırıldı' : 'Uygulama kaldırıldı'));
    var grid = el('div', 'kv');
    kv(grid, 'Alan adı', r.domain + ((r.path && r.path !== '/') ? r.path : ''), false);
    if (r.backup) kv(grid, 'Yedek', r.backup, true);
    box.appendChild(grid);
    (r.warnings || []).forEach(function (w) { box.appendChild(el('div', 'warnbox', w)); });
    box.appendChild(el('div', 'muted', r.backup
      ? 'Yedek dizininde dosyalar (files/) ve veritabanı dökümü (.sql) bulunur. Gerekmiyorsa sunucuda silebilirsiniz.'
      : 'Yedek alınmadı.'));
  }

  /* ---------------- listeler ---------------- */
  function loadInstalls() {
    api('/api/installs').then(function (res) {
      var tb = $('installed-table').querySelector('tbody'); tb.innerHTML = '';
      (res.installs || []).forEach(function (i) {
        var tr = el('tr');
        tr.appendChild(el('td', '', i.app_name || i.app));
        var td = el('td');
        var a = el('a', '', i.url); a.href = i.url; a.target = '_blank'; a.rel = 'noopener';
        td.appendChild(a); tr.appendChild(td);
        tr.appendChild(el('td', '', i.db_name || '–'));
        tr.appendChild(el('td', '', i.php || '–'));
        tr.appendChild(el('td', '', new Date((i.installed || 0) * 1000).toLocaleString('tr-TR')));
        var act = el('td');
        var rm = el('button', 'btn small danger', 'Kaldır');
        rm.addEventListener('click', function () { openUninstall(i); });
        act.appendChild(rm); tr.appendChild(act);
        tb.appendChild(tr);
      });
      if (!(res.installs || []).length) {
        var tr = el('tr'); var td = el('td', 'empty', 'Henüz uygulama kurulmadı.');
        td.colSpan = 6; tr.appendChild(td); tb.appendChild(tr);
      }
    }).catch(function () {});
  }

  function loadJobs() {
    api('/api/jobs').then(function (res) {
      var tb = $('jobs-table').querySelector('tbody'); tb.innerHTML = '';
      (res.jobs || []).forEach(function (j) {
        var tr = el('tr');
        var map = { done: ['tamam', 'ok'], error: ['hata', 'bad'], running: ['sürüyor', 'busy'], queued: ['sırada', ''] };
        var info = map[j.status] || [j.status, ''];
        var td0 = el('td'); td0.appendChild(el('span', 'pill ' + info[1], info[0])); tr.appendChild(td0);
        tr.appendChild(el('td', '', (j.kind === 'uninstall' ? 'Kaldırma · ' : '') + (j.app_name || j.app)));
        tr.appendChild(el('td', '', (j.domain || '') + (j.path && j.path !== '/' ? j.path : '')));
        tr.appendChild(el('td', '', new Date((j.created || 0) * 1000).toLocaleString('tr-TR')));
        var tda = el('td');
        var btn = el('button', 'btn small', 'günlük');
        btn.addEventListener('click', function () { watchJob(j.id, (j.kind === 'uninstall' ? 'Kaldırma: ' : '') + (j.app_name || '') + ' → ' + (j.domain || ''), j.kind); });
        tda.appendChild(btn); tr.appendChild(tda);
        tb.appendChild(tr);
      });
      if (!(res.jobs || []).length) {
        var tr = el('tr'); var td = el('td', 'empty', 'Kayıt yok.'); td.colSpan = 5; tr.appendChild(td); tb.appendChild(tr);
      }
    }).catch(function () {});
  }

  function verifyCatalog() {
    var btn = $('btn-verify'); btn.disabled = true;
    $('verify-status').innerHTML = '<span class="spin"></span> adresler yoklanıyor…';
    api('/api/verify', { go: 1 }).then(function (res) {
      btn.disabled = false;
      var ok = (res.results || []).filter(function (r) { return r.ok; }).length;
      $('verify-status').textContent = ok + ' / ' + (res.results || []).length + ' adres çalışıyor';
      var box = $('verify-results'); box.innerHTML = '';
      (res.results || []).forEach(function (r) {
        var row = el('div', 'vrow' + (r.ok ? '' : ' bad'));
        row.appendChild(el('span', 'pill ' + (r.ok ? 'ok' : 'bad'), r.ok ? 'tamam' : 'hata'));
        row.appendChild(el('b', '', r.name));
        var detail = r.ok ? (r.size ? (r.size / 1048576).toFixed(1) + ' MB' : 'erişilebilir')
                          : (r.error || ('HTTP ' + r.status));
        row.appendChild(el('span', 'muted', detail));
        box.appendChild(row);
      });
    }).catch(function (err) {
      btn.disabled = false; $('verify-status').textContent = '';
      toast(err.message, 6000);
    });
  }

  /* ---------------- başlatma ---------------- */
  function initApp(state) {
    STATE = state; CSRF = state.csrf || '';
    $('login').hidden = true; $('app').hidden = false;
    $('host-chip').textContent = state.hostname + ' · v' + state.version;
    var badges = $('top-badges'); badges.innerHTML = '';
    var cp = state.cyberpanel || {};
    badges.appendChild(el('span', 'pill ' + (cp.cli ? 'ok' : 'bad'), cp.cli ? 'CyberPanel bağlı' : 'CyberPanel CLI yok'));
    badges.appendChild(el('span', 'pill', state.app_count + ' uygulama'));
    $('set-php').value = cp.default_php || '8.2';
    $('set-package').value = cp.default_package || 'Default';
    $('set-owner').value = cp.default_owner || 'admin';
    $('set-ssl').checked = !!cp.issue_ssl;

    api('/api/catalog').then(function (res) {
      APPS = res.apps || []; CATS = res.categories || [];
      renderCats(); renderGrid();
    });
    loadInstalls();
  }

  function boot() {
    api('/api/state').then(function (state) {
      if (state.authenticated) { initApp(state); }
      else {
        $('login').hidden = false;
        $('login-foot').textContent = state.app + ' v' + state.version + ' · ' + state.hostname;
        if (!state.password_set) show('login-error', 'Panel şifresi tanımlı değil.');
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
    $('search').addEventListener('input', function () { FILTER.q = this.value; renderGrid(); });
    $('im-start').addEventListener('click', startInstall);
    $('um-start').addEventListener('click', startUninstall);
    ['um-backup', 'um-db', 'um-site'].forEach(function (id) { $(id).addEventListener('change', updateUninstallWarn); });
    $('um-confirm').addEventListener('input', updateUninstallWarn);
    $('um-confirm').addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' && !$('um-start').disabled) startUninstall();
    });
    $('btn-verify').addEventListener('click', verifyCatalog);
    $('btn-save-settings').addEventListener('click', function () {
      show('settings-msg', '');
      api('/api/settings', { cyberpanel: {
        default_php: $('set-php').value.trim(), default_package: $('set-package').value.trim(),
        default_owner: $('set-owner').value.trim(), issue_ssl: $('set-ssl').checked } })
        .then(function (res) { STATE.cyberpanel = res.cyberpanel; show('settings-msg', 'Kaydedildi.', true); })
        .catch(function (err) { show('settings-msg', err.message); });
    });
    $('btn-pw').addEventListener('click', function () {
      show('pw-msg', '');
      api('/api/password', { current: $('pw-current').value, new: $('pw-new').value })
        .then(function () { $('pw-current').value = $('pw-new').value = ''; show('pw-msg', 'Şifre güncellendi.', true); })
        .catch(function (err) { show('pw-msg', err.message); });
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-close]'), function (btn) {
      btn.addEventListener('click', function () {
        $(btn.dataset.close).hidden = true;
        if (btn.dataset.close === 'job-modal') clearInterval(POLL);
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (tab) {
      tab.addEventListener('click', function () {
        Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (t) { t.classList.remove('active'); });
        Array.prototype.forEach.call(document.querySelectorAll('.pane'), function (p) { p.classList.remove('active'); });
        tab.classList.add('active');
        $('pane-' + tab.dataset.tab).classList.add('active');
        if (tab.dataset.tab === 'jobs') loadJobs();
        if (tab.dataset.tab === 'installed') loadInstalls();
      });
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') {
        ['install-modal', 'job-modal'].forEach(function (id) { $(id).hidden = true; });
        clearInterval(POLL);
      }
    });
  }

  wire(); boot();
})();
