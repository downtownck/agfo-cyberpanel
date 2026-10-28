# -*- coding: utf-8 -*-
"""Kurulum motoru.

* Siteyi, veritabanini ve SSL'i CyberPanel'in kendi komut satiriyla olusturur,
  boylece kurulan her sey panelin kayitlarinda da gorunur.
* Uygulama tarifindeki adimlari KABUK KULLANMADAN, arguman listesiyle calistirir.
* Her kurulum bir "is" (job) olarak arka planda yurur; gunlugu canli izlenir.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import string
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import catalog
import store

DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")
NAME_RE = re.compile(r"^[a-zA-Z0-9_]{1,32}$")
USER_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,32}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-zA-Z]{2,20}$")
SAFE_REL = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")

# Site dizinlerinin kokü. Uretimde /home; testlerde degistirilebilir.
HOME_BASE = os.environ.get("AGFO_STORE_HOME_BASE", "/home")

RUNNING = {"count": 0}
_run_lock = threading.Lock()


class InstallError(Exception):
    pass


# ---------------------------------------------------------------------------
# yardimcilar
# ---------------------------------------------------------------------------

def random_password(length=20):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def php_binary(version=None):
    version = (version or store.CFG.get("cyberpanel", "default_php", default="8.2") or "8.2")
    compact = version.replace(".", "")
    template = os.environ.get("AGFO_STORE_PHP_TEMPLATE", "/usr/local/lsws/lsphp{v}/bin/php")
    for candidate in (template.replace("{v}", compact), "/usr/bin/php%s" % version):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    # Baska surume sessizce dusmek, uygulamayi yanlis PHP ile kurmak demektir.
    raise InstallError("PHP %s bu sunucuda kurulu degil (lsphp%s). "
                       "CyberPanel > PHP > Install PHP ile kurun." % (version, compact))


def _ver(text):
    try:
        return tuple(int(x) for x in str(text).split(".")[:2])
    except ValueError:
        return (0, 0)


_MODULES = {}


def php_modules(version):
    """Bir lsphp surumunde yuklu PHP eklentileri (kucuk harf). Bulunamazsa None."""
    if version in _MODULES:
        return _MODULES[version]
    try:
        binary = php_binary(version)
    except InstallError:
        return None
    try:
        proc = subprocess.run([binary, "-m"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
        mods = {l.strip().lower() for l in proc.stdout.decode("utf-8", "replace").splitlines()
                if l.strip() and not l.startswith("[")}
    except Exception:
        return None
    _MODULES[version] = mods
    return mods


def missing_extensions(app, version):
    need = [e.lower() for e in ((app.get("requires") or {}).get("extensions") or [])]
    mods = php_modules(version)
    if mods is None:
        return []
    aliases = {"xml": ("xml", "libxml", "simplexml"), "pdo_mysql": ("pdo_mysql",), "mysqli": ("mysqli",)}
    return [e for e in need if not any(a in mods for a in aliases.get(e, (e,)))]


def php_in_range(app, version):
    req = app.get("requires") or {}
    lo, hi = req.get("php") or "0.0", req.get("php_max") or "99.9"
    return _ver(lo) <= _ver(version) <= _ver(hi)


def ext_hint(version, missing):
    v = version.replace(".", "")
    return "CyberPanel > PHP > Install Extensions bolumunden lsphp%s icin kurun: %s" % (
        v, ", ".join("lsphp%s-%s" % (v, m) for m in missing))


def site_php_version(domain):
    """Mevcut sitenin OpenLiteSpeed'de calistigi PHP surumu (ornek '8.2')."""
    vhosts = os.environ.get("AGFO_STORE_VHOST_DIR", "/usr/local/lsws/conf/vhosts")
    for conf in ("%s/%s/vhost.conf" % (vhosts, domain),):
        try:
            with open(conf, "r", encoding="utf-8", errors="replace") as fh:
                m = re.search(r"lsphp(\d)(\d+)", fh.read())
            if m:
                return "%s.%s" % (m.group(1), m.group(2))
        except OSError:
            continue
    return None


def safe_join(base, rel):
    rel = (rel or "").strip().lstrip("/")
    if rel and not SAFE_REL.match(rel):
        raise InstallError("Gecersiz yol: %s" % rel)
    target = os.path.normpath(os.path.join(base, rel))
    if not (target == base or target.startswith(base + os.sep)):
        raise InstallError("Yol kok dizinin disina cikiyor: %s" % rel)
    return target


def substitute(value, variables):
    """{degisken} yer tutucularini doldurur. Kabuk yorumu yoktur."""
    if isinstance(value, list):
        return [substitute(v, variables) for v in value]
    if isinstance(value, dict):
        return dict((k, substitute(v, variables)) for k, v in value.items())
    if not isinstance(value, str):
        return value
    def repl(match):
        key = match.group(1)
        if key not in variables:
            raise InstallError("Tarifte bilinmeyen degisken: {%s}" % key)
        return str(variables[key])
    return re.sub(r"\{([a-z_][a-z0-9_]*)\}", repl, value)


# ---------------------------------------------------------------------------
# CyberPanel koprusu
# ---------------------------------------------------------------------------

SECRET_FLAGS = ("--dbPassword", "--password", "--adminPass", "--dbpass", "--database-pass",
                "--admin-pass", "--admin_password", "--adminpass", "--pass")
SECRET_RE = re.compile(r"(--(?:dbPassword|password|adminPass|dbpass|database-pass|admin-pass|"
                       r"admin_password|adminpass|pass|admin-password)[= ])(\S+)", re.I)


def mask_argv(argv):
    """Gunluge yazilacak komut satirinda sifreleri gizler."""
    out, hide = [], False
    for item in argv:
        if hide:
            out.append("••••••"); hide = False; continue
        if item in SECRET_FLAGS:
            out.append(item); hide = True; continue
        out.append(SECRET_RE.sub(lambda m: m.group(1) + "••••••", item))
    return out


def redact(text, secrets_=()):
    """Metinden bilinen sifreleri ve sifre bayraklarini temizler."""
    text = SECRET_RE.sub(lambda m: m.group(1) + "••••••", text or "")
    for value in secrets_:
        if value and len(str(value)) >= 6:
            text = text.replace(str(value), "••••••")
    return text


