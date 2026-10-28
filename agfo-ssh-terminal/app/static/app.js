/* AGFO SSH Terminal - istemci uygulamasi
 * Sekmeli terminaller, kayitli oturumlar, anahtar yoneticisi, arama ve temalar.
 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var QS = new URLSearchParams(location.search);
  var CSRF = '';
  var STATE = {};
  var TABS = [];
  var ACTIVE = null;
  var SEQ = 0;
  var MAX_TABS = 12;
  var LOG_CAP = 4 * 1024 * 1024;

  /* ------------------------------------------------------------------ */
  /* Temalar                                                            */
  /* ------------------------------------------------------------------ */
  var THEMES = {
    'agfo-dark': {
      background: '#0b0f14', foreground: '#e8eef6', cursor: '#2dd4bf', cursorAccent: '#0b0f14',
      selectionBackground: 'rgba(45,212,191,0.30)',
      black: '#1a2330', red: '#f87171', green: '#4ade80', yellow: '#fbbf24',
      blue: '#60a5fa', magenta: '#c084fc', cyan: '#2dd4bf', white: '#e8eef6',
      brightBlack: '#64748b', brightRed: '#fca5a5', brightGreen: '#86efac', brightYellow: '#fde047',
      brightBlue: '#93c5fd', brightMagenta: '#d8b4fe', brightCyan: '#5eead4', brightWhite: '#ffffff'
    },
    'putty-classic': {
      background: '#000000', foreground: '#bbbbbb', cursor: '#bbbbbb', cursorAccent: '#000000',
      selectionBackground: 'rgba(187,187,187,0.35)',
      black: '#000000', red: '#bb0000', green: '#00bb00', yellow: '#bbbb00',
      blue: '#0000bb', magenta: '#bb00bb', cyan: '#00bbbb', white: '#bbbbbb',
      brightBlack: '#555555', brightRed: '#ff5555', brightGreen: '#55ff55', brightYellow: '#ffff55',
      brightBlue: '#5555ff', brightMagenta: '#ff55ff', brightCyan: '#55ffff', brightWhite: '#ffffff'
    },
    'solarized-dark': {
      background: '#002b36', foreground: '#93a1a1', cursor: '#93a1a1', cursorAccent: '#002b36',
      selectionBackground: 'rgba(147,161,161,0.30)',
      black: '#073642', red: '#dc322f', green: '#859900', yellow: '#b58900',
      blue: '#268bd2', magenta: '#d33682', cyan: '#2aa198', white: '#eee8d5',
      brightBlack: '#586e75', brightRed: '#cb4b16', brightGreen: '#93a1a1', brightYellow: '#657b83',
      brightBlue: '#839496', brightMagenta: '#6c71c4', brightCyan: '#93a1a1', brightWhite: '#fdf6e3'
    },
    'matrix': {
      background: '#000000', foreground: '#33ff66', cursor: '#33ff66', cursorAccent: '#000000',
      selectionBackground: 'rgba(51,255,102,0.28)',
      black: '#001100', red: '#ff5555', green: '#33ff66', yellow: '#9fff4f',
      blue: '#22bb55', magenta: '#55ff99', cyan: '#44ffaa', white: '#ccffcc',
      brightBlack: '#115522', brightRed: '#ff8888', brightGreen: '#66ff99', brightYellow: '#ccff66',
      brightBlue: '#33dd77', brightMagenta: '#88ffbb', brightCyan: '#77ffcc', brightWhite: '#eaffea'
    },
    'light': {
      background: '#fdf6e3', foreground: '#1c1c1c', cursor: '#1c1c1c', cursorAccent: '#fdf6e3',
      selectionBackground: 'rgba(0,0,0,0.18)',
      black: '#073642', red: '#c0392b', green: '#1e8449', yellow: '#9a6700',
      blue: '#1f5fa9', magenta: '#8e44ad', cyan: '#17807a', white: '#eee8d5',
      brightBlack: '#5c6b73', brightRed: '#e74c3c', brightGreen: '#27ae60', brightYellow: '#b7791f',
      brightBlue: '#2980b9', brightMagenta: '#9b59b6', brightCyan: '#16a085', brightWhite: '#ffffff'
    }
  };

  var PREFS = (function () {
    var def = { theme: 'agfo-dark', fontSize: 14, copyOnSelect: true };
    try {
      var raw = localStorage.getItem('agfo-sshterm-prefs');
      if (raw) { var p = JSON.parse(raw); for (var k in def) { if (p[k] !== undefined) def[k] = p[k]; } }
    } catch (e) { /* yoksay */ }
    return def;
  })();

  function savePrefs() {
    try { localStorage.setItem('agfo-sshterm-prefs', JSON.stringify(PREFS)); } catch (e) { /* yoksay */ }
  }

  /* ------------------------------------------------------------------ */
  /* Yardimcilar                                                        */
  /* ------------------------------------------------------------------ */
  function toast(msg, ms) {
    var el = $('toast');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.hidden = true; }, ms || 2600);
  }

  function showError(id, msg) {
    var el = $(id);
    if (!el) return;
    if (!msg) { el.hidden = true; el.textContent = ''; return; }
    el.classList.remove('ok');
    el.textContent = msg;
    el.hidden = false;
  }

  function showOk(id, msg) {
    var el = $(id);
    el.classList.add('ok');
    el.textContent = msg;
    el.hidden = false;
  }

  function humanBytes(n) {
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1048576).toFixed(2) + ' MB';
  }

  function api(path, body) {
    var opts = {
      method: body ? 'POST' : 'GET',
      headers: { 'Accept': 'application/json' },
      credentials: 'same-origin'
    };
    if (body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-AGFO-CSRF'] = CSRF;
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (res.status === 401 && path !== '/api/login') { gotoLogin(); throw new Error('Oturum süresi doldu'); }
        if (!res.ok || data.ok === false) {
          var map = {
            bad_password: 'Şifre hatalı.',
            locked: 'Çok fazla hatalı deneme. Bir süre bekleyin.',
            csrf: 'Oturum doğrulaması başarısız, sayfayı yenileyin.',
            bad_name: 'Geçersiz ad.',
            too_large: 'Dosya çok büyük.',
            not_a_private_key: 'İçerik bir özel anahtar gibi görünmüyor.',
            too_short: 'Şifre en az 10 karakter olmalı.',
            ip_not_allowed: 'IP adresiniz izinli listede değil.',
            no_password_configured: 'Sunucuda panel şifresi tanımlı değil.'
          };
          throw new Error(map[data.error] || data.error || ('HTTP ' + res.status));
        }
        return data;
      });
    });
  }

  function gotoLogin() {
    $('app').hidden = true;
    $('login').hidden = false;
    TABS.slice().forEach(function (t) { closeTab(t, true); });
  }

  /* ------------------------------------------------------------------ */
  /* Terminal sekmesi                                                   */
  /* ------------------------------------------------------------------ */
  function Tab(label, request) {
    this.id = 'tab' + (++SEQ);
    this.label = label;
    this.request = request;
    this.state = 'connecting';
    this.bytes = 0;
    this.latency = null;
    this.logText = '';
    this.decoder = new TextDecoder('utf-8', { fatal: false });
    this.buildDom();
    this.buildTerm();
    this.connect();
  }

  Tab.prototype.buildDom = function () {
    var self = this;
    this.wrap = document.createElement('div');
    this.wrap.className = 'term-wrap';
    $('terminals').appendChild(this.wrap);

    this.tabEl = document.createElement('div');
    this.tabEl.className = 'tab';
    var dot = document.createElement('span'); dot.className = 'dot';
    var name = document.createElement('span'); name.textContent = this.label;
    var x = document.createElement('span'); x.className = 'x'; x.textContent = '✕'; x.title = 'Kapat';
    this.tabEl.appendChild(dot); this.tabEl.appendChild(name); this.tabEl.appendChild(x);
    this.tabEl.addEventListener('click', function (ev) {
      if (ev.target === x) { closeTab(self); return; }
      activate(self);
    });
    $('tabs').appendChild(this.tabEl);
  };

  Tab.prototype.buildTerm = function () {
    var self = this;
    this.term = new Terminal({
      fontFamily: 'ui-monospace, "JetBrains Mono", "Cascadia Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace',
      fontSize: PREFS.fontSize,
      theme: THEMES[PREFS.theme] || THEMES['agfo-dark'],
      cursorBlink: true,
      cursorStyle: 'block',
      scrollback: (STATE.defaults && STATE.defaults.scrollback) || 5000,
      allowProposedApi: true,
      macOptionIsMeta: true,
      rightClickSelectsWord: false,
      convertEol: false,
      windowsMode: false
    });
    this.fit = new FitAddon.FitAddon();
    this.term.loadAddon(this.fit);
    try { this.term.loadAddon(new WebLinksAddon.WebLinksAddon()); } catch (e) { /* yoksay */ }
    this.search = new SearchAddon.SearchAddon();
    this.term.loadAddon(this.search);
    this.term.open(this.wrap);

    this.term.onData(function (data) { self.sendText(data); });
    this.term.onBinary(function (data) {
      var buf = new Uint8Array(data.length);
      for (var i = 0; i < data.length; i++) { buf[i] = data.charCodeAt(i) & 255; }
      self.sendBytes(buf);
    });
    this.term.onResize(function (size) {
      self.sendJson({ t: 'resize', cols: size.cols, rows: size.rows });
      if (ACTIVE === self) { $('st-size').textContent = size.cols + '×' + size.rows; }
    });
    this.term.onSelectionChange(function () {
      if (!PREFS.copyOnSelect) return;
      var sel = self.term.getSelection();
      if (sel && navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(sel).catch(function () { /* yoksay */ });
      }
    });
    this.term.attachCustomKeyEventHandler(function (ev) { return keyHandler(self, ev); });

    this.ro = new ResizeObserver(function () { self.refit(); });
    this.ro.observe(this.wrap);
  };

  Tab.prototype.refit = function () {
    if (!this.term || this.wrap.offsetParent === null) return;
    try { this.fit.fit(); } catch (e) { /* yoksay */ }
  };

  Tab.prototype.connect = function () {
    var self = this;
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var ws = new WebSocket(proto + '//' + location.host + '/ws');
    ws.binaryType = 'arraybuffer';
    this.ws = ws;
    this.setState('connecting');

    ws.onopen = function () {
      self.refit();
      var req = JSON.parse(JSON.stringify(self.request));
      req.t = 'open';
      req.cols = self.term.cols;
      req.rows = self.term.rows;
      ws.send(JSON.stringify(req));
      self.pingTimer = setInterval(function () {
        if (ws.readyState === 1) { ws.send(JSON.stringify({ t: 'ping', ts: Date.now() })); }
      }, 5000);
    };

    ws.onmessage = function (ev) {
      if (typeof ev.data === 'string') { self.onControl(ev.data); return; }
      var bytes = new Uint8Array(ev.data);
      self.bytes += bytes.length;
      self.term.write(bytes);
      if (self.logText.length < LOG_CAP) {
        self.logText += self.decoder.decode(bytes, { stream: true });
      }
      if (ACTIVE === self) { $('st-bytes').textContent = humanBytes(self.bytes); }
    };

    ws.onclose = function () {
      clearInterval(self.pingTimer);
      if (self.state !== 'closed') {
        self.setState('dead');
        self.term.write('\r\n\x1b[1;33m[bağlantı kapandı]\x1b[0m\r\n');
      }
    };

    ws.onerror = function () { /* onclose zaten devrede */ };
  };

  Tab.prototype.onControl = function (raw) {
    var msg;
    try { msg = JSON.parse(raw); } catch (e) { return; }
    if (msg.t === 'ready') {
      this.setState('live');
      this.cmd = msg.cmd || '';
      if (msg.log) { toast('Oturum kaydı: ' + msg.log, 4200); }
      this.term.focus();
      this.refit();
    } else if (msg.t === 'exit') {
      this.setState('dead');
      this.term.write('\r\n\x1b[1;33m[oturum sona erdi' + (msg.code === null || msg.code === undefined ? '' : ', çıkış kodu ' + msg.code) + ']\x1b[0m\r\n');
      this.term.write('\x1b[2;37m[alt çubuktaki "Yeniden bağlan" ile aynı ayarlarla tekrar bağlanabilirsiniz]\x1b[0m\r\n');
    } else if (msg.t === 'error') {
      this.setState('dead');
      this.term.write('\r\n\x1b[1;31m[hata] ' + msg.msg + '\x1b[0m\r\n');
      toast(msg.msg, 5000);
    } else if (msg.t === 'info') {
      this.term.write('\r\n\x1b[1;36m[bilgi] ' + msg.msg + '\x1b[0m\r\n');
    } else if (msg.t === 'pong') {
      this.latency = Date.now() - (msg.ts || Date.now());
      if (ACTIVE === this) { $('st-latency').textContent = this.latency + ' ms'; }
    }
  };

  Tab.prototype.setState = function (s) {
    this.state = s;
    this.tabEl.classList.toggle('live', s === 'live');
    this.tabEl.classList.toggle('dead', s === 'dead' || s === 'closed');
    if (ACTIVE === this) { paintStatus(this); }
  };

  Tab.prototype.sendJson = function (obj) {
    if (this.ws && this.ws.readyState === 1) { this.ws.send(JSON.stringify(obj)); }
  };

  Tab.prototype.sendText = function (text) {
    this.sendBytes(new TextEncoder().encode(text));
  };

  Tab.prototype.sendBytes = function (bytes) {
    if (this.ws && this.ws.readyState === 1) { this.ws.send(bytes); }
  };

  Tab.prototype.paste = function () {
    var self = this;
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.readText().then(function (text) {
        if (text) { self.term.paste(text); }
      }).catch(function () { toast('Pano okunamadı; Ctrl+V veya sağ tık kullanın.'); });
    } else {
      toast('Pano erişimi için HTTPS gerekir; sağ tık ile yapıştırın.');
    }
  };

  Tab.prototype.dispose = function () {
    this.state = 'closed';
    clearInterval(this.pingTimer);
    try { if (this.ro) this.ro.disconnect(); } catch (e) { /* yoksay */ }
    try { this.sendJson({ t: 'close' }); } catch (e) { /* yoksay */ }
    try { if (this.ws) this.ws.close(); } catch (e) { /* yoksay */ }
    try { this.term.dispose(); } catch (e) { /* yoksay */ }
    if (this.wrap.parentNode) { this.wrap.parentNode.removeChild(this.wrap); }
    if (this.tabEl.parentNode) { this.tabEl.parentNode.removeChild(this.tabEl); }
  };

  /* ------------------------------------------------------------------ */
  /* Sekme yonetimi                                                     */
  /* ------------------------------------------------------------------ */
  function openTab(label, request) {
    if (TABS.length >= MAX_TABS) { toast('En fazla ' + MAX_TABS + ' sekme açılabilir.'); return null; }
    var tab = new Tab(label, request);
    TABS.push(tab);
    activate(tab);
    return tab;
  }

  function activate(tab) {
    ACTIVE = tab;
    TABS.forEach(function (t) {
      var on = t === tab;
      t.wrap.classList.toggle('active', on);
      t.tabEl.classList.toggle('active', on);
    });
    $('empty-state').hidden = TABS.length > 0;
    $('terminals').style.display = TABS.length ? 'block' : 'none';
    if (tab) {
      tab.refit();
      tab.term.focus();
      paintStatus(tab);
    } else {
      paintStatus(null);
    }
  }

  function closeTab(tab, silent) {
    var idx = TABS.indexOf(tab);
    if (idx < 0) return;
    TABS.splice(idx, 1);
    tab.dispose();
    if (!silent) {
      var next = TABS[Math.min(idx, TABS.length - 1)] || null;
      activate(next);
    }
  }

  function paintStatus(tab) {
    var st = $('st-state');
    if (!tab) {
      st.textContent = 'hazır'; st.className = 'pill';
      $('btn-reconnect').hidden = true;
      $('st-target').textContent = '';
      $('st-size').textContent = '';
      $('st-bytes').textContent = '';
      $('st-latency').textContent = '';
      return;
    }
    var map = {
      connecting: ['bağlanıyor', 'pill busy'],
      live: ['bağlı', 'pill live'],
      dead: ['kapandı', 'pill dead'],
      closed: ['kapalı', 'pill dead']
    };
    var info = map[tab.state] || ['?', 'pill'];
    st.textContent = info[0];
    st.className = info[1];
    $('btn-reconnect').hidden = (tab.state !== 'dead' && tab.state !== 'closed');
    $('st-target').textContent = tab.cmd || tab.label;
    $('st-size').textContent = tab.term.cols + '×' + tab.term.rows;
    $('st-bytes').textContent = humanBytes(tab.bytes);
    $('st-latency').textContent = tab.latency === null ? '' : tab.latency + ' ms';
  }

  /* ------------------------------------------------------------------ */
  /* Klavye kisayollari                                                 */
  /* ------------------------------------------------------------------ */
  // Kisayollar tek bir yerde (belge duzeyinde) islenir; xterm bu tuslari
  // kabuga gondermesin diye yalnizca 'false' dondurur.
  var SHORTCUT_KEYS = ['c', 'v', 'f', 'w', 'l', 'n'];

  function keyHandler(tab, ev) {
    if (ev.type !== 'keydown') return true;
    if (ev.ctrlKey && ev.shiftKey && !ev.altKey && SHORTCUT_KEYS.indexOf(ev.key.toLowerCase()) >= 0) {
      return false;
    }
    if (ev.altKey && !ev.ctrlKey && /^[1-9]$/.test(ev.key)) { return false; }
    if (ev.key === 'Insert' && (ev.shiftKey || ev.ctrlKey)) { return false; }
    return true;
  }

  function copyActiveSelection() {
    if (!ACTIVE) return false;
    var sel = ACTIVE.term.getSelection();
    if (!sel) return false;
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(sel).catch(function () { /* yoksay */ });
    }
    toast('Kopyalandı');
    return true;
  }

  function globalKeys(ev) {
    // PuTTY aliskanligi: Shift+Insert yapistir, Ctrl+Insert kopyala
    if (ev.key === 'Insert' && ev.shiftKey && ACTIVE) { ev.preventDefault(); ACTIVE.paste(); return; }
    if (ev.key === 'Insert' && ev.ctrlKey) { if (copyActiveSelection()) ev.preventDefault(); return; }

    if (ev.altKey && !ev.ctrlKey && /^[1-9]$/.test(ev.key)) {
      var t = TABS[parseInt(ev.key, 10) - 1];
      if (t) { ev.preventDefault(); activate(t); }
      return;
    }
    if (!(ev.ctrlKey && ev.shiftKey) || ev.altKey) return;
    var k = ev.key.toLowerCase();
    if (k === 'c') { if (copyActiveSelection()) ev.preventDefault(); return; }
    if (k === 'v') { if (ACTIVE) { ev.preventDefault(); ACTIVE.paste(); } return; }
    if (k === 'f') { ev.preventDefault(); toggleSearch(true); return; }
    if (k === 'w') { if (ACTIVE) { ev.preventDefault(); closeTab(ACTIVE); } return; }
    if (k === 'l') { ev.preventDefault(); quickRootShell(); return; }
    if (k === 'n') { ev.preventDefault(); $('sidebar').classList.remove('hidden'); $('f-host').focus(); return; }
  }

  function toggleSearch(show) {
    var bar = $('search-bar');
    bar.hidden = !show;
    if (show) { $('search-input').focus(); $('search-input').select(); }
    else if (ACTIVE) { try { ACTIVE.search.clearDecorations(); } catch (e) { /* yoksay */ } ACTIVE.term.focus(); }
  }

  function runSearch(dir) {
    if (!ACTIVE) return;
    var q = $('search-input').value;
    if (!q) return;
    var opts = { decorations: { matchBackground: '#fbbf24', activeMatchBackground: '#2dd4bf' }, caseSensitive: false };
    if (dir < 0) { ACTIVE.search.findPrevious(q, opts); } else { ACTIVE.search.findNext(q, opts); }
  }

  /* ------------------------------------------------------------------ */
  /* Baglanti istekleri                                                 */
  /* ------------------------------------------------------------------ */
  function requestFromForm() {
    var mode = $('f-mode').value;
    if (mode === 'local') { return { mode: 'local', log: $('f-log').checked }; }
    return {
      mode: 'ssh',
      host: $('f-host').value.trim(),
      port: parseInt($('f-port').value, 10) || 22,
      user: $('f-user').value.trim(),
      identity: $('f-identity').value,
      jump: $('f-jump').value.trim(),
      extra: $('f-extra').value.trim(),
      command: $('f-command').value.trim(),
      agent: $('f-agent').checked,
      compression: $('f-compression').checked,
      keepalive: parseInt($('f-keepalive').value, 10) || 30,
      host_key_policy: $('f-policy').value,
      log: $('f-log').checked
    };
  }

  function labelFor(req) {
    if (req.mode === 'local') return 'root@' + (STATE.hostname || 'sunucu');
    return (req.user || 'ssh') + '@' + (req.host || '?') + (req.port && req.port !== 22 ? ':' + req.port : '');
  }

  function connectFromForm() {
    showError('conn-error', '');
    var req = requestFromForm();
    if (req.mode === 'ssh' && !req.host) { showError('conn-error', 'Host/IP girin.'); return; }
    openTab($('f-name').value.trim() || labelFor(req), req);
  }

  function quickRootShell() {
    openTab('root@' + (STATE.hostname || 'sunucu'), { mode: 'local', log: false });
  }

  // Menu linki dogrudan calisan bir terminalle acilsin diye:
  //   ?open=root       -> sunucunun yerel root kabugu
  //   ?open=localhost  -> root@127.0.0.1 SSH
  //   ?open=<oturum>   -> kayitli oturum adi veya kimligi
  function autoOpen() {
    var what = (QS.get('open') || '').trim();
    if (!what) return;
    var lower = what.toLowerCase();
    if (lower === 'root' || lower === 'local' || lower === 'shell') { quickRootShell(); }
    else if (lower === 'localhost') { quickRootSsh(); }
    else {
      var items = STATE.profiles || [], found = null;
      for (var i = 0; i < items.length; i++) {
        if (items[i].id === what || (items[i].name || '').toLowerCase() === lower) { found = items[i]; break; }
      }
      if (!found) { toast('Otomatik açılacak oturum bulunamadı: ' + what, 4000); return; }
      fillForm(found);
      openTab(found.name, profileToRequest(found));
    }
    if (document.body.classList.contains('embed')) {
      $('sidebar').classList.add('hidden');
      setTimeout(function () { if (ACTIVE) ACTIVE.refit(); }, 80);
    }
  }

  function quickRootSsh() {
    openTab('root@127.0.0.1', {
      mode: 'ssh', host: '127.0.0.1', port: 22, user: 'root',
      host_key_policy: 'accept-new', keepalive: 30, log: false
    });
  }

  /* ------------------------------------------------------------------ */
  /* Profiller                                                          */
  /* ------------------------------------------------------------------ */
  function renderProfiles() {
    var ul = $('profile-list');
    ul.innerHTML = '';
    var items = STATE.profiles || [];
    if (!items.length) {
      var li = document.createElement('li');
      li.className = 'pempty';
      li.textContent = 'Henüz kayıtlı oturum yok.';
      ul.appendChild(li);
      return;
    }
    items.forEach(function (p) {
      var li = document.createElement('li');
      li.dataset.id = p.id;
      var box = document.createElement('div');
      var n = document.createElement('div'); n.className = 'pname'; n.textContent = p.name;
      var t = document.createElement('div'); t.className = 'ptarget';
      t.textContent = p.mode === 'local' ? 'yerel root kabuğu'
        : (p.user || '') + '@' + (p.host || '') + (p.port && p.port !== 22 ? ':' + p.port : '');
      box.appendChild(n); box.appendChild(t);
      var go = document.createElement('span'); go.className = 'pgo'; go.textContent = 'bağlan';
      li.appendChild(box); li.appendChild(go);
      li.addEventListener('click', function (ev) {
        fillForm(p);
        Array.prototype.forEach.call(ul.children, function (c) { c.classList.remove('active'); });
        li.classList.add('active');
        if (ev.target === go) { openTab(p.name, profileToRequest(p)); }
      });
      li.addEventListener('dblclick', function () { openTab(p.name, profileToRequest(p)); });
      ul.appendChild(li);
    });
  }

  function profileToRequest(p) {
    if (p.mode === 'local') { return { mode: 'local', log: !!p.log }; }
    return {
      mode: 'ssh', host: p.host, port: p.port, user: p.user, identity: p.identity,
      jump: p.jump, extra: p.extra, command: p.command, agent: !!p.agent,
      compression: !!p.compression, keepalive: p.keepalive,
      host_key_policy: p.host_key_policy, log: !!p.log
    };
  }

  function fillForm(p) {
    $('f-mode').value = p.mode || 'ssh';
    $('f-host').value = p.host || '';
    $('f-port').value = p.port || 22;
    $('f-user').value = p.user || 'root';
    $('f-identity').value = p.identity || '';
    $('f-jump').value = p.jump || '';
    $('f-extra').value = p.extra || '';
    $('f-command').value = p.command || '';
    $('f-agent').checked = !!p.agent;
    $('f-compression').checked = !!p.compression;
    $('f-log').checked = !!p.log;
    $('f-keepalive').value = p.keepalive || 30;
    $('f-policy').value = p.host_key_policy || 'accept-new';
    $('f-name').value = p.name || '';
    $('conn-form').dataset.pid = p.id || '';
    $('btn-delete-profile').hidden = !p.id;
    syncModeUi();
  }

  function clearForm() {
    fillForm({ mode: 'ssh', port: 22, user: 'root', keepalive: 30, host_key_policy: 'accept-new' });
    $('conn-form').dataset.pid = '';
    $('btn-delete-profile').hidden = true;
    Array.prototype.forEach.call($('profile-list').children, function (c) { c.classList.remove('active'); });
  }

  function saveProfile() {
    showError('conn-error', '');
    var name = $('f-name').value.trim();
    if (!name) { showError('conn-error', 'Kaydetmek için bir oturum adı girin.'); return; }
    var req = requestFromForm();
    var prof = {
      id: $('conn-form').dataset.pid || '',
      name: name, mode: req.mode, host: req.host || '', port: req.port || 22,
      user: req.user || '', identity: req.identity || '', jump: req.jump || '',
      extra: req.extra || '', command: req.command || '', agent: !!req.agent,
      compression: !!req.compression, keepalive: req.keepalive || 30,
      host_key_policy: req.host_key_policy || 'accept-new', log: !!req.log,
      theme: PREFS.theme, font_size: PREFS.fontSize
    };
    api('/api/profiles', { action: 'save', profile: prof }).then(function (res) {
      STATE.profiles = res.profiles;
      renderProfiles();
      $('conn-form').dataset.pid = res.saved.id;
      $('btn-delete-profile').hidden = false;
      toast('Oturum kaydedildi');
    }).catch(function (err) { showError('conn-error', err.message); });
  }

  function deleteProfile() {
    var pid = $('conn-form').dataset.pid;
    if (!pid) return;
    api('/api/profiles', { action: 'delete', id: pid }).then(function (res) {
      STATE.profiles = res.profiles;
      renderProfiles();
      clearForm();
      toast('Oturum silindi');
    }).catch(function (err) { showError('conn-error', err.message); });
  }

  function syncModeUi() {
    var local = $('f-mode').value === 'local';
    Array.prototype.forEach.call(document.querySelectorAll('.ssh-only'), function (el) {
      el.style.display = local ? 'none' : '';
    });
  }

  /* ------------------------------------------------------------------ */
  /* Anahtarlar                                                         */
  /* ------------------------------------------------------------------ */
  function renderKeys() {
    var ul = $('keys-list');
    ul.innerHTML = '';
    var keys = STATE.keys || [];
    if (!keys.length) {
      var li = document.createElement('li');
      li.textContent = 'Kayıtlı anahtar yok.';
      li.className = 'muted';
      ul.appendChild(li);
    }
    keys.forEach(function (k) {
      var li = document.createElement('li');
      var n = document.createElement('span'); n.className = 'kname'; n.textContent = k.name;
      var s = document.createElement('span'); s.className = 'muted'; s.textContent = humanBytes(k.size);
      var del = document.createElement('button');
      del.className = 'btn danger-ghost'; del.textContent = 'Sil';
      del.style.marginLeft = 'auto';
      del.addEventListener('click', function () {
        api('/api/keys', { action: 'delete', name: k.name }).then(function (res) {
          STATE.keys = res.keys; renderKeys(); renderKeyOptions(); toast('Anahtar silindi');
        }).catch(function (err) { showError('keys-error', err.message); });
      });
      li.appendChild(n); li.appendChild(s); li.appendChild(del);
      ul.appendChild(li);
    });
    renderKeyOptions();
  }

  function renderKeyOptions() {
    var sel = $('f-identity');
    var current = sel.value;
    sel.innerHTML = '';
    var none = document.createElement('option');
    none.value = ''; none.textContent = '(yok / şifre ile)';
    sel.appendChild(none);
    (STATE.keys || []).forEach(function (k) {
      var o = document.createElement('option');
      o.value = k.name; o.textContent = k.name;
      sel.appendChild(o);
    });
    sel.value = current;
  }

  function uploadKey() {
    showError('keys-error', '');
    var name = $('key-name').value.trim();
    var content = $('key-content').value;
    if (!name) { showError('keys-error', 'Dosya adı girin.'); return; }
    if (!content.trim()) { showError('keys-error', 'Anahtar içeriğini yapıştırın.'); return; }
    api('/api/keys', { action: 'upload', name: name, content: content }).then(function (res) {
      STATE.keys = res.keys;
      renderKeys();
      $('key-content').value = '';
      toast('Anahtar yüklendi');
    }).catch(function (err) { showError('keys-error', err.message); });
  }

  /* ------------------------------------------------------------------ */
  /* Tema / yazi boyutu                                                 */
  /* ------------------------------------------------------------------ */
  function applyTheme(name) {
    PREFS.theme = name;
    savePrefs();
    var theme = THEMES[name] || THEMES['agfo-dark'];
    TABS.forEach(function (t) { t.term.options.theme = theme; });
    $('terminals').style.background = theme.background;
  }

  function applyFontSize(size) {
    PREFS.fontSize = Math.max(8, Math.min(28, size));
    savePrefs();
    $('font-size-label').textContent = PREFS.fontSize;
    TABS.forEach(function (t) { t.term.options.fontSize = PREFS.fontSize; t.refit(); });
  }

  function downloadLog() {
    if (!ACTIVE) { toast('Açık sekme yok.'); return; }
    var name = 'agfo-terminal-' + ACTIVE.label.replace(/[^A-Za-z0-9._@-]/g, '_') + '-' +
      new Date().toISOString().replace(/[:.]/g, '-') + '.log';
    var blob = new Blob([ACTIVE.logText], { type: 'text/plain;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  /* ------------------------------------------------------------------ */
  /* Ayarlar                                                            */
  /* ------------------------------------------------------------------ */
  function renderSettings() {
    var rows = [
      ['Sürüm', STATE.version || '-'],
      ['Sunucu', STATE.hostname || '-'],
      ['TLS', STATE.tls ? 'açık' : 'kapalı'],
      ['ssh istemcisi', STATE.ssh_available ? 'bulundu' : 'YOK (yalnızca yerel kabuk)'],
      ['Oturum kaydı', STATE.session_log ? 'açık' : 'kapalı'],
      ['Etkin oturum', (STATE.active_sessions || 0) + ' / ' + (STATE.max_sessions || '-')]
    ];
    var grid = $('settings-info');
    grid.innerHTML = '';
    rows.forEach(function (r) {
      var b = document.createElement('b'); b.textContent = r[0];
      var v = document.createElement('span'); v.textContent = r[1];
      grid.appendChild(b); grid.appendChild(v);
    });
  }

  function changePassword() {
    showError('settings-msg', '');
    var cur = $('pw-current').value, nw = $('pw-new').value;
    if (!cur || !nw) { showError('settings-msg', 'Her iki alanı doldurun.'); return; }
    api('/api/password', { current: cur, new: nw }).then(function () {
      $('pw-current').value = ''; $('pw-new').value = '';
      showOk('settings-msg', 'Şifre güncellendi.');
    }).catch(function (err) { showError('settings-msg', err.message); });
  }

  /* ------------------------------------------------------------------ */
  /* Baslatma                                                           */
  /* ------------------------------------------------------------------ */
  function initApp(state) {
    STATE = state;
    CSRF = state.csrf || '';
    $('login').hidden = true;
    $('app').hidden = false;
    $('host-chip').textContent = state.hostname + ' · v' + state.version;
    $('theme-select').value = PREFS.theme;
    $('font-size-label').textContent = PREFS.fontSize;
    $('terminals').style.background = (THEMES[PREFS.theme] || THEMES['agfo-dark']).background;
    if (state.defaults && state.defaults.keepalive) { $('f-keepalive').value = state.defaults.keepalive; }
    if (!state.session_log) { $('f-log').disabled = true; $('f-log').parentNode.title = 'Sunucu yapılandırmasında oturum kaydı kapalı'; }
    renderProfiles();
    renderKeys();
    renderSettings();
    clearForm();
    if (!state.ssh_available) {
      toast('Uyarı: sunucuda ssh istemcisi yok; yalnızca yerel kabuk çalışır.', 6000);
    }
    autoOpen();
  }

  function boot() {
    api('/api/state').then(function (state) {
      if (state.authenticated) { initApp(state); }
      else {
        $('login').hidden = false;
        $('login-foot').textContent = state.app + ' v' + state.version + ' · ' + state.hostname +
          (state.tls ? ' · TLS açık' : ' · TLS KAPALI');
        if (!state.password_set) { showError('login-error', 'Sunucuda panel şifresi tanımlı değil. Kurulum betiğini çalıştırın.'); }
        $('login-pass').focus();
      }
    }).catch(function (err) {
      $('login').hidden = false;
      showError('login-error', 'Sunucuya ulaşılamadı: ' + err.message);
    });
  }

  function wire() {
    // Panel icine gomulu kullanim: ?embed=1 ile markayi gizleyip ust bari daraltir
    if (QS.get('embed') === '1' || QS.get('embed') === 'true') {
      document.body.classList.add('embed');
    }

    $('login-form').addEventListener('submit', function (ev) {
      ev.preventDefault();
      showError('login-error', '');
      var pass = $('login-pass').value;
      api('/api/login', { password: pass }).then(function () {
        $('login-pass').value = '';
        boot();
      }).catch(function (err) { showError('login-error', err.message); });
    });

    $('conn-form').addEventListener('submit', function (ev) { ev.preventDefault(); connectFromForm(); });
    $('btn-save-profile').addEventListener('click', saveProfile);
    $('btn-delete-profile').addEventListener('click', deleteProfile);
    $('btn-new-profile').addEventListener('click', clearForm);
    $('f-mode').addEventListener('change', syncModeUi);

    $('btn-root-shell').addEventListener('click', quickRootShell);
    $('btn-root-ssh').addEventListener('click', quickRootSsh);
    $('empty-root-shell').addEventListener('click', quickRootShell);
    $('empty-root-ssh').addEventListener('click', quickRootSsh);

    $('theme-select').addEventListener('change', function () { applyTheme(this.value); });
    $('btn-font-up').addEventListener('click', function () { applyFontSize(PREFS.fontSize + 1); });
    $('btn-font-down').addEventListener('click', function () { applyFontSize(PREFS.fontSize - 1); });
    $('btn-dl-log').addEventListener('click', downloadLog);
    $('btn-reconnect').addEventListener('click', function () {
      if (!ACTIVE) return;
      var label = ACTIVE.label, req = ACTIVE.request;
      closeTab(ACTIVE);
      openTab(label, req);
    });
    $('btn-sidebar').addEventListener('click', function () {
      $('sidebar').classList.toggle('hidden');
      setTimeout(function () { if (ACTIVE) ACTIVE.refit(); }, 60);
    });

    $('btn-keys').addEventListener('click', function () { showError('keys-error', ''); $('keys-modal').hidden = false; });
    $('btn-key-upload').addEventListener('click', uploadKey);
    $('key-file').addEventListener('change', function () {
      var f = this.files && this.files[0];
      if (!f) return;
      var reader = new FileReader();
      reader.onload = function () {
        $('key-content').value = String(reader.result || '');
        if (!$('key-name').value.trim()) {
          $('key-name').value = f.name.replace(/[^A-Za-z0-9._-]/g, '_').slice(0, 64);
        }
      };
      reader.readAsText(f);
    });

    $('btn-settings').addEventListener('click', function () {
      api('/api/state').then(function (s) { STATE = Object.assign(STATE, s); renderSettings(); });
      showError('settings-msg', '');
      $('settings-modal').hidden = false;
    });
    $('btn-pw-save').addEventListener('click', changePassword);

    $('btn-logout').addEventListener('click', function () {
      api('/api/logout', { bye: 1 }).catch(function () { /* yoksay */ }).then(gotoLogin);
    });

    Array.prototype.forEach.call(document.querySelectorAll('[data-close]'), function (btn) {
      btn.addEventListener('click', function () { $(btn.dataset.close).hidden = true; });
    });
    Array.prototype.forEach.call(document.querySelectorAll('.overlay'), function (ov) {
      ov.addEventListener('click', function (ev) {
        if (ev.target === ov && ov.id !== 'login') { ov.hidden = true; }
      });
    });

    $('search-next').addEventListener('click', function () { runSearch(1); });
    $('search-prev').addEventListener('click', function () { runSearch(-1); });
    $('search-close').addEventListener('click', function () { toggleSearch(false); });
    $('search-input').addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { runSearch(ev.shiftKey ? -1 : 1); }
      if (ev.key === 'Escape') { toggleSearch(false); }
    });

    document.addEventListener('keydown', function (ev) {
      globalKeys(ev);
      if (ev.key === 'Escape') {
        ['keys-modal', 'settings-modal'].forEach(function (id) { $(id).hidden = true; });
        if (!$('search-bar').hidden) { toggleSearch(false); }
      }
    });

    window.addEventListener('resize', function () { if (ACTIVE) ACTIVE.refit(); });
    window.addEventListener('beforeunload', function (ev) {
      if (TABS.some(function (t) { return t.state === 'live'; })) {
        ev.preventDefault();
        ev.returnValue = 'Açık terminal oturumları var.';
        return ev.returnValue;
      }
    });

    // Orta tus ile yapistirma (PuTTY aliskanligi)
    $('terminals').addEventListener('auxclick', function (ev) {
      if (ev.button === 1 && ACTIVE) { ev.preventDefault(); ACTIVE.paste(); }
    });
  }

  wire();
  boot();
})();
