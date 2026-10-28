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
      var hb = healthBadge(app.health); hb.title = app.health_detail || '';
      head.appendChild(hb);
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
  var SUG = null;
  function openInstall(app) {
    CURRENT = app; SUG = null;
    show('im-error', '');
    $('im-title').textContent = app.name + ' kur';
    $('im-desc').textContent = app.description || app.tagline || '';
    $('im-domain').value = ''; $('im-path').value = '/';
    $('im-site-info').hidden = true; $('im-php-change-row').hidden = true; $('im-php-change').checked = false;
    $('im-suggest').innerHTML = '<div class="muted"><span class="spin"></span> sunucu inceleniyor, kurulum yeri öneriliyor…</div>';
    $('im-php').innerHTML = ''; $('im-php-hint').textContent = '';
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
    $('install-modal').hidden = false;
    api('/api/suggest?app=' + encodeURIComponent(app.id)).then(function (res) {
      if (CURRENT !== app) return;
      SUG = res;
      renderSuggestions(res);
      fillPhp(res.php, res.best_php);
      var dl = $('im-sites'); dl.innerHTML = '';
      (res.sites || []).forEach(function (s) { var o = el('option'); o.value = s.domain; dl.appendChild(o); });
      if (!$('im-email').value) $('im-email').value = res.email || '';
      (app.fields || []).forEach(function (f) {
        var inp = $('f-' + f.id);
        if (inp && !inp.value && f.type === 'email') inp.value = res.email || '';
      });
      var first = (res.suggestions || []).filter(function (x) { return x.viable; })[0];
      if (first) applySuggestion(first);
      else $('im-domain').focus();
    }).catch(function (err) {
      $('im-suggest').innerHTML = ''; fillPhp([], null);
      $('im-php').appendChild(el('option', '', (STATE.cyberpanel && STATE.cyberpanel.default_php) || '8.2'));
      toast('Öneriler alınamadı: ' + err.message, 5000);
    });
  }

  function fillPhp(opts, best) {
    var sel = $('im-php'); sel.innerHTML = '';
    (opts || []).forEach(function (o) {
      var label = o.version + (o.version === best ? ' (önerilen)' : '') + (o.ok ? '' : ' — ' + o.reason);
      var opt = el('option', '', label); opt.value = o.version; opt.disabled = !o.ok;
      if (o.version === best) opt.selected = true;
      sel.appendChild(opt);
    });
    var bad = (opts || []).filter(function (o) { return o.missing && o.missing.length; });
    $('im-php-hint').textContent = !best && bad.length ? bad[bad.length - 1].hint :
      (SUG && SUG.php_range ? 'Uygulama: PHP ' + SUG.php_range.min + (SUG.php_range.max ? '–' + SUG.php_range.max : '+') : '');
  }

  function renderSuggestions(res) {
    var box = $('im-suggest'); box.innerHTML = '';
    (res.suggestions || []).forEach(function (sg) {
      var b = el('button', 'sg' + (sg.viable ? '' : ' off')); b.type = 'button';
      var k = el('div', 'k', sg.title);
      if (sg.recommended) k.appendChild(el('span', 'rec', 'önerilen'));
      if (sg.kind === 'new_subdomain') k.appendChild(el('span', '', sg.dns_ok ? '· DNS ✓' : '· DNS yok'));
      b.appendChild(k);
      b.appendChild(el('b', '', sg.domain + (sg.path !== '/' ? sg.path : '')));
      b.appendChild(el('div', 'n', (sg.php ? 'PHP ' + sg.php + ' · ' : '') + sg.note));
      if (sg.viable) b.addEventListener('click', function () { applySuggestion(sg); });
      b._sg = sg; box.appendChild(b);
    });
    if (!(res.suggestions || []).length) box.appendChild(el('div', 'muted', 'Öneri yok; alan adını elle girin.'));
  }

  function applySuggestion(sg) {
    $('im-domain').value = sg.domain; $('im-path').value = sg.path;
    Array.prototype.forEach.call(document.querySelectorAll('#im-suggest .sg'), function (b) {
      b.classList.toggle('active', b._sg === sg);
    });
    domainChanged();
  }

  function domainChanged() {
    if (!SUG) return;
    var dom = $('im-domain').value.trim().toLowerCase();
    var site = (SUG.sites || []).filter(function (s) { return s.domain === dom; })[0];
    var info = $('im-site-info'), row = $('im-php-change-row');
    row.hidden = true; $('im-php-change').checked = false;
    $('im-php').disabled = false;
    if (!site) {
      info.hidden = !dom; info.className = 'siteinfo';
      info.textContent = dom ? 'Yeni site açılır (PHP aşağıdan seçilir).' : '';
      return;
    }
    info.hidden = false;
    var parts = ['Mevcut site · PHP ' + (site.php || '?')];
    if (site.apps.length) parts.push('kurulu: ' + site.apps.map(function (a) { return a.app + (a.path !== '/' ? ' (' + a.path + ')' : ''); }).join(', '));
    else if (!site.root_empty) parts.push('kökte ' + site.root_items + ' öğe var');
    else parts.push('kök boş');
    if (!site.root_empty && $('im-path').value.trim() === '/') parts.push('kök dolu: bir alt dizin girin');
    var phpOpt = (SUG.php || []).filter(function (o) { return o.version === site.php; })[0];
    var fits = phpOpt && phpOpt.ok;
    info.className = 'siteinfo' + (fits ? '' : ' warn');
    if (!fits && site.php) {
      parts.push('bu uygulama sitenin PHP ' + site.php + ' sürümüyle çalışmaz' + (phpOpt && phpOpt.reason ? ' (' + phpOpt.reason + ')' : ''));
      if (SUG.best_php) {
        row.hidden = false;
        $('im-php-change-text').textContent = 'Sitenin PHP sürümünü ' + site.php + ' → ' + SUG.best_php +
          ' yap (sitedeki diğer uygulamaları da etkiler; kurulum başarısız olursa geri alınır)';
      }
    }
    info.textContent = parts.join(' · ');
    // mevcut sitede PHP sitenin kendisidir; secim kutusu bilgi amaclidir
    if (site.php) { $('im-php').value = fits ? site.php : (SUG.best_php || site.php); $('im-php').disabled = true; }
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
    if (!$('im-php-change-row').hidden && $('im-php-change').checked && SUG && SUG.best_php) {
      params.change_site_php = SUG.best_php;
    }
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
    var checking = kind === 'health';
    $('jm-title').textContent = title || 'Kurulum';
    $('jm-log').textContent = '';
    $('jm-result').hidden = true;
    $('jm-result').innerHTML = '';
    $('jm-status').textContent = checking ? 'test ediliyor' : (removing ? 'kaldırılıyor' : 'kuruluyor'); $('jm-status').className = 'pill busy';
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
          if (checking || (res.job.result || {}).kind === 'health') {
            var r = res.job.result || {}; var box = $('jm-result'); box.hidden = false; box.innerHTML = '';
            box.appendChild(el('h4', '', 'Test bitti'));
            box.appendChild(el('div', '', (r.ok || 0) + ' sorunsuz · ' + (r.warn || 0) + ' uyarılı · ' + (r.fail || 0) + ' başarısız'));
            api('/api/catalog').then(function (c) { APPS = c.apps || APPS; renderGrid(); loadHealth(); });
          }
          else if (removing || (res.job.result || {}).kind === 'uninstall') renderUninstallResult(res.job.result || {});
          else renderResult(res.job.result || {});
          loadInstalls();
        } else if (st === 'error') {
          clearInterval(POLL);
          $('jm-status').textContent = 'hata'; $('jm-status').className = 'pill bad';
          var box = $('jm-result'); box.hidden = false;
          box.style.background = '#2a1717'; box.style.borderColor = '#5a2c2c';
          box.appendChild(el('h4', '', removing ? 'Kaldırma tamamlanamadı' : 'Kurulum tamamlanamadı'));
          box.appendChild(el('div', '', (res.job || {}).error || 'Bilinmeyen hata'));
          addAnalyzeButton(box, jobId);
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

  /* ---------------- saglik testi ---------------- */
  var HB = { verified: '✓ doğrulandı', package_ok: 'paket tamam', warn: 'uyarılı', fail: 'sorunlu', untested: 'denenmedi' };
  function healthBadge(state) { return el('span', 'hbadge ' + (state || 'untested'), HB[state || 'untested']); }
  function layerPill(r) {
    if (!r || !r.status) return el('span', 'muted', '–');
    var map = { ok: ['tamam', 'ok'], warn: ['uyarı', 'busy'], fail: ['hata', 'bad'], skip: ['atlandı', ''] };
    var info = map[r.status] || [r.status, ''];
    var p = el('span', 'pill ' + info[1], info[0]);
    p.title = new Date((r.tested || 0) * 1000).toLocaleString('tr-TR');
    return p;
  }
  function loadHealth() {
    api('/api/health').then(function (res) {
      $('health-domain').value = res.test_domain || '';
      $('health-php').textContent = 'Kurulu PHP: ' + ((res.php || []).join(', ') || '?');
      var rep = res.report || {};
      var tb = $('health-table').querySelector('tbody'); tb.innerHTML = '';
      APPS.slice().sort(function (a, b) { return a.name.localeCompare(b.name, 'tr'); }).forEach(function (app) {
        var e = rep[app.id] || {};
        var tr = el('tr');
        tr.appendChild(el('td', '', app.name));
        var tp = el('td'); tp.appendChild(layerPill(e.package)); tr.appendChild(tp);
        var tt = el('td'); tt.appendChild(layerPill(e.trial)); tr.appendChild(tt);
        var det = '';
        if (e.trial && e.trial.detail) det = e.trial.detail;
        else if (e.package) {
          var bad = (e.package.checks || []).filter(function (c) { return c.level !== 'ok'; }).map(function (c) { return c.text; });
          det = bad.length ? bad.join(' · ') : ('sürüm ' + (e.package.version || '?') + ' · ' + e.package.size_mb + ' MB');
        }
        tr.appendChild(el('td', 'det', det));
        var act = el('td'); var box = el('div', 'tool-actions');
        var b1 = el('button', 'btn small', 'Paket'); b1.addEventListener('click', function () { runHealth('package', [app.id]); });
        var b2 = el('button', 'btn small', 'Dene'); b2.addEventListener('click', function () { runHealth('trial', [app.id]); });
        box.appendChild(b1); box.appendChild(b2);
        var failed = (e.package && e.package.status === 'fail') || (e.trial && e.trial.status === 'fail');
        if (failed && aiReady()) {
          var b3 = el('button', 'btn small', "AI'ya sor");
          b3.addEventListener('click', function () { repairApp(app.id); });
          box.appendChild(b3);
        }
        act.appendChild(box); tr.appendChild(act); tb.appendChild(tr);
      });
    }).catch(function (err) { toast(err.message, 6000); });
  }
  function runHealth(mode, ids) {
    if (mode === 'trial' && !ids && !confirm('Tüm uygulamalar test sitesine tek tek kurulup kaldırılacak. Bu uzun sürer ve bant genişliği kullanır. Başlatılsın mı?')) return;
    api('/api/health/start', { mode: mode, apps: ids || [] }).then(function (res) {
      watchJob(res.job, mode === 'package' ? 'Paket testi' : 'Deneme kurulumu', 'health');
    }).catch(function (err) { toast(err.message, 7000); });
  }

  /* ---------------- AI ---------------- */
  var AI = { provider: '', keys: {}, catalog: [] };
  function aiReady() { return !!AI.provider; }

  function addAnalyzeButton(box, jobId) {
    var row = el('div', 'btn-row'); row.style.marginTop = '10px';
    var b = el('button', 'btn', aiReady() ? 'AI ile analiz et' : 'AI ile analiz et (anahtar yok)');
    b.disabled = !aiReady();
    var out = el('div');
    b.addEventListener('click', function () {
      b.disabled = true; b.innerHTML = '<span class="spin"></span> analiz ediliyor…';
      api('/api/ai/analyze', { job: jobId }).then(function (res) {
        b.remove(); renderAnalysis(out, res.analysis);
      }).catch(function (err) { b.disabled = false; b.textContent = 'AI ile analiz et'; toast(err.message, 7000); });
    });
    row.appendChild(b); box.appendChild(row); box.appendChild(out);
  }

  function renderAnalysis(out, a) {
    out.innerHTML = '';
    var box = el('div', 'aibox');
    box.appendChild(el('h5', '', a.ozet || 'Analiz'));
    if (a.neden) box.appendChild(el('div', '', a.neden));
    if ((a.adimlar || []).length) {
      var ol = el('ol');
      a.adimlar.forEach(function (x) { ol.appendChild(el('li', '', x)); });
      box.appendChild(ol);
    }
    box.appendChild(el('div', 'meta', 'Güven: ' + (a.guven || '?') + ' · ' + a.provider + ' / ' + a.model +
      ' · AI yanılabilir; adımları uygulamadan önce kontrol edin.'));
    if (a.katalog_sorunu && a.app) {
      var b = el('button', 'btn small', 'Bu uygulama için katalog onarımı öner');
      b.style.marginTop = '8px';
      b.addEventListener('click', function () { $('job-modal').hidden = true; openTab('settings'); repairApp(a.app); });
      box.appendChild(b);
    }
    out.appendChild(box);
  }

  function loadAI() {
    return api('/api/ai/status').then(function (res) {
      AI.provider = res.provider; AI.keys = res.keys || {}; AI.catalog = res.catalog || [];
      var wrap = $('ai-keys'); wrap.innerHTML = '';
      var names = Object.keys(AI.keys);
      if (!names.length) wrap.appendChild(el('span', 'muted', 'Tanımlı anahtar yok.'));
      var labels = {}; AI.catalog.forEach(function (c) { labels[c.id] = c.label; });
      names.forEach(function (n) {
        var k = AI.keys[n];
        var pill = el('span', 'pill ok', (labels[n] || n) + ' ' + k.hint + ' · ' + k.source);
        if (k.source === 'bu panel') {
          var x = el('button', 'btn ghost small', '✕'); x.title = 'Bu paneldeki anahtarı sil';
          x.addEventListener('click', function () {
            api('/api/ai/key', { provider: n, remove: true }).then(loadAI).catch(function (e) { toast(e.message); });
          });
          pill.appendChild(x);
        }
        wrap.appendChild(pill);
      });
      var sel = $('ai-provider'); sel.innerHTML = '';
      names.forEach(function (n) {
        var o = el('option', '', labels[n] || n); o.value = n; if (n === res.provider) o.selected = true; sel.appendChild(o);
      });
      if (!names.length) { var o = el('option', '', '—'); o.value = ''; sel.appendChild(o); }
      $('ai-model').value = res.model || '';
      var nsel = $('ai-new-provider'); nsel.innerHTML = '';
      AI.catalog.forEach(function (c) { var o = el('option', '', c.label); o.value = c.id; nsel.appendChild(o); });
    }).catch(function () {});
  }

  function repairApp(appId) {
    var box = $('verify-results');
    var holder = document.getElementById('prop-' + appId);
    if (!holder) { holder = el('div', 'proposal'); holder.id = 'prop-' + appId; box.insertBefore(holder, box.firstChild); }
    holder.innerHTML = '<div class="aibox"><span class="spin"></span> AI bir indirme adresi arıyor, ardından sunucudan yoklanacak…</div>';
    holder.scrollIntoView({ block: 'center' });
    api('/api/ai/repair', { app: appId }).then(function (res) { renderProposal(holder, res.proposal); })
      .catch(function (err) { holder.innerHTML = ''; holder.appendChild(el('div', 'warnbox', err.message)); });
  }

  function renderProposal(holder, p) {
    holder.innerHTML = '';
    var box = el('div', 'aibox');
    box.appendChild(el('h5', '', p.app_name + ' için önerilen kaynak'));
    var d = p.download || {};
    var line = el('div'); line.appendChild(el('code', '', d.github ? ('GitHub ' + d.github + ' · ' + d.asset) : d.url));
    box.appendChild(line);
    box.appendChild(el('div', 'muted', 'biçim ' + d.format + ' · strip ' + d.strip + (d.only ? ' · yalnız ' + d.only : '') +
      (p.note ? ' · ' + p.note : '')));
    if (p.explanation) box.appendChild(el('div', '', p.explanation));
    var c = p.check || {};
    box.appendChild(el('div', c.ok ? 'pill ok' : 'pill bad', c.ok ? 'sunucudan yoklandı: erişilebilir' :
      'sunucudan yoklandı: erişilemiyor (' + (c.error || ('HTTP ' + c.status)) + ')'));
    var row = el('div', 'btn-row'); row.style.marginTop = '8px';
    var apply = el('button', 'btn primary small', 'Uygula'); apply.disabled = !c.ok;
    apply.title = c.ok ? '' : 'Erişilemeyen adres uygulanamaz';
    apply.addEventListener('click', function () {
      apply.disabled = true;
      api('/api/ai/apply', { app: p.app }).then(function (res) {
        holder.innerHTML = ''; holder.appendChild(el('div', 'pill ok', p.app_name + ': yeni kaynak uygulandı'));
        loadOverrides(); toast('Uygulandı: ' + res.url);
      }).catch(function (err) { apply.disabled = false; toast(err.message, 7000); });
    });
    var drop = el('button', 'btn small', 'Vazgeç');
    drop.addEventListener('click', function () { api('/api/ai/discard', { app: p.app }).then(function () { holder.remove(); }); });
    row.appendChild(apply); row.appendChild(drop); box.appendChild(row);
    box.appendChild(el('div', 'meta', p.provider + ' / ' + p.model + (p.source_page ? ' · kaynak: ' + p.source_page : '') +
      ' · Uygulamadan önce adres yeniden yoklanır.'));
    holder.appendChild(box);
  }

  function loadOverrides() {
    api('/api/catalog/proposals').then(function (res) {
      var box = $('overrides'); box.innerHTML = '';
      var ids = Object.keys(res.overrides || {});
      if (!ids.length) return;
      box.appendChild(el('h5', '', 'Uygulanmış katalog düzeltmeleri'));
      ids.forEach(function (id) {
        var o = res.overrides[id], d = o.download || {};
        var row = el('div', 'vrow');
        row.appendChild(el('b', '', id));
        row.appendChild(el('code', '', d.github ? ('GitHub ' + d.github) : d.url));
        var b = el('button', 'btn small', 'Geri al');
        b.addEventListener('click', function () {
          api('/api/catalog/revert', { app: id }).then(loadOverrides).catch(function (e) { toast(e.message); });
        });
        row.appendChild(b); box.appendChild(row);
      });
    }).catch(function () {});
  }

  /* ---------------- sunucu araclari ---------------- */
  var TOOL_RM = null;
  function loadTools() {
    var tb = $('tools-table').querySelector('tbody');
    tb.innerHTML = '<tr><td colspan="5" class="empty"><span class="spin"></span></td></tr>';
    api('/api/tools').then(function (res) {
      tb.innerHTML = '';
      (res.tools || []).forEach(function (t) {
        var tr = el('tr');
        var td = el('td'); td.appendChild(el('b', '', t.name));
        td.appendChild(el('div', 'muted', t.desc || t.slug)); tr.appendChild(td);
        tr.appendChild(el('td', '', t.version));
        var st = el('td');
        var map = { active: ['çalışıyor', 'ok'], inactive: ['durdu', 'bad'], failed: ['hata', 'bad'], activating: ['başlıyor', 'busy'] };
        var info = t.service ? (map[t.active] || [t.active || '?', '']) : ['servis yok', ''];
        st.appendChild(el('span', 'pill ' + info[1], info[0]));
        if (t.enabled && t.enabled !== 'enabled') st.appendChild(el('div', 'muted', t.enabled));
        tr.appendChild(st);
        tr.appendChild(el('td', '', t.port ? String(t.port) : '–'));
        var act = el('td'); var box = el('div', 'tool-actions');
        if (t.open_url && !t.self) {
          var a = el('a', 'btn small', 'Aç'); a.href = t.open_url; a.target = '_blank'; a.rel = 'noopener'; box.appendChild(a);
        }
        if (t.service) {
          var r = el('button', 'btn small', 'Yeniden başlat');
          r.addEventListener('click', function () { toolAction(t, 'restart', r); }); box.appendChild(r);
          if (!t.self) {
            var on = t.active === 'active';
            var ss = el('button', 'btn small', on ? 'Durdur' : 'Başlat');
            ss.addEventListener('click', function () { toolAction(t, on ? 'stop' : 'start', ss); }); box.appendChild(ss);
          }
          var lg = el('button', 'btn small', 'Günlük');
          lg.addEventListener('click', function () { toolLogs(t); }); box.appendChild(lg);
        }
        if (t.uninstall && !t.self) {
          var rm = el('button', 'btn small danger', 'Kaldır');
          rm.addEventListener('click', function () { openToolRemove(t); }); box.appendChild(rm);
        }
        act.appendChild(box); tr.appendChild(act); tb.appendChild(tr);
      });
      if (!(res.tools || []).length) {
        tb.innerHTML = '<tr><td colspan="5" class="empty">AGFO aracı bulunamadı.</td></tr>';
      }
    }).catch(function (err) { tb.innerHTML = ''; toast(err.message, 6000); });
  }
  function toolAction(t, what, btn) {
    btn.disabled = true;
    api('/api/tools/action', { slug: t.slug, action: what }).then(function (res) {
      toast(res.message || 'tamam'); setTimeout(loadTools, t.self ? 5000 : 1200);
    }).catch(function (err) { btn.disabled = false; toast(err.message, 7000); });
  }
  function toolLogs(t) {
    $('tm-title').textContent = t.name + ' · son günlük'; $('tm-body').textContent = 'yükleniyor…';
    $('text-modal').hidden = false;
    api('/api/tools/' + t.slug + '/logs?n=200').then(function (res) {
      var pre = $('tm-body'); pre.textContent = res.log; pre.scrollTop = pre.scrollHeight;
    }).catch(function (err) { $('tm-body').textContent = err.message; });
  }
  function openToolRemove(t) {
    TOOL_RM = t; $('tr-title').textContent = t.name + ' kaldır'; $('tr-slug').textContent = t.slug;
    $('tr-confirm').value = ''; $('tr-start').disabled = true; $('tr-error').hidden = true;
    $('tool-rm-modal').hidden = false; setTimeout(function () { $('tr-confirm').focus(); }, 50);
  }
  function startToolRemove() {
    var t = TOOL_RM; if (!t) return;
    var b = $('tr-start'); b.disabled = true; b.innerHTML = '<span class="spin"></span>';
    api('/api/tools/uninstall', { slug: t.slug, confirm: $('tr-confirm').value.trim() }).then(function (res) {
      $('tool-rm-modal').hidden = true; b.textContent = 'Kaldır';
      $('tm-title').textContent = t.name + ' kaldırıldı'; $('tm-body').textContent = res.output || '';
      $('text-modal').hidden = false; loadTools();
    }).catch(function (err) { b.disabled = false; b.textContent = 'Kaldır'; show('tr-error', err.message); });
  }
  /* ---------------- CyberPanel menu editoru ---------------- */
  var MENU = { rows: [], icons: [], sugg: [], dirty: false };
  function loadMenu() {
    var tb = $('menu-table').querySelector('tbody');
    tb.innerHTML = '<tr><td colspan="6" class="empty"><span class="spin"></span></td></tr>';
    $('menu-msg').textContent = '';
    api('/api/menu').then(function (res) {
      MENU.rows = (res.entries || []).map(function (e) {
        return { orig: e.label, label: e.label, href: e.href, icon: e.icon, newtab: !!e.newtab };
      });
      MENU.icons = res.icons || []; MENU.sugg = res.suggestions || []; MENU.dirty = false;
      var notes = $('menu-notes'); notes.innerHTML = '';
      if (!(res.files || []).length) {
        notes.appendChild(el('div', 'error', 'CyberPanel şablonlarında AGFO menü grubu bulunamadı (' + (res.searched || []).join(', ') + '). Menüye en az bir AGFO girdisini agfo-ssh-menu paketiyle ekleyin.'));
      }
      MENU.sugg.forEach(function (s) { if (s.note) notes.appendChild(el('div', 'warn', s.label + ': ' + s.note)); });
      var sel = $('menu-backups'); sel.innerHTML = '';
      (res.backups || []).forEach(function (b) {
        var t = b.stamp;
        var o = el('option', '', t.slice(6, 8) + '.' + t.slice(4, 6) + '.' + t.slice(0, 4) + ' ' + t.slice(9, 11) + ':' + t.slice(11, 13) + ':' + t.slice(13, 15) + ' (' + b.files + ' dosya)');
        o.value = t; sel.appendChild(o);
      });
      if (!(res.backups || []).length) sel.appendChild(el('option', '', 'yedek yok'));
      $('btn-menu-restore').disabled = !(res.backups || []).length;
      renderMenu();
    }).catch(function (err) { tb.innerHTML = ''; toast(err.message, 6000); });
  }
  function menuDirty() { MENU.dirty = true; $('menu-msg').textContent = 'kaydedilmemiş değişiklik var'; }
  function renderMenu() {
    var tb = $('menu-table').querySelector('tbody'); tb.innerHTML = '';
    MENU.rows.forEach(function (r, i) {
      var tr = el('tr');
      var mv = el('td', 'menu-move');
      var up = el('button', 'btn small', '▲'); up.title = 'Yukarı'; up.disabled = i === 0;
      up.addEventListener('click', function () { var t = MENU.rows[i - 1]; MENU.rows[i - 1] = r; MENU.rows[i] = t; menuDirty(); renderMenu(); });
      var dn = el('button', 'btn small', '▼'); dn.title = 'Aşağı'; dn.disabled = i === MENU.rows.length - 1;
      dn.addEventListener('click', function () { var t = MENU.rows[i + 1]; MENU.rows[i + 1] = r; MENU.rows[i] = t; menuDirty(); renderMenu(); });
      mv.appendChild(up); mv.appendChild(dn); tr.appendChild(mv);
      var lt = el('td'); var li = el('input'); li.type = 'text'; li.value = r.label; li.maxLength = 60;
      li.addEventListener('input', function () { r.label = li.value; menuDirty(); });
      lt.appendChild(li); if (!r.orig) lt.appendChild(el('div', 'muted', 'yeni')); tr.appendChild(lt);
      var ht = el('td'); var hi = el('input'); hi.type = 'text'; hi.value = r.href; hi.spellcheck = false; hi.className = 'mono';
      hi.addEventListener('input', function () { r.href = hi.value.trim(); menuDirty(); });
      ht.appendChild(hi);
      if (/^https?:\/\/\d{1,3}(\.\d{1,3}){3}[:/]/.test(r.href)) ht.appendChild(el('div', 'warn small', 'IP adresi: tarayıcı sertifika uyarısı verebilir'));
      tr.appendChild(ht);
      var it = el('td'); var is = el('select');
      var icons = MENU.icons.slice(); if (r.icon && icons.indexOf(r.icon) < 0) icons.unshift(r.icon);
      if (!r.icon) is.appendChild(el('option', '', '(yok)'));
      icons.forEach(function (ic) { var o = el('option', '', ic.replace(/^fa-/, '')); o.value = ic; if (ic === r.icon) o.selected = true; is.appendChild(o); });
      is.addEventListener('change', function () { r.icon = is.value; menuDirty(); });
      it.appendChild(is); tr.appendChild(it);
      var nt = el('td'); var nc = el('input'); nc.type = 'checkbox'; nc.checked = r.newtab;
      nc.addEventListener('change', function () { r.newtab = nc.checked; menuDirty(); });
      nt.appendChild(nc); tr.appendChild(nt);
      var dt = el('td'); var del = el('button', 'btn small danger', 'Sil');
      del.addEventListener('click', function () { MENU.rows.splice(i, 1); menuDirty(); renderMenu(); });
      dt.appendChild(del); tr.appendChild(dt);
      tb.appendChild(tr);
    });
    if (!MENU.rows.length) tb.innerHTML = '<tr><td colspan="6" class="empty">Menüde AGFO girdisi yok.</td></tr>';
  }
  function menuSuggest() {
    var n = 0, added = 0;
    MENU.sugg.forEach(function (s) {
      var row = MENU.rows.filter(function (r) { return r.label === s.label || r.orig === s.label; })[0];
      if (row) {
        if (row.href !== s.href || !row.newtab) { row.href = s.href; row.newtab = true; n++; }
      } else {
        MENU.rows.push({ orig: '', label: s.label, href: s.href, icon: s.icon, newtab: true }); added++;
      }
    });
    MENU.rows.forEach(function (r) { if (!r.newtab) { r.newtab = true; n++; } });
    if (n || added) { menuDirty(); renderMenu(); }
    toast(n || added ? (n + ' girdi güncellendi, ' + added + ' girdi eklendi — Kaydet ile uygulayın') : 'Menü zaten kurulu panellerle uyumlu');
  }
  function menuSave() {
    var b = $('btn-menu-save'); b.disabled = true;
    api('/api/menu/save', { entries: MENU.rows.map(function (r) {
      return { orig: r.orig, label: r.label.trim(), href: r.href, icon: r.icon, newtab: r.newtab };
    }) }).then(function (res) {
      b.disabled = false;
      toast(res.changed.length ? ('Menü kaydedildi' + (res.restarted ? '; CyberPanel yeniden başlıyor, birkaç saniye sonra Ctrl+F5' : '; CyberPanel\'i yeniden başlatın')) : 'Değişiklik yok', 7000);
      loadMenu();
    }).catch(function (err) { b.disabled = false; toast(err.message, 8000); });
  }
  function menuRestore() {
    var stamp = $('menu-backups').value; if (!stamp) return;
    if (!confirm('Menü bu yedekteki hâline döndürülsün mü? (Şimdiki hâl de yedeklenir.)')) return;
    api('/api/menu/restore', { stamp: stamp }).then(function (res) {
      toast('Geri yüklendi' + (res.restarted ? '; CyberPanel yeniden başlıyor' : ''), 6000); loadMenu();
    }).catch(function (err) { toast(err.message, 7000); });
  }

  function openTab(name) {
    var tab = document.querySelector('.tab[data-tab="' + name + '"]'); if (tab) tab.click();
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
        if (!r.ok) {
          var ask = el('button', 'btn small', aiReady() ? "AI'ya sor" : "AI'ya sor (anahtar yok)");
          ask.disabled = !aiReady();
          ask.addEventListener('click', function () { repairApp(r.id); });
          row.appendChild(ask);
        }
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
    loadAI();
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
    $('im-domain').addEventListener('input', function () {
      Array.prototype.forEach.call(document.querySelectorAll('#im-suggest .sg'), function (b) { b.classList.remove('active'); });
      domainChanged();
    });
    $('im-path').addEventListener('input', domainChanged);
    $('um-start').addEventListener('click', startUninstall);
    $('tr-start').addEventListener('click', startToolRemove);
    $('btn-menu-add').addEventListener('click', function () { MENU.rows.push({ orig: '', label: '', href: 'https://', icon: 'fa-link', newtab: true }); menuDirty(); renderMenu(); });
    $('btn-menu-suggest').addEventListener('click', menuSuggest);
    $('btn-menu-save').addEventListener('click', menuSave);
    $('btn-menu-restore').addEventListener('click', menuRestore);
    $('btn-health-package').addEventListener('click', function () { runHealth('package'); });
    $('btn-health-trial').addEventListener('click', function () { runHealth('trial'); });
    $('btn-health-domain').addEventListener('click', function () {
      api('/api/health/test-domain', { domain: $('health-domain').value.trim() })
        .then(function () { toast('Test alan adı kaydedildi'); }).catch(function (e) { toast(e.message, 6000); });
    });
    $('tr-confirm').addEventListener('input', function () {
      $('tr-start').disabled = !TOOL_RM || this.value.trim() !== TOOL_RM.slug;
    });
    $('btn-ai-save').addEventListener('click', function () {
      api('/api/ai/settings', { provider: $('ai-provider').value, model: $('ai-model').value })
        .then(function () { $('ai-msg').textContent = 'Kaydedildi.'; loadAI(); })
        .catch(function (e) { $('ai-msg').textContent = e.message; });
    });
    $('btn-ai-test').addEventListener('click', function () {
      var p = $('ai-provider').value; if (!p) return;
      $('ai-msg').innerHTML = '<span class="spin"></span> deneniyor…';
      api('/api/ai/test', { provider: p }).then(function (res) {
        $('ai-msg').textContent = (res.valid ? '✓ ' : '✕ ') + res.message;
      }).catch(function (e) { $('ai-msg').textContent = e.message; });
    });
    $('btn-ai-add').addEventListener('click', function () {
      api('/api/ai/key', { provider: $('ai-new-provider').value, key: $('ai-new-key').value, model: $('ai-new-model').value })
        .then(function () { $('ai-new-key').value = ''; toast('Anahtar kaydedildi'); loadAI(); })
        .catch(function (e) { toast(e.message, 6000); });
    });
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
        if (tab.dataset.tab === 'tools') { loadTools(); loadMenu(); }
        if (tab.dataset.tab === 'settings') { loadAI(); loadOverrides(); loadHealth(); }
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