class CyberPanel(object):
    def __init__(self, logger):
        self.log = logger

    def cli(self):
        configured = store.CFG.get("cyberpanel", "cli", default="") or ""
        if configured and os.access(configured, os.X_OK):
            return configured
        for candidate in ("/usr/local/CyberCP/bin/cyberpanel", "/usr/bin/cyberpanel",
                          "/usr/local/bin/cyberpanel"):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        found = shutil.which("cyberpanel")
        if not found:
            raise InstallError("CyberPanel komut satiri (cyberpanel) bulunamadi.")
        return found

    def run(self, args, timeout=600):
        argv = [self.cli()] + list(args)
        self.log("$ " + " ".join(mask_argv(argv)))
        try:
            proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise InstallError("CyberPanel komutu zaman asimina ugradi")
        out = proc.stdout.decode("utf-8", "replace").strip()
        for line in out.split("\n")[-40:]:
            if line.strip():
                self.log("  " + line.strip())
        return proc.returncode, out

    @staticmethod
    def parse_result(output):
        """CyberPanel CLI her durumda 0 dondurur; sonuc JSON govdesindedir.

        Ciktinin son JSON satiri {"success": 1, "errorMessage": "None"} bicimindedir.
        Bazi komutlar (createDatabase, issueSSL, deleteWebsite) BASARISIZLIKTA da
        success=1 basar; bu yuzden hata olcutu errorMessage alanidir.
        """
        payload = None
        for line in reversed((output or "").split("\n")):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    payload = json.loads(line)
                    break
                except ValueError:
                    continue
        if payload is None:
            return None, "CyberPanel ciktisi cozumlenemedi"
        message = str(payload.get("errorMessage", "None"))
        ok = bool(payload.get("success")) and message.strip().lower() in ("none", "", "null")
        return ok, (None if ok else message)

    def run_checked(self, args, what, timeout=600):
        rc, out = self.run(args, timeout=timeout)
        ok, message = self.parse_result(out)
        if ok is None:
            # Komut JSON basmadiysa (bilinmeyen islev adi veya eksik bayrak)
            raise InstallError("%s: CyberPanel beklenen yaniti vermedi. Cikti: %s"
                               % (what, (out or "(bos)")[-200:]))
        if not ok:
            raise InstallError("%s: %s" % (what, message))
        return out

    def website_exists(self, domain):
        return os.path.isdir(HOME_BASE + "/%s" % domain)

    def create_website(self, domain, email, php, package=None, owner=None):
        if self.website_exists(domain):
            self.log("site zaten var: %s" % domain)
            return False
        package = package or store.CFG.get("cyberpanel", "default_package", default="Default")
        owner = owner or store.CFG.get("cyberpanel", "default_owner", default="admin")
        self.run_checked(["createWebsite", "--package", package, "--owner", owner,
                          "--domainName", domain, "--email", email, "--php", php],
                         "Site olusturulamadi", timeout=900)
        if not self.website_exists(domain):
            raise InstallError("Site dizini olusmadi: %s" % domain)
        return True

    def create_database(self, domain, db_name, db_user, db_pass):
        self.run_checked(["createDatabase", "--databaseWebsite", domain,
                          "--dbName", db_name, "--dbUsername", db_user,
                          "--dbPassword", db_pass], "Veritabani olusturulamadi")
        return True

    def change_php(self, domain, php):
        self.run_checked(["changePHP", "--domainName", domain, "--php", php],
                         "PHP surumu degistirilemedi", timeout=300)
        return True

    def delete_database(self, db_name):
        self.run_checked(["deleteDatabase", "--dbName", db_name],
                         "Veritabani silinemedi", timeout=300)
        return True

    def delete_website(self, domain):
        self.run_checked(["deleteWebsite", "--domainName", domain],
                         "Site silinemedi", timeout=900)
        return True

    def issue_ssl(self, domain):
        """SSL sonucu SSL_RESULT= satirindadir; basarisizlik kurulumu durdurmaz."""
        rc, out = self.run(["issueSSL", "--domainName", domain], timeout=420)
        for line in reversed((out or "").split("\n")):
            if line.strip().startswith("SSL_RESULT="):
                try:
                    data = json.loads(line.strip()[len("SSL_RESULT="):])
                except ValueError:
                    break
                if data.get("outcome") == "issued" or data.get("SSL") == 1:
                    self.log("SSL cikarildi")
                    return True
                self.log("UYARI: SSL cikarilamadi (%s). Site HTTP uzerinden calisir."
                         % (data.get("error_message") or data.get("warning") or "sebep bilinmiyor"))
                return False
        ok, message = self.parse_result(out)
        if ok:
            return True
        self.log("UYARI: SSL cikarilamadi (%s)." % (message or "sebep bilinmiyor"))
        return False

    def site_user(self, domain):
        """Sitenin Linux kullanicisi (CyberPanel'in urettigi externalApp).

        Alan adindan TAHMIN EDILEMEZ: CyberPanel 'examp4821' gibi bir ad uretir.
        Dizinin sahibinden okumak en guvenilir yoldur.
        """
        import pwd
        home = HOME_BASE + "/%s" % domain
        try:
            return pwd.getpwuid(os.stat(home).st_uid).pw_name
        except Exception:
            return None


# ---------------------------------------------------------------------------
# indirme ve arsiv acma
# ---------------------------------------------------------------------------

def download(url, target, logger, timeout=None):
    if not url.startswith("https://"):
        raise InstallError("Yalnizca https adresleri indirilebilir")
    if not store.CFG.get("network", "allow_downloads", default=True):
        raise InstallError("Indirme kapali (network.allow_downloads=false)")
    timeout = timeout or int(store.CFG.get("limits", "download_timeout", default=900) or 900)
    logger("indiriliyor: %s" % url)
    # Bazi indirme sunuculari (Cloudflare arkasindakiler) Python istemcisini
    # 403 ile reddeder. Sunucudaki curl daha genis kabul gorur; once onu dene.
    curl = shutil.which("curl")
    if curl:
        proc = subprocess.run(
            [curl, "-fsSL", "--proto", "=https", "--proto-redir", "=https",
             "--max-redirs", "10", "--max-time", str(timeout), "--retry", "2",
             "--max-filesize", str(2 * 1024 * 1024 * 1024), "-o", target, url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout + 60)
        if proc.returncode == 0 and os.path.getsize(target) > 0:
            logger("indirildi: %.1f MB" % (os.path.getsize(target) / 1048576.0))
            return
        logger("  curl basarisiz (%s); yedek istemci deneniyor"
               % (proc.stderr.decode("utf-8", "replace").strip()[-160:] or proc.returncode))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AGFO-App-Store/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(target, "wb") as out:
            total = 0
            while True:
                chunk = resp.read(262144)
                if not chunk:
                    break
                out.write(chunk)
                total += len(chunk)
                if total > 2 * 1024 * 1024 * 1024:
                    raise InstallError("Arsiv cok buyuk (2 GB sinirini asti)")
    except InstallError:
        raise
    except Exception as exc:
        raise InstallError("Indirme basarisiz: %s" % exc)
    logger("indirildi: %.1f MB" % (os.path.getsize(target) / 1048576.0))


GITHUB_API = os.environ.get("AGFO_STORE_GITHUB_API", "https://api.github.com")


def _http_json(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "AGFO-App-Store", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


_RESOLVE_CACHE = {}
RESOLVE_TTL = 3600


def _curl_text(url, timeout=30, head=False):
    """Bir sayfayi (ya da yalnizca basliklari) curl ile getirir."""
    curl = shutil.which("curl")
    if not curl:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 AGFO-App-Store/1.1"},
                                     method="HEAD" if head else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.geturl() if head else resp.read(4 * 1024 * 1024).decode("utf-8", "replace")
    argv = [curl, "-sSL", "--proto", "=https", "--proto-redir", "=https", "--max-time", str(timeout),
            "-A", "Mozilla/5.0 AGFO-App-Store/1.1"]
    if head:
        argv += ["-o", os.devnull, "-w", "%{url_effective}", "-I"]
    proc = subprocess.run(argv + [url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout + 15)
    if proc.returncode != 0:
        raise InstallError("Sayfa alinamadi (%s): %s" % (url, proc.stderr.decode("utf-8", "replace").strip()[-160:]))
    return proc.stdout.decode("utf-8", "replace")


def _github_latest(repo, pattern, logger):
    """(indirme_adresi, surum) -- once API, olmazsa surum sayfasindan."""
    token = (store.CFG.get("network", "github_token", default="") or "").strip()
    try:
        headers = {"User-Agent": "AGFO-App-Store", "Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request("%s/repos/%s/releases/latest" % (GITHUB_API, repo), headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for asset in data.get("assets") or []:
            if pattern.search(asset.get("name", "")):
                return asset["browser_download_url"], data.get("tag_name", "")
        raise InstallError("%s son surumunde (%s) uygun paket yok; aranan: %s"
                           % (repo, data.get("tag_name", "?"), pattern.pattern))
    except InstallError:
        raise
    except Exception as exc:
        api_error = str(exc)
    # API sinirina (saatte 60 istek) takildiysak surum sayfasindan bul.
    try:
        final = _curl_text("https://github.com/%s/releases/latest" % repo, head=True)
        m = re.search(r"/releases/tag/([^/?#]+)", final or "")
        if not m:
            raise InstallError("son surum etiketi bulunamadi")
        tag = m.group(1)
        html = _curl_text("https://github.com/%s/releases/expanded_assets/%s" % (repo, tag))
        for href in re.findall(r'href="(/%s/releases/download/[^"]+)"' % re.escape(repo), html):
            name = urllib.parse.unquote(href.rsplit("/", 1)[-1])
            if pattern.search(name):
                return "https://github.com" + href, urllib.parse.unquote(tag)
        raise InstallError("%s %s surumunde uygun paket yok; aranan: %s" % (repo, tag, pattern.pattern))
    except InstallError as exc:
        raise InstallError("GitHub surum bilgisi alinamadi (%s): API: %s; sayfa: %s" % (repo, api_error[:120], exc))


def resolve_download(spec, logger, use_cache=True):
    """Tarifteki indirme tanimini somut bir adrese cevirir.

    {"url": ...}                          sabit ya da resmi 'son surum' adresi
    {"github": "sahip/depo", "asset": re} GitHub'daki son kararli surumun desene
                                          uyan dosyasi (surum yazilmaz, eskimez)
    {"page": "https://...", "regex": re}  resmi indirme sayfasindan regex ile
    """
    out = dict(spec)
    key = json.dumps({k: spec.get(k) for k in ("url", "github", "asset", "page", "regex")}, sort_keys=True)
    hit = _RESOLVE_CACHE.get(key)
    if use_cache and hit and time.time() - hit[0] < RESOLVE_TTL:
        out.update(hit[1])
        if out.get("version"):
            logger("son surum: %s (%s) [onbellek]" % (out["version"],
                   urllib.parse.unquote(out["url"].rsplit("/", 1)[-1])))
        return out

    found = {}
    repo = spec.get("github")
    if repo:
        if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo):
            raise InstallError("Gecersiz GitHub deposu: %s" % repo)
        url, tag = _github_latest(repo, re.compile(spec.get("asset") or r"\.zip$"), logger)
        found = {"url": url, "version": tag}
        logger("son surum: %s (%s)" % (tag, urllib.parse.unquote(url.rsplit("/", 1)[-1])))
    elif spec.get("page"):
        page = spec["page"]
        if not page.startswith("https://"):
            raise InstallError("Indirme sayfasi https olmali")
        html = _curl_text(page)
        m = re.search(spec.get("regex") or r"https://\S+\.zip", html)
        if not m:
            raise InstallError("Indirme sayfasinda paket adresi bulunamadi (%s)" % page)
        import html as _html
        link = _html.unescape(m.group(1) if m.groups() else m.group(0))
        link = urllib.parse.urljoin(page, link)
        if not link.startswith("https://"):
            raise InstallError("Sayfadaki adres https degil: %s" % link[:120])
        found = {"url": link}
        logger("indirme sayfasindan bulundu: %s" % urllib.parse.unquote(link.rsplit("/", 1)[-1]))
    if found:
        _RESOLVE_CACHE[key] = (time.time(), found)
        out.update(found)
    if not out.get("url"):
        raise InstallError("Indirme adresi belirlenemedi")
    return out


def check_archive(path, fmt):
    """Inen dosya gercekten arsiv mi? (Bazi sunucular 200 ile HTML doner.)"""
    if fmt == "file":
        with open(path, "rb") as fh:
            head = fh.read(64)
        if not head.lstrip().startswith(b"<?php"):
            raise InstallError("Indirilen dosya bir PHP dosyasi degil (baslangic: %s)"
                               % head[:40].decode("utf-8", "replace"))
        return
    try:
        if fmt == "zip":
            ok = zipfile.is_zipfile(path)
        else:
            ok = tarfile.is_tarfile(path)
    except OSError:
        ok = False
    if not ok:
        with open(path, "rb") as fh:
            head = fh.read(120).decode("utf-8", "replace").strip().replace("\n", " ")
        raise InstallError("Indirilen dosya gecerli bir %s arsivi degil (baslangic: %s)" % (fmt, head[:80]))


def archive_target(dest, name):
    """Arsivdeki bir uyenin hedef yolu; site kokunun disina cikamaz.

    Tarif yollarindaki dar karakter kurali (SAFE_REL) burada KULLANILMAZ:
    gercek paketlerde bosluklu, Unicode ya da parantezli dosya adlari olur
    (ornek: EspoCRM vendor testleri). Guvenlik yapisal denetimle saglanir.
    """
    if not name or "\x00" in name or "\\" in name:
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or ".." in parts or name.startswith("/"):
        return None
    target = os.path.normpath(os.path.join(dest, *parts))
    if not target.startswith(dest.rstrip("/") + os.sep):
        return None
    return target


def _safe_members_tar(archive, strip):
    for member in archive.getmembers():
        name = member.name
        if name.startswith("/") or ".." in name.split("/"):
            continue
        if member.issym() or member.islnk():
            continue
        parts = name.split("/")
        if strip:
            if len(parts) <= strip:
                continue
            name = "/".join(parts[strip:])
        if not name:
            continue
        member.name = name
        yield member


def extract(archive_path, fmt, dest, strip, logger, only="", strip_name=""):
    """only: arsivin (strip sonrasi) yalnizca bu alt klasorunu belge kokune koy.
    Ornek: Dolibarr kaynak arsivinde uygulama 'htdocs/' altindadir."""
    if only:
        import tempfile
        staging = tempfile.mkdtemp(prefix="agfo-x-", dir=store.WORK_DIR)
        try:
            extract(archive_path, fmt, staging, strip, logger)
            src = os.path.join(staging, only.strip("/"))
            if not os.path.isdir(src):
                raise InstallError("Arsivde beklenen klasor yok: %s" % only)
            for name in os.listdir(src):
                shutil.move(os.path.join(src, name), os.path.join(dest, name))
            logger("yalnizca '%s' klasoru kuruldu" % only)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return
    if fmt == "file":
        target = archive_target(dest, (strip_name or "index.php"))
        if target is None:
            raise InstallError("Gecersiz hedef dosya adi")
        shutil.copyfile(archive_path, target)
        logger("dosya yerlestirildi: %s" % os.path.basename(target))
        return
    logger("arsiv aciliyor (%s)" % fmt)
    if fmt in ("tar.gz", "tgz", "tar.bz2"):
        mode = "r:bz2" if fmt == "tar.bz2" else "r:gz"
        with tarfile.open(archive_path, mode) as archive:
            members = _safe_members_tar(archive, strip)
            if hasattr(tarfile, "data_filter"):
                archive.extractall(dest, members=members, filter="data")
            else:
                archive.extractall(dest, members=members)
    elif fmt == "zip":
        skipped = 0
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                name = info.filename
                if name.startswith("/") or ".." in name.split("/"):
                    continue
                parts = name.split("/")
                if strip:
                    if len(parts) <= strip:
                        continue
                    name = "/".join(parts[strip:])
                if not name:
                    continue
                target = archive_target(dest, name)
                if target is None:
                    skipped += 1
                    continue
                if info.is_dir() or name.endswith("/"):
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with archive.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        if skipped:
            logger("UYARI: guvenli olmayan %d arsiv girdisi atlandi" % skipped)
    else:
        raise InstallError("Desteklenmeyen arsiv bicimi: %s" % fmt)


def _ids(user, group):
    import grp, pwd
    try:
        return pwd.getpwnam(user).pw_uid, grp.getgrnam(group).gr_gid
    except KeyError:
        return None, None


def chown_tree(path, user, group, logger):
    uid, gid = _ids(user, group)
    if uid is None:
        logger("UYARI: %s:%s bulunamadi, sahiplik degistirilmedi" % (user, group))
        return
    for root, dirs, files in os.walk(path):
        for item in dirs + files:
            try:
                os.chown(os.path.join(root, item), uid, gid, follow_symlinks=False)
            except OSError:
                pass
    try:
        os.chown(path, uid, gid)
    except OSError:
        pass


def demote_spec(user, home):
    """Komutu site kullanicisi olarak calistirmak icin preexec ve ortam.

    Internetten inen kurulum betikleri (wp-cli, occ, install.php) root olarak
    calismamali. Ayrica Nextcloud occ gibi araclar dosya sahibinden baska
    kullaniciyla calistirilmayi reddeder.
    """
    import pwd
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        raise InstallError("Site kullanicisi bulunamadi: %s" % user)
    if entry.pw_uid == 0:
        raise InstallError("Site kullanicisi root olamaz")
    uid, gid = entry.pw_uid, entry.pw_gid

    def preexec():
        os.setsid()
        os.initgroups(user, gid)
        os.setgid(gid)
        os.setuid(uid)

    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": home, "USER": user, "LOGNAME": user,
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
    }
    return preexec, env, uid, gid


def fix_permissions(site_home, docroot, site_user, logger):
    """CyberPanel'in 'Fix Permissions' islemiyle ayni sirayi uygular.

    Dizinler 0755, dosyalar 0644, sahip site kullanicisi; en sonda belge koku
    <kullanici>:nogroup ve 0750 yapilir -- OpenLiteSpeed bu duzeni bekler.
    Hicbir sey herkese yazilabilir birakilmaz; lsphp zaten site kullanicisi
    olarak calistigi icin buna gerek yoktur.
    """
    group = "nogroup"
    import grp
    try:
        grp.getgrnam(group)
    except KeyError:
        group = "nobody"

    uid, _ = _ids(site_user, site_user)
    if uid is None:
        logger("UYARI: site kullanicisi (%s) bulunamadi; izinler degistirilmedi" % site_user)
        return

    for root, dirs, files in os.walk(docroot):
        for name in dirs:
            try:
                os.chmod(os.path.join(root, name), 0o755)
            except OSError:
                pass
        for name in files:
            try:
                os.chmod(os.path.join(root, name), 0o644)
            except OSError:
                pass
    chown_tree(docroot, site_user, site_user, logger)
    try:
        os.chown(site_home, uid, uid)
    except OSError:
        pass
    gid = _ids(site_user, group)[1]
    if gid is not None:
        try:
            os.chown(docroot, uid, gid)
            os.chmod(docroot, 0o750)
        except OSError:
            pass
    logger("izinler ayarlandi (dizin 0755 / dosya 0644, sahip %s)" % site_user)


# ---------------------------------------------------------------------------
# is (job) yurutucusu
# ---------------------------------------------------------------------------

class Job(object):
    def __init__(self, app, params):
        self.id = secrets.token_hex(8)
        self.app = app
        self.params = params
        self.lines = []
        self.lock = threading.Lock()
        self.log_path = os.path.join(store.WORK_DIR, "%s.log" % self.id)
        # Tarifte acikca verilen dosya izinleri: CyberPanel'in izin duzeltmesi
        # her dosyayi 0644 yapar; sifre iceren config dosyalari icin bunlari
        # sonradan geri koyuyoruz.
        self.explicit_modes = []
        # Tarifin site kokunun disinda actigi veri dizinleri (kaldirmada lazim).
        self.data_dirs = []
        self.record = None
        self.max_lines = int(store.CFG.get("limits", "job_log_lines", default=4000) or 4000)

    def log(self, message):
        stamp = time.strftime("%H:%M:%S")
        line = "[%s] %s" % (stamp, message)
        with self.lock:
            self.lines.append(line)
            if len(self.lines) > self.max_lines:
                del self.lines[: len(self.lines) - self.max_lines]
            try:
                if not os.path.isdir(store.WORK_DIR):
                    os.makedirs(store.WORK_DIR, 0o700)
                with open(self.log_path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except Exception:
                pass

    def tail(self, offset=0):
        with self.lock:
            return self.lines[offset:], len(self.lines)


JOBS = {}


def get_runtime_job(job_id):
    return JOBS.get(job_id)


def validate_params(app, params):
    """Kullanici girdilerini dogrular ve temiz bir sozluk dondurur."""
    domain = (params.get("domain") or "").strip().lower().rstrip(".")
    if not DOMAIN_RE.match(domain):
        raise InstallError("Gecersiz alan adi: %s" % domain)
    email = (params.get("email") or "").strip()
    if not EMAIL_RE.match(email):
        raise InstallError("Gecersiz e-posta adresi")
    php = (params.get("php") or store.CFG.get("cyberpanel", "default_php", default="8.2")).strip()
    if not re.match(r"^\d\.\d$", php):
        raise InstallError("Gecersiz PHP surumu")
    path = (params.get("path") or "/").strip() or "/"
    if path != "/" and not re.match(r"^/[A-Za-z0-9._-]{1,40}$", path):
        raise InstallError("Gecersiz alt dizin")

    clean = {"domain": domain, "email": email, "php": php, "path": path,
             "title": (params.get("title") or app["name"])[:120]}

    for field in app.get("fields", []):
        fid = field["id"]
        value = (params.get(fid) or field.get("default") or "").strip()
        if field.get("type") == "password" and not value:
            value = random_password()
        if field.get("required", True) and not value:
            raise InstallError("%s alani gerekli" % field.get("label", fid))
        if field.get("type") == "email" and value and not EMAIL_RE.match(value):
            raise InstallError("%s gecerli bir e-posta olmali" % field.get("label", fid))
        if field.get("type") == "text" and value and not re.match(r"^[^\r\n]{1,120}$", value):
            raise InstallError("%s gecersiz" % field.get("label", fid))
        if field.get("pattern") and value and not re.match(field["pattern"], value):
            raise InstallError("%s gecersiz: %s" % (field.get("label", fid),
                               field.get("pattern_hint") or "izin verilmeyen karakter"))
        clean[fid] = value
    return clean


def build_variables(app, clean, cp_info):
    variables = dict(clean)
    variables.update(cp_info)
    variables.setdefault("admin_pass", clean.get("admin_pass") or random_password())
    variables["app_id"] = app["id"]
    variables["app_name"] = app["name"]
    variables["php_bin"] = php_binary(clean["php"])
    variables["site_home"] = HOME_BASE + "/%s" % clean["domain"]
    variables["now"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # Tariflerin config dosyalarina yazacagi rastgele anahtarlar (yalnizca harf/rakam).
    variables["path_slash"] = clean["path"].rstrip("/") + "/"     # "/" ya da "/alt/"
    variables["secret"] = random_password(32)
    variables["secret64"] = random_password(64)
    return variables


def execute_steps(app, variables, job):
    docroot = variables["docroot"]
    for index, raw in enumerate(app.get("steps", []), 1):
        step = substitute(raw, variables)
        kind = next(iter(step.keys()))
        job.log("adim %d/%d: %s" % (index, len(app.get("steps", [])), kind))

        if kind == "mkdir":
            spec = step["mkdir"]
            if isinstance(spec, dict) and spec.get("base") == "home":
                # Moodle/Nextcloud gibi uygulamalar veri dizinini site kokunun
                # DISINA ister; yalnizca /home/<alanadi> altina izin veriyoruz.
                home = variables["site_home"]
                target = os.path.normpath(spec["path"])
                if not (target == home or target.startswith(home + os.sep)):
                    raise InstallError("Veri dizini site dizininin disinda: %s" % target)
                existed = os.path.exists(target)
                os.makedirs(target, mode=int(spec.get("mode", "0755"), 8), exist_ok=True)
                if target != home and target not in job.data_dirs:
                    # Yalnizca BU isin actigi dizin geri alinir.
                    if not existed and getattr(job, "rollback", None) is not None:
                        job.rollback.setdefault("data_dirs", []).append(target)
                        if getattr(job, "persist_rollback", None):
                            job.persist_rollback()
                    job.data_dirs.append(target)
                _, _, uid, gid = demote_spec(variables["site_user"], home)
                os.chown(target, uid, gid)
                job.log("  dizin: %s (sahip %s)" % (target, variables["site_user"]))
                continue
            target = safe_join(docroot, spec if isinstance(spec, str) else spec.get("path"))
            mode = int((spec.get("mode") if isinstance(spec, dict) else None) or "0755", 8)
            os.makedirs(target, mode=mode, exist_ok=True)

        elif kind == "write":
            spec = step["write"]
            target = safe_join(docroot, spec["path"])
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(spec.get("content", ""))
            mode = int(spec.get("mode", "0644"), 8)
            os.chmod(target, mode)
            if mode != 0o644:
                job.explicit_modes.append((target, mode))
            job.log("  yazildi: %s" % spec["path"])

        elif kind == "delete":
            spec = step["delete"]
            target = safe_join(docroot, spec if isinstance(spec, str) else spec.get("path"))
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            elif os.path.exists(target):
                os.unlink(target)
            job.log("  silindi: %s" % (spec if isinstance(spec, str) else spec.get("path")))

        elif kind == "run":
            spec = step["run"]
            argv = spec["argv"] if isinstance(spec, dict) else spec
            if not isinstance(argv, list) or not argv:
                raise InstallError("Gecersiz 'run' adimi")
            cwd = safe_join(docroot, (spec.get("cwd") if isinstance(spec, dict) else "") or "")
            timeout = int((spec.get("timeout") if isinstance(spec, dict) else 0) or 900)
            as_root = isinstance(spec, dict) and bool(spec.get("as_root"))
            kwargs = {}
            if not as_root:
                preexec, env, _, _ = demote_spec(variables["site_user"], variables["site_home"])
                # Onceki adimlarin root olarak yazdigi dosyalar komutun
                # erisebilecegi hale gelsin.
                chown_tree(docroot, variables["site_user"], variables["site_user"], lambda m: None)
                kwargs = {"preexec_fn": preexec, "env": env}
            job.log("  $ " + " ".join(mask_argv(argv[:6])) + (" …" if len(argv) > 6 else "")
                    + ("  [root]" if as_root else "  [%s]" % variables["site_user"]))
            try:
                proc = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                      stderr=subprocess.STDOUT, timeout=timeout, check=False,
                                      **kwargs)
            except FileNotFoundError:
                raise InstallError("Komut bulunamadi: %s" % argv[0])
            except subprocess.TimeoutExpired:
                raise InstallError("Komut zaman asimina ugradi: %s" % argv[0])
            out = proc.stdout.decode("utf-8", "replace").strip()
            for line in out.split("\n")[-30:]:
                if line.strip():
                    job.log("    " + line.strip()[:300])
            if proc.returncode != 0 and not (isinstance(spec, dict) and spec.get("ignore_errors")):
                raise InstallError("Komut basarisiz (%d): %s" % (proc.returncode, argv[0]))

        elif kind == "copy":
            spec = step["copy"]
            src = safe_join(docroot, spec["from"])
            dst = safe_join(docroot, spec["to"])
            if spec.get("if_missing", True) and os.path.exists(dst):
                job.log("  zaten var: %s" % spec["to"])
            elif not os.path.isfile(src):
                if not spec.get("optional"):
                    raise InstallError("Kopyalanacak dosya yok: %s" % spec["from"])
            else:
                shutil.copyfile(src, dst)
                job.log("  kopyalandi: %s -> %s" % (spec["from"], spec["to"]))

        elif kind == "env":
            spec = step["env"]
            target = safe_join(docroot, spec.get("file") or ".env")
            values = spec.get("set") or {}
            text = ""
            if os.path.isfile(target):
                with open(target, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            for key, value in values.items():
                if not re.match(r"^[A-Z][A-Z0-9_]{0,60}$", key):
                    raise InstallError("Gecersiz .env anahtari: %s" % key)
                value = str(value).replace("\n", "").replace("\r", "")
                if re.search(r"[\s#\"'$]", value):
                    value = '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')
                line = "%s=%s" % (key, value)
                pattern = re.compile(r"^%s=.*$" % re.escape(key), re.M)
                text = pattern.sub(lambda m: line, text) if pattern.search(text) else (text.rstrip("\n") + "\n" + line + "\n")
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.chmod(target, 0o640)
            job.explicit_modes.append((target, 0o640))
            job.log("  .env guncellendi: %s" % ", ".join(sorted(values.keys())))

        elif kind == "chown":
            fix_permissions(variables["site_home"], docroot, variables["site_user"], job.log)

        else:
            raise InstallError("Bilinmeyen adim turu: %s" % kind)


def run_job(job):
    app = job.app
    params = job.params
    cp = CyberPanel(job.log)
    created_site = False
    domain = None
    rb = {}            # geri alma defteri: bu isin olusturdugu kaynaklar
    job.rollback = rb

    def persist():
        # Defter her degisiklikte is kaydina yazilir: servis kurulumun ortasinda
        # durursa, yeniden baslarken bu defterle geri alma yapilabilsin.
        store.update_job(job.id, rollback={k: v for k, v in rb.items() if k != "archive"})
    job.persist_rollback = persist
    try:
        store.update_job(job.id, status="running", started=int(time.time()))
        # Parametreler start_install icinde dogrulandi; burada yeniden
        # dogrulamiyoruz ki uretilen sifreler degismesin.
        clean = params
        domain = clean["domain"]
        job.log("kurulum basliyor: %s -> %s%s" % (app["name"], domain, clean["path"]))

        # 0) once indir: adres bozuksa site ve veritabani hic acilmasin.
        if not os.path.isdir(store.WORK_DIR):
            os.makedirs(store.WORK_DIR, 0o700)
        download_spec = resolve_download(app["download"], job.log)
        archive = os.path.join(store.WORK_DIR, "%s-%s" % (job.id, os.path.basename(
            urllib.parse.urlparse(download_spec["url"]).path) or "archive"))
        rb["archive"] = archive
        download(download_spec["url"], archive, job.log)
        check_archive(archive, download_spec.get("format", "tar.gz"))

        # 1) site
        created_site = cp.create_website(domain, clean["email"], clean["php"])
        rb["site"] = created_site
        persist()
        if clean.get("change_site_php") and not created_site:
            cp.change_php(domain, clean["change_site_php"])
            rb["php_before"] = clean.get("php_before")
            persist()
            job.log("site PHP %s -> %s yapildi" % (clean.get("php_before"), clean["change_site_php"]))
        docroot_base = HOME_BASE + "/%s/public_html" % domain
        docroot = docroot_base if clean["path"] == "/" else os.path.join(docroot_base, clean["path"].lstrip("/"))
        if not os.path.isdir(docroot_base):
            raise InstallError("Site dizini olusmadi: %s" % docroot_base)
        if not os.path.isdir(docroot):
            rb["docroot_dir"] = docroot          # biz actik; hatada tamamen silinir
            persist()
        os.makedirs(docroot, exist_ok=True)
        if os.listdir(docroot) and not params.get("overwrite"):
            leftovers = [n for n in os.listdir(docroot) if n not in ("index.html", ".well-known")]
            if leftovers:
                raise InstallError("Hedef dizin bos degil: %s" % docroot)
        for name in list(os.listdir(docroot)):
            if name == "index.html":
                os.unlink(os.path.join(docroot, name))
        if not params.get("overwrite"):
            rb["docroot_clean"] = docroot        # bos idi; hatada icerigi bosaltilir
            persist()

        # Site kullanicisi CyberPanel tarafindan uretilir (ornek: examp4821);
        # alan adindan tahmin edilemez, dizin sahibinden okunur.
        site_user = cp.site_user(domain)
        if not site_user or site_user == "root":
            raise InstallError("Sitenin sistem kullanicisi belirlenemedi (%s/%s)" % (HOME_BASE, domain))
        job.log("site kullanicisi: %s" % site_user)
        cp_info = {"docroot": docroot, "site_user": site_user,
                   "url": "https://%s%s" % (domain, "" if clean["path"] == "/" else clean["path"]),
                   # 'localhost' MySQL'de soket demektir; CyberPanel yetkileri
                   # 127.0.0.1 ve makine IP'si icin verir, bu yuzden TCP kullaniyoruz.
                   "db_host": "127.0.0.1", "db_name": "", "db_user": "", "db_pass": ""}

        # 2) veritabani
        if app.get("database", True):
            suffix = secrets.token_hex(3)
            base = re.sub(r"[^a-z0-9]", "", app["id"])[:8] or "app"
            cp_info["db_name"] = ("%s_%s" % (base, suffix))[:32]
            cp_info["db_user"] = ("%s_%s" % (base, suffix))[:32]
            cp_info["db_pass"] = random_password(24)
            if not (NAME_RE.match(cp_info["db_name"]) and NAME_RE.match(cp_info["db_user"])):
                raise InstallError("Veritabani adi uretilemedi")
            rb["db"] = cp_info["db_name"]
            persist()
            cp.create_database(domain, cp_info["db_name"], cp_info["db_user"], cp_info["db_pass"])
            job.log("veritabani olusturuldu: %s" % cp_info["db_name"])

        variables = build_variables(app, clean, cp_info)

        # 3) dosyalar
        extract(archive, download_spec.get("format", "tar.gz"), docroot,
                int(download_spec.get("strip", 0)), job.log, download_spec.get("only", ""),
                download_spec.get("target", ""))
        try:
            os.unlink(archive)
        except OSError:
            pass

        # 4) tarif adimlari
        execute_steps(app, variables, job)

        # 4b) public/ isteyen uygulamalar: istekleri public/ klasorune yonlendir,
        # geri kalan her sey (.env, vendor, storage) disaridan erisilemez olur.
        if (app.get("web_root") or "").strip("/"):
            write_public_redirect(docroot, clean["path"], job.log, app["web_root"].strip("/"))
        if app.get("deny"):
            write_deny_rules(docroot, app["deny"], job.log)

        # 5) sahiplik ve SSL
        fix_permissions(variables["site_home"], docroot_base, variables["site_user"], job.log)
        for target, mode in job.explicit_modes:
            try:
                os.chmod(target, mode)
            except OSError:
                pass
        if job.explicit_modes:
            job.log("tarifte belirtilen dosya izinleri geri konuldu (%d dosya)"
                    % len(job.explicit_modes))
        if store.CFG.get("cyberpanel", "issue_ssl", default=True) and created_site:
            cp.issue_ssl(domain)

        finish = app.get("finish", {}) or {}
        result = {
            "url": variables["url"] + (finish.get("path", "") or ""),
            "admin_user": variables.get("admin_user", ""),
            "admin_pass": variables.get("admin_pass", ""),
            "db_name": cp_info["db_name"], "db_user": cp_info["db_user"],
            "db_pass": cp_info["db_pass"],
            "note": finish.get("note", ""),
            "install_mode": app.get("install_mode", "web"),
        }
        store.add_install({
            "app": app["id"], "app_name": app["name"], "domain": domain,
            "path": clean["path"], "url": result["url"], "docroot": docroot,
            "installed": int(time.time()), "db_name": cp_info["db_name"],
            "db_user": cp_info["db_user"], "php": clean["php"],
            # Kaldirmada "siteyi de sil" yalnizca siteyi bu panel actiysa sunulur.
            "created_site": bool(created_site), "site_user": variables["site_user"],
            "data_dirs": list(job.data_dirs),
        })
        rb.clear()
        store.update_job(job.id, status="done", finished=int(time.time()), result=result, rollback={})
        try:
            store.CFG.set(("cyberpanel", "last_email"), clean.get("email", ""))
        except Exception:
            pass
        store.audit("install", {"app": app["id"], "domain": domain, "path": clean["path"]})
        job.log("KURULUM TAMAM: %s" % result["url"])

    except InstallError as exc:
        job.log("HATA: %s" % exc)
        rollback(cp, rb, job, domain)
        store.update_job(job.id, status="error", finished=int(time.time()), error=str(exc), rollback={})
        store.audit("install_failed", {"app": app.get("id"), "domain": domain, "error": str(exc)})
    except Exception as exc:  # beklenmeyen
        job.log("BEKLENMEYEN HATA: %s" % exc)
        rollback(cp, rb, job, domain)
        store.update_job(job.id, status="error", finished=int(time.time()), error=str(exc), rollback={})
    finally:
        archive_path = rb.get("archive") if rb else None
        if archive_path and os.path.exists(archive_path):
            try:
                os.unlink(archive_path)
            except OSError:
                pass
        with _run_lock:
            RUNNING["count"] = max(0, RUNNING["count"] - 1)


PUBLIC_HTACCESS = """# AGFO App Store: bu uygulama {folder}/ klasorunden sunulur.
# Diger klasorler (.env, vendor, config, data ...) bu kural sayesinde disaridan erisilemez.
RewriteEngine On
RewriteBase {base}
RewriteRule ^{folder}/ - [L]
RewriteRule ^(.*)$ {folder}/$1 [L]
"""


def write_public_redirect(docroot, path, logger, folder="public"):
    if not re.match(r"^[A-Za-z0-9_-]{1,40}$", folder):
        raise InstallError("Gecersiz web koku klasoru: %s" % folder)
    if not os.path.isdir(os.path.join(docroot, folder)):
        raise InstallError("Uygulama %s/ klasoru bekliyordu ama pakette yok" % folder)
    target = os.path.join(docroot, ".htaccess")
    if os.path.exists(target):
        shutil.move(target, target + ".orig")
        logger("paketin kok .htaccess dosyasi .htaccess.orig olarak saklandi")
    base = "/" if path == "/" else path.rstrip("/") + "/"
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(PUBLIC_HTACCESS.format(base=base, folder=folder))
    logger("web koku %s/ (yonlendirme ve gizli dosya korumasi yazildi)" % folder)


DENY_MARK = "# AGFO App Store: korunan klasorler"


def write_deny_rules(docroot, dirs, logger):
    """Hassas klasorleri disariya kapatir.

    OpenLiteSpeed .htaccess icindeki Deny/Require satirlarini UYGULAMAZ, yalnizca
    rewrite kurallarini isler. Uygulamalarin kendi 'Deny from all' korumalari bu
    yuzden calismaz; ayni korumayi rewrite [F] kuraliyla veriyoruz.
    """
    clean = [d.strip("/") for d in dirs
             if re.match(r"^[A-Za-z0-9_.-]{1,60}(/[A-Za-z0-9_.-]{1,60})*\*?/?$", d.strip())
             and ".." not in d.split("/")]
    if not clean:
        return
    target = os.path.join(docroot, ".htaccess")
    old = ""
    if os.path.isfile(target):
        with open(target, "r", encoding="utf-8", errors="replace") as fh:
            old = fh.read()
    if DENY_MARK in old:
        return
    # Sondaki * onek demektir: files/config_* -> files/config_<herhangi>
    pattern = "|".join(re.escape(d[:-1]) + "[^/]*" if d.endswith("*") else re.escape(d) for d in clean)
    block = "%s\nRewriteEngine On\nRewriteRule ^(%s)(/|$) - [F,L]\n# --\n\n" % (DENY_MARK, pattern)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(block + old)
    logger("disariya kapatilan klasorler: %s" % ", ".join(clean))


def rollback(cp, rb, job, domain):
    """Basarisiz kurulumun olusturdugu her seyi geri alir.

    Yalnizca BU isin olusturdugu kaynaklara dokunur: onceden var olan site,
    onceden dolu dizin ya da baska kurulumun veritabani asla silinmez.
    Geri almadaki bir hata asil hatayi gizlemez; gunluge yazilir.
    """
    if not rb or not any(rb.get(k) for k in ("site", "db", "docroot_dir", "docroot_clean", "data_dirs", "php_before")):
        return
    job.log("geri aliniyor: bu kurulumun olusturdugu kaynaklar siliniyor")
    if rb.get("php_before") and not rb.get("site"):
        try:
            cp.change_php(domain, rb["php_before"])
            job.log("  site PHP %s'e geri alindi" % rb["php_before"])
        except InstallError as exc:
            job.log("  UYARI: site PHP surumu geri alinamadi (%s): %s" % (rb["php_before"], exc))
    if rb.get("site"):
        # Site bu is tarafindan acildiysa dosyalari ve veritabanlari onunla gider.
        try:
            if rb.get("db"):
                cp.delete_database(rb["db"])
                job.log("  veritabani silindi: %s" % rb["db"])
        except InstallError as exc:
            job.log("  UYARI: veritabani silinemedi (%s): %s" % (rb["db"], exc))
        try:
            cp.delete_website(domain)
            job.log("  site silindi: %s" % domain)
        except InstallError as exc:
            job.log("  UYARI: site silinemedi (%s): %s. CyberPanel'den silin." % (domain, exc))
        return
    if rb.get("db"):
        try:
            cp.delete_database(rb["db"])
            job.log("  veritabani silindi: %s" % rb["db"])
        except InstallError as exc:
            job.log("  UYARI: veritabani silinemedi (%s): %s. CyberPanel > Databases'ten silin."
                    % (rb["db"], exc))
    for path in rb.get("data_dirs") or []:
        shutil.rmtree(path, ignore_errors=True)
        job.log("  veri dizini silindi: %s" % path)
    if rb.get("docroot_dir"):
        shutil.rmtree(rb["docroot_dir"], ignore_errors=True)
        job.log("  dizin silindi: %s" % rb["docroot_dir"])
    elif rb.get("docroot_clean") and os.path.isdir(rb["docroot_clean"]):
        target = rb["docroot_clean"]
        for name in os.listdir(target):
            if name in KEEP_IN_DOCROOT:
                continue
            item = os.path.join(target, name)
            if os.path.isdir(item) and not os.path.islink(item):
                shutil.rmtree(item, ignore_errors=True)
            else:
                try:
                    os.unlink(item)
                except OSError:
                    pass
        job.log("  yazilan dosyalar temizlendi: %s" % target)


class _FileLogger(object):
    """Calisan bir Job nesnesi olmadan, isin gunluk dosyasina yazar."""
    def __init__(self, job_id):
        self.path = os.path.join(store.WORK_DIR, "%s.log" % job_id)

    def log(self, message):
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), message))
        except OSError:
            pass


def recover_interrupted(records, logger=None):
    """Servis yeniden baslarken yarim kalan kurulumlarin olusturduklarini geri alir."""
    done = 0
    for rec in records:
        rb = rec.get("rollback") or {}
        if rec.get("kind") not in (None, "install") or not rb or not rec.get("domain"):
            continue
        sink = _FileLogger(rec["id"])
        sink.log("SERVIS YENIDEN BASLADI: yarim kalan kurulum geri aliniyor")
        try:
            rollback(CyberPanel(sink.log), rb, sink, rec["domain"])
            store.update_job(rec["id"], rollback={},
                             error="Servis yeniden basladigi icin is yarida kaldi; olusturulanlar geri alindi.")
            done += 1
        except Exception as exc:
            sink.log("geri alma basarisiz: %s" % exc)
        if logger:
            logger("yarim kurulum geri alindi: %s %s%s" % (rec.get("app"), rec.get("domain"), rec.get("path", "")))
    return done


def start_install(app_id, params):
    app = catalog.get(app_id)
    if not app:
        raise InstallError("Uygulama bulunamadi: %s" % app_id)
    # Girdiler ise baslamadan ONCE dogrulanir: hatali istek aninda ve anlasilir
    # bir mesajla reddedilir, bos yere "kurulum basladi" denmez.
    clean = validate_params(app, params)
    clean["overwrite"] = bool(params.get("overwrite"))
    if app.get("root_only") and clean["path"] != "/":
        raise InstallError("%s alt dizine kurulamaz; kendi alan adinin ya da alt alan adinin "
                           "kokune kurun (Alt dizin: /)." % app["name"])
    req = app.get("requires") or {}
    need, top = str(req.get("php") or ""), str(req.get("php_max") or "")
    rng = ("PHP %s-%s" % (need, top)) if top else ("PHP %s veya ustu" % need)
    clean["change_site_php"] = ""
    if os.path.isdir(HOME_BASE + "/%s" % clean["domain"]):
        # Mevcut site: uygulama sitenin KENDI PHP surumuyle calisir.
        current = site_php_version(clean["domain"])
        fits = lambda v: php_in_range(app, v) and not missing_extensions(app, v)
        if current and not fits(current):
            target = str(params.get("change_site_php") or "").strip()
            if target and re.match(r"^\d\.\d$", target) and fits(target):
                php_binary(target)
                clean["change_site_php"] = target
                clean["php_before"] = current
                clean["php"] = target
            else:
                why = ("PHP %s'te eksik eklenti: %s" % (current, ", ".join(missing_extensions(app, current)))
                       if php_in_range(app, current) else "su an PHP %s kullaniyor" % current)
                raise InstallError(
                    "%s %s ister; %s %s. Kurulum penceresinde 'sitenin PHP surumunu degistir' "
                    "secenegini isaretleyin, eklentiyi kurun ya da uygulamayi yeni bir alt alan "
                    "adina kurun." % (app["name"], rng, clean["domain"], why))
        elif current:
            clean["php"] = current
    elif not php_in_range(app, clean["php"]):
        if need and _ver(clean["php"]) < _ver(need):
            clean["php"] = need          # yeni site: gereken surumle acilir
        elif top and _ver(clean["php"]) > _ver(top):
            clean["php"] = top
    php_binary(clean["php"])             # o surum sunucuda var mi? yoksa simdi reddet
    missing = missing_extensions(app, clean["php"])
    if missing:
        raise InstallError("%s icin PHP %s'te eksik eklenti: %s. %s" % (
            app["name"], clean["php"], ", ".join(missing), ext_hint(clean["php"], missing)))
    limit = int(store.CFG.get("limits", "max_concurrent_jobs", default=2) or 2)
    with _run_lock:
        if RUNNING["count"] >= limit:
            raise InstallError("Ayni anda en fazla %d kurulum calisabilir." % limit)
        RUNNING["count"] += 1
    job = Job(app, clean)
    JOBS[job.id] = job
    store.add_job({"id": job.id, "app": app["id"], "app_name": app["name"],
                   "domain": clean["domain"], "path": clean["path"],
                   "status": "queued", "created": int(time.time())})
    thread = threading.Thread(target=run_job, args=(job,), name="install-%s" % job.id, daemon=True)
    thread.start()
    return job.id


# ---------------------------------------------------------------------------
# kaldirma
# ---------------------------------------------------------------------------

TRASH_DIR = os.environ.get("AGFO_STORE_TRASH_DIR", os.path.join(store.ROOT_DIR, "trash"))
MYSQL_PASSWORD_FILE = os.environ.get("AGFO_STORE_MYSQL_PASSWORD_FILE", "/etc/cyberpanel/mysqlPassword")
KEEP_IN_DOCROOT = (".well-known",)


def _mysql_defaults_file():
    """CyberPanel'in root MySQL sifresiyle gecici bir --defaults-extra-file yazar.

    Sifre komut satirina konmaz (ps ciktisinda gorunmesin). Dosya yoksa None
    doner; MariaDB'de root genelde unix_socket ile sifresiz de baglanir.
    """
    try:
        with open(MYSQL_PASSWORD_FILE, "r", encoding="utf-8") as fh:
            password = fh.read().strip()
    except OSError:
        return None
    if not password:
        return None
    import tempfile
    fd, path = tempfile.mkstemp(prefix="agfo-my-", suffix=".cnf")
    with os.fdopen(fd, "w") as fh:
        fh.write("[client]\nuser=root\npassword=%s\n" % password.replace("\n", ""))
    os.chmod(path, 0o600)
    return path


def _mysql_argv(tool, defaults):
    argv = [shutil.which(tool) or tool]
    if defaults:
        argv.append("--defaults-extra-file=%s" % defaults)
    return argv


def dump_database(db_name, target, logger):
    if not NAME_RE.match(db_name or ""):
        raise InstallError("Gecersiz veritabani adi: %s" % db_name)
    defaults = _mysql_defaults_file()
    try:
        argv = _mysql_argv("mysqldump", defaults) + [
            "--single-transaction", "--quick", "--routines", "--triggers", db_name]
        with open(target, "wb") as out:
            proc = subprocess.run(argv, stdout=out, stderr=subprocess.PIPE, timeout=3600)
        if proc.returncode != 0:
            raise InstallError("Veritabani yedegi alinamadi: %s"
                               % proc.stderr.decode("utf-8", "replace").strip()[-300:])
    except FileNotFoundError:
        raise InstallError("mysqldump bulunamadi; yedek alinamadi")
    finally:
        if defaults:
            os.unlink(defaults)
    os.chmod(target, 0o600)
    logger("veritabani yedegi: %s (%.1f MB)" % (target, os.path.getsize(target) / 1048576.0))


def database_exists(db_name):
    """Silme gercekten oldu mu? Belirlenemezse None."""
    defaults = _mysql_defaults_file()
    try:
        argv = _mysql_argv("mysql", defaults) + [
            "-N", "-B", "-e", "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='%s'" % db_name]
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if proc.returncode != 0:
            return None
        return proc.stdout.decode("utf-8", "replace").strip() == db_name
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        if defaults:
            os.unlink(defaults)


def find_install(domain, path):
    for item in store.load_installs():
        if item.get("domain") == domain and (item.get("path") or "/") == path:
            return item
    return None


def resolve_install_docroot(record):
    """Kayittaki belge kokunu dogrular; kayit elle bozulmus olsa bile site
    dizini disinda hicbir seyin silinmemesini garanti eder."""
    domain = record.get("domain") or ""
    if not DOMAIN_RE.match(domain):
        raise InstallError("Kayitta gecersiz alan adi: %s" % domain)
    base = os.path.realpath(HOME_BASE + "/%s/public_html" % domain)
    path = record.get("path") or "/"
    expected = base if path == "/" else os.path.normpath(os.path.join(base, path.lstrip("/")))
    if not (expected == base or expected.startswith(base + os.sep)):
        raise InstallError("Kayitta gecersiz alt dizin: %s" % path)
    if os.path.islink(expected):
        raise InstallError("Belge koku bir sembolik baglanti; guvenlik icin durduruldu: %s" % expected)
    recorded = record.get("docroot")
    if recorded and os.path.normpath(recorded) != expected and os.path.realpath(recorded) != expected:
        raise InstallError("Kayittaki dizin beklenenle uyusmuyor: %s" % recorded)
    return base, expected


def _domain_busy(domain):
    for job in JOBS.values():
        rec = store.get_job(job.id) or {}
        if rec.get("kind") == "health":
            continue        # saglik testi kendisi kurulum/kaldirma baslatir; onu engellememeli
        if rec.get("domain") == domain and rec.get("status") in ("queued", "running"):
            return True
    return False


def run_uninstall(job):
    p = job.params
    domain, path = p["domain"], p["path"]
    cp = CyberPanel(job.log)
    record = job.record
    stamp = time.strftime("%Y%m%d-%H%M%S")
    trash = os.path.join(TRASH_DIR, "%s%s-%s-%s" % (
        domain, "" if path == "/" else path.replace("/", "_"), record.get("app", "app"), stamp))
    warnings = []
    try:
        store.update_job(job.id, status="running", started=int(time.time()))
        job.log("kaldirma basliyor: %s -> %s%s" % (record.get("app_name") or record.get("app"), domain, path))
        base, docroot = resolve_install_docroot(record)
        job.log("belge koku: %s" % docroot)

        # 1) yedek: hicbir sey silinmeden once alinir; alinamazsa durulur.
        if p["backup"]:
            os.makedirs(trash, 0o700, exist_ok=True)
            os.chmod(TRASH_DIR, 0o700)
            job.log("yedek dizini: %s" % trash)
            if p["drop_db"] and record.get("db_name"):
                dump_database(record["db_name"], os.path.join(trash, "%s.sql" % record["db_name"]), job.log)
            with open(os.path.join(trash, "kayit.json"), "w", encoding="utf-8") as fh:
                json.dump(record, fh, indent=2, ensure_ascii=False)

        # 2) dosyalar
        protected = set()
        if docroot == base:
            # Ayni sitede alt dizine kurulmus baska uygulamalar varsa onlara dokunma.
            for other in store.load_installs():
                opath = (other.get("path") or "/").strip("/")
                if other.get("domain") == domain and opath:
                    protected.add(opath.split("/")[0])
            if protected:
                job.log("korunan alt dizin kurulumlari: %s" % ", ".join(sorted(protected)))
        if os.path.isdir(docroot):
            names = [n for n in os.listdir(docroot)
                     if not (docroot == base and (n in KEEP_IN_DOCROOT or n in protected))]
            moved = 0
            if p["backup"]:
                files_dir = os.path.join(trash, "files")
                os.makedirs(files_dir, 0o700, exist_ok=True)
                for name in names:
                    shutil.move(os.path.join(docroot, name), os.path.join(files_dir, name))
                    moved += 1
                job.log("%d oge yedege tasindi" % moved)
            else:
                for name in names:
                    target = os.path.join(docroot, name)
                    if os.path.isdir(target) and not os.path.islink(target):
                        shutil.rmtree(target)
                    else:
                        os.unlink(target)
                    moved += 1
                job.log("%d oge silindi" % moved)
            if docroot != base:
                os.rmdir(docroot)
                job.log("alt dizin kaldirildi: %s" % path)
        else:
            job.log("UYARI: belge koku zaten yok: %s" % docroot)

        # Uygulamanin site kokunun disindaki veri dizinleri (Nextcloud/Moodle)
        for extra in record.get("data_dirs") or []:
            extra = os.path.normpath(extra)
            home = os.path.realpath(HOME_BASE + "/%s" % domain)
            inside = extra.startswith(home + os.sep)
            holds_docroot = extra == base or base.startswith(extra + os.sep)
            if inside and not holds_docroot and os.path.isdir(extra) and not os.path.islink(extra):
                if p["backup"]:
                    shutil.move(extra, os.path.join(trash, "data-" + os.path.basename(extra)))
                else:
                    shutil.rmtree(extra)
                job.log("veri dizini kaldirildi: %s" % extra)

        # 3) veritabani
        if p["drop_db"] and record.get("db_name"):
            db = record["db_name"]
            try:
                cp.delete_database(db)
                exists = database_exists(db)
                if exists:
                    raise InstallError("CyberPanel basarili dedi ama veritabani hala duruyor")
                job.log("veritabani silindi: %s%s" % (db, "" if exists is False else " (dogrulanamadi)"))
            except InstallError as exc:
                msg = "veritabani silinemedi (%s): %s. CyberPanel > Databases > Delete Database ile silin." % (db, exc)
                job.log("UYARI: " + msg)
                warnings.append(msg)
        elif record.get("db_name"):
            job.log("veritabani birakildi: %s" % record["db_name"])

        # 4) site
        if p["delete_site"]:
            cp.delete_website(domain)
            job.log("CyberPanel sitesi silindi: %s" % domain)
        elif os.path.isdir(base):
            # Bos belge kokunu OpenLiteSpeed'in bekledigi sahiplikte birak.
            user = record.get("site_user") or cp.site_user(domain)
            if user:
                fix_permissions(HOME_BASE + "/%s" % domain, base, user, job.log)

        store.remove_install(domain, path)
        result = {"kind": "uninstall", "domain": domain, "path": path,
                  "backup": trash if p["backup"] else "", "warnings": warnings,
                  "site_deleted": bool(p["delete_site"])}
        store.update_job(job.id, status="done", finished=int(time.time()), result=result)
        store.audit("uninstall", {"app": record.get("app"), "domain": domain, "path": path,
                                  "drop_db": p["drop_db"], "delete_site": p["delete_site"],
                                  "backup": result["backup"], "warnings": len(warnings)})
        job.log("KALDIRMA TAMAM%s" % (" (%d uyari)" % len(warnings) if warnings else ""))
    except InstallError as exc:
        job.log("HATA: %s" % exc)
        store.update_job(job.id, status="error", finished=int(time.time()), error=str(exc))
        store.audit("uninstall_failed", {"domain": domain, "path": path, "error": str(exc)})
    except Exception as exc:
        job.log("BEKLENMEYEN HATA: %s" % exc)
        store.update_job(job.id, status="error", finished=int(time.time()), error=str(exc))
    finally:
        with _run_lock:
            RUNNING["count"] = max(0, RUNNING["count"] - 1)


def start_uninstall(params):
    domain = (params.get("domain") or "").strip().lower()
    path = (params.get("path") or "/").strip() or "/"
    record = find_install(domain, path)
    if not record:
        raise InstallError("Bu adreste kayitli kurulum yok: %s%s" % (domain, path))
    if (params.get("confirm") or "").strip().lower() != domain:
        raise InstallError("Onay icin alan adini aynen yazin: %s" % domain)
    clean = {
        "domain": domain, "path": path,
        "drop_db": bool(params.get("drop_db", True)) and bool(record.get("db_name")),
        "backup": bool(params.get("backup", True)),
        "delete_site": bool(params.get("delete_site")),
    }
    if clean["delete_site"]:
        if not record.get("created_site"):
            raise InstallError("Bu site App Store'dan once de vardi; site silme yalnizca "
                               "App Store'un actigi sitelerde yapilabilir.")
        others = [i for i in store.load_installs()
                  if i.get("domain") == domain and (i.get("path") or "/") != path]
        if others:
            raise InstallError("Bu sitede baska kurulumlar da var; once onlari kaldirin.")
        if path != "/":
            raise InstallError("Site silme yalnizca kok dizindeki kurulumlarda yapilabilir.")
    resolve_install_docroot(record)  # gecersiz kayit aninda reddedilsin
    if _domain_busy(domain):
        raise InstallError("Bu alan adinda suren bir is var; bitmesini bekleyin.")
    limit = int(store.CFG.get("limits", "max_concurrent_jobs", default=2) or 2)
    with _run_lock:
        if RUNNING["count"] >= limit:
            raise InstallError("Ayni anda en fazla %d is calisabilir." % limit)
        RUNNING["count"] += 1
    name = record.get("app_name") or record.get("app") or "Uygulama"
    job = Job({"id": record.get("app", "app"), "name": name}, clean)
    job.record = record
    JOBS[job.id] = job
    store.add_job({"id": job.id, "kind": "uninstall", "app": record.get("app"),
                   "app_name": name, "domain": domain, "path": path,
                   "status": "queued", "created": int(time.time())})
    thread = threading.Thread(target=run_uninstall, args=(job,), name="uninstall-%s" % job.id, daemon=True)
    thread.start()
    return job.id


# ---------------------------------------------------------------------------
# katalog dogrulama
# ---------------------------------------------------------------------------

def probe_url(url, timeout=20):
    """Adres gercekten indirilebilir mi? Kurulumla ayni yolu (curl) kullanir."""
    curl = shutil.which("curl")
    if curl:
        proc = subprocess.run(
            [curl, "-sSL", "--proto", "=https", "--proto-redir", "=https", "-r", "0-1023",
             "-o", os.devnull, "-w", "%{http_code}", "--max-time", str(timeout), url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout + 15)
        code = proc.stdout.decode("ascii", "replace").strip()
        status = int(code) if code.isdigit() else 0
        return 200 <= status < 300, status, proc.stderr.decode("utf-8", "replace").strip()[:200]
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 AGFO-App-Store/1.0",
                                               "Range": "bytes=0-1023"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300, resp.status, ""
    except urllib.error.HTTPError as exc:
        return False, exc.code, str(exc)
    except Exception as exc:
        return False, 0, str(exc)[:200]


def verify_catalog(timeout=20):
    """Her uygulamanin indirme adresini sunucudan yoklar (GitHub son surumu dahil)."""
    results = []
    for item in catalog.load():
        entry = {"id": item["id"], "name": item["name"], "url": item["download"].get("url", ""),
                 "ok": False, "status": 0, "size": 0, "error": "", "version": ""}
        try:
            spec = resolve_download(item["download"], lambda m: None)
            entry["url"] = spec["url"]
            entry["version"] = spec.get("version", "")
            entry["ok"], entry["status"], entry["error"] = probe_url(spec["url"], timeout)
        except InstallError as exc:
            entry["error"] = str(exc)[:200]
        except Exception as exc:
            entry["error"] = str(exc)[:200]
        results.append(entry)
    store.audit("catalog_verify", {"ok": sum(1 for r in results if r["ok"]),
                                   "total": len(results)})
    return results
