# AGFO CyberPanel Araçları — Proje Spesifikasyonu

**Sürüm:** 1.0 · **Tarih:** 29.10.2026 · **Depo:** `downtownck/agfo-cyberpanel`
**Sahibi:** Cemal Gürkan Kara (AGFO)

Bu belge, Hetzner ve Netcup'taki iki CyberPanel sunucusu için geliştirilen tüm
AGFO araçlarının uyması gereken ortak kuralları tanımlar. Yeni bir araç
yazılırken ya da mevcut bir araç revize edilirken bu belge esas alınır.
"ZORUNLU" işaretli maddeler sağlanmadan sürüm paketlenmez.

---

## 1. Kapsam ve hedef sunucular

| | **Hetzner** | **Netcup** |
|---|---|---|
| Ana alan adı | agfo.app | agfocert.net |
| Panel | CyberPanel + OpenLiteSpeed/LiteSpeed | CyberPanel + OpenLiteSpeed |
| DNS | — | Kendi DNS'i (ns1/ns2.agfocert.net) |
| Ön güvenlik duvarı | **Hetzner Cloud Firewall** — panel portları Hetzner Console'dan elle açılır | Sunucu içi firewalld/ufw |
| Sistem Python'u | 3.11'in altında | (kurulumda tespit edilir) |
| Notlar | PHP 8.4 korunmalı; birçok uygulama ona bağlı | AGFO SafeGuard bu sunucuya kurulmaz |

> Boş hücreler kurulum sırasında `common/agfo_common.py` tarafından tespit
> edilip `/var/lib/agfo/server.json` dosyasına yazılır (bkz. §4).

### Sunucuya özel kurallar

Geliştirmeye başlarken hedef sunucu belirlenir: **Hetzner**, **Netcup** veya
**İkisi de**. Ortak kod iki sunucuda aynıdır; seçim yalnızca şunları değiştirir:

- **Hetzner:** Cloud Firewall kurulumla açılamaz; yeni dış port için kurulum
  çıktısında "Hetzner Console → Firewall → Inbound: TCP <port>" uyarısı,
  kaldırmada silme hatırlatması. Python 3.8 uyumu zorunlu. PHP 8.4 ve lsphp
  sürümlerine dokunulmaz; site vhost'ları değiştirilmez.
- **Netcup:** portlar firewalld/ufw ile açılır, `via` manifeste yazılır.
  agfocert.net DNS'ine açık onay olmadan dokunulmaz. SafeGuard'a bağımlılık
  yok. PHP `disable_functions` geniş olabilir; PHP bileşenleri `mail`,
  `shell_exec`, `system` vb.'ye dayanmaz.
- **İkisi de:** iki listenin kısıtları birlikte. Kurulum sunucuyu kendisi
  tespit eder (`/var/lib/agfo/server.json`), tespit edilemezse
  `AGFO_SERVER=hetzner|netcup`. Tek ZIP; önerilen kurulum sırası Netcup → Hetzner.

> Depo herkese açıktır: belgelere ve koda IP adresi, jeton, şifre veya API
> anahtarı yazılmaz.

Kapsam: bu depodaki **tüm** araçlar ve bundan sonra eklenecek her araç.
Kapsam dışı: WordPress eklentileri (ayrı standartları var), CyberPanel'in
kendi kodu (yalnızca menü şablonlarına işaretli blok eklenir).

### 1.1 Mevcut araçlar ve port kaydı

| Slug | Sürüm | Port | Tema (bugün) |
|---|---|---|---|
| agfo-ssh-terminal | 1.3.2 | 8822 | koyu |
| agfo-firewall-ai | 1.1.2 | 8823 | koyu |
| agfo-app-store | 1.2.0 | 8824 | koyu |
| *(boş)* | — | 8825 | — |
| agfo-file-manager | 1.0.1 | 8826 (+ iç 18096) | açık (TFM) |
| agfo-ssh-menu | 1.5.1 | — | — |

**Port kuralı:** yeni araç, bu tablodaki ilk boş portu alır (8825, sonra
8827…). İç (yalnızca 127.0.0.1) portlar 18000–18999 aralığından seçilir.
Port bu tabloya ve README'ye aynı commit'te yazılır.

---

## 2. Temel ilkeler (mevcut, korunur)

1. **Harici bağımlılık yok.** Yalnızca Python standart kütüphanesi;
   en düşük hedef **Python 3.8** (Hetzner'daki eski Python nedeniyle).
   PHP gerekiyorsa CyberPanel'in kurulu `lsphp`'si kullanılır.
2. **Package Runner ile kurulum.** Her ZIP'in kökünde `install.sh` bulunur;
   kurulum tty istemez, soru sormaz; tüm ayarlar `AGFO_<KISA>_*` ortam
   değişkenleriyle verilir.
3. **Runner çalışma dizini kuralı.** Kurulum, `/var/lib/agfo-package-runner/work/...`
   altından başka bir kullanıcı adına dosya çalıştırmaz; gerekenler önce
   `/opt/<slug>/` altına kopyalanır.
4. **Yükseltmede ayar korunur.** Aynı `install.sh` yeniden çalıştırıldığında
   şifre, IP kilidi, API anahtarları, jeton, oturumlar ve sertifikalar yerinde kalır.
5. **systemd servisi** olarak çalışma; varsayılan HTTPS; CyberPanel'in
   Let's Encrypt sertifikası bulunur, günlük `certwatch` zamanlayıcısı kurulur.
6. **Güvenlik tabanı:** PBKDF2-SHA256 şifre, IP başına kaba kuvvet kilidi,
   HttpOnly+SameSite çerez, CSRF başlığı, Origin denetimi, `allow_ips`,
   menüden şifresiz giriş jetonu (`auth.token_login`).
7. **İşlev kaybı yasak.** Bir revizyonda çalışan hiçbir özellik, uç nokta,
   buton veya ayar kaybolamaz; açıkça istenmedikçe kaldırılmaz. Paketlemeden
   önce bir önceki sürümle işlev envanteri karşılaştırılır.

---

## 3. Yeni zorunlu gereksinimler

### 3.1 Menü bağlantısı — ZORUNLU

Her araç, kurulduğu anda CyberPanel kenar menüsüne **kendi** girdisini ekler;
kaldırıldığında **yalnızca kendi** girdisini siler. Ayrı menü paketini
çalıştırmak gerekmez.

**Tasarım: menü kayıt defteri + senkron aracı**

```
/var/lib/agfo/menu.d/<slug>.json    # her aracın kendi girdisi
```

```json
{
  "slug": "agfo-backup-center",
  "label": "AGFO Backup Center",
  "url_from": "/opt/agfo-backup-center/config/config.json",
  "token_param": true,
  "target": "blank",
  "icon": "fa-database",
  "order": 50
}
```

- `install.sh` sonunda: dosyayı yazar → `agfo-menu sync` çalıştırır.
- `uninstall.sh` başında: dosyayı siler → `agfo-menu sync` çalıştırır.
- `agfo-menu sync`, CyberPanel şablonuna her araç için işaretli bir blok yazar:

  ```html
  <!-- agfo-menu:agfo-backup-center:start -->
  <li>…</li>
  <!-- agfo-menu:agfo-backup-center:end -->
  ```

  Kayıt defterinde olmayan işaretli blokları siler. Bu sayede kaldırma,
  başka araçların girdilerine ve CyberPanel'in kendi değişikliklerine
  dokunmadan yapılır (bugünkü "en yeni `.agfo-bak` yedeğini geri koy"
  yönteminin yerine geçer).
- Link adresi `public_url` + giriş jetonundan üretilir; IP ile yayınlanan
  panelde 8090 sertifikasındaki alan adı, yalnızca panelin sertifikası onu
  kapsıyorsa kullanılır (1.5.1 davranışı korunur).
- **CyberPanel güncellemesine dayanıklılık:** CyberPanel yükseltmesi
  şablonları ezerse girdiler kaybolur. `agfo-menu-sync.path` (şablon
  dosyasını izler) + günlük `agfo-menu-sync.timer` kayıt defterini yeniden uygular.
- Değişiklikten sonra `lscpd` gecikmeli ve `--no-block` yeniden başlatılır.
- Varsayılan: yeni sekme. Elle eklenmiş Package Runner girdisinin yalnızca
  sekmesi ayarlanır, adresine dokunulmaz.
- App Store'daki **CyberPanel menü editörü** aynı kayıt defterini okur/yazar;
  elle yapılan sıralama/etiket değişiklikleri `menu.d` dosyasına yansır.
- `agfo-menu` aracı ve zamanlayıcıları **referans sayımlı** paylaşılan
  bileşendir: ilk AGFO aracıyla kurulur, son AGFO aracı kaldırılınca kaldırılır.

**Kabul ölçütü:** temiz sunucuda `install.sh` → menüde girdi var ve
tıklayınca şifresiz açılıyor; `uninstall.sh` → girdi yok, diğer girdiler
ve CyberPanel'in kendi menüsü bayt bayt aynı.

### 3.2 Açık renk tema — ZORUNLU (yeni araçlar)

Yeni geliştirilen tüm araçlar açık renk temayla gelir ve CyberPanel'in açık
görünümüyle uyumlu durur. Tüm araçlar tek bir ortak stil dosyasını kullanır:
`common/ui/agfo-light.css`.

| Belirteç | Değer | Kullanım |
|---|---|---|
| `--bg` | `#f5f7fa` | Sayfa zemini |
| `--surface` | `#ffffff` | Kart, panel, tablo |
| `--surface-2` | `#eef2f7` | Başlık satırı, seçili satır |
| `--line` | `#d9e0ea` | Kenarlık |
| `--fg` | `#1f2933` | Ana metin |
| `--fg-dim` | `#52606d` | İkincil metin |
| `--accent` | `#1d4ed8` | Birincil buton, link |
| `--ok` | `#15803d` | Başarılı |
| `--warn` | `#b45309` | Uyarı |
| `--err` | `#b91c1c` | Hata |

Kurallar:

- Metin/zemin kontrastı **WCAG AA** (normal metin ≥ 4.5:1). Koyu zemin
  üzerinde koyu metin yasaktır.
- Font: sistem font yığını; kod ve log alanları `ui-monospace`.
- Kod düzenleyici (Ace vb.) açık tema ile açılır (ör. `github`, `textmate`).
- Tarayıcının koyu modu temayı ters çevirmez (`color-scheme: light`).
- Mevcut koyu temalı araçlar (Terminal, Firewall AI, App Store) bir sonraki
  **minor** revizyonlarında açık temaya geçirilir; geçişte hiçbir ekran
  işlevi kaybolmaz.

### 3.3 İzsiz kaldırma — ZORUNLU

Her kurulum, sunucuda bıraktığı **her izi** bir manifeste yazar; kaldırma
yalnızca bu manifeste göre çalışır. Tahminle `rm` yapılmaz.

```
/var/lib/agfo/installed/<slug>.json
```

```json
{
  "slug": "agfo-firewall-ai",
  "version": "1.2.0",
  "installed_at": "2026-10-29T12:00:00Z",
  "server": "netcup",
  "paths":      ["/opt/agfo-firewall-ai", "/var/log/agfo-firewall-ai"],
  "units":      ["agfo-firewall-ai.service", "agfo-firewall-ai-certwatch.service",
                 "agfo-firewall-ai-certwatch.timer"],
  "ports":      [{"port": 8823, "via": "firewalld"}],
  "files_added":   ["/etc/crowdsec/acquis.d/agfo-cyberpanel.yaml"],
  "files_patched": [{"path": "/etc/…", "marker": "agfo:agfo-firewall-ai"}],
  "packages":   [{"name": "crowdsec", "preexisting": false}],
  "cron":       [],
  "users":      [],
  "menu":       "/var/lib/agfo/menu.d/agfo-firewall-ai.json",
  "shared":     ["agfo-menu"]
}
```

İz kategorileri ve kaldırmadaki davranış:

| İz | Kaldırmada |
|---|---|
| `/opt/<slug>` ve log dizinleri | Silinir |
| systemd birimleri (servis, timer, path) | Durdurulur, devre dışı, dosya silinir, `daemon-reload` |
| Açılan portlar (firewalld / ufw / CSF) | Hangi araçla açıldıysa onunla kapatılır |
| Eklenen yapılandırma dosyaları | Silinir |
| Yamalanan dosyalar | Yalnızca işaretli blok çıkarılır |
| Kurulan apt/dnf paketleri | `preexisting: false` **ve** başka bir AGFO aracı kullanmıyorsa kaldırılır |
| Menü girdisi | `menu.d` silinir + `agfo-menu sync` |
| `.agfo-bak-*` yedekleri | Bu kurulumun oluşturdukları silinir |
| `__pycache__`, geçici `work/`, `trash/` | Silinir |
| Paylaşılan bileşenler (`agfo-menu`, `agfo-common`) | Referans sayısı 0 olursa silinir |
| `/var/lib/agfo/installed/<slug>.json` | En son silinir |

Kaldırma modları:

```bash
bash uninstall.sh                      # TAM kaldırma — iz bırakmaz
AGFO_KEEP_CONFIG=1 bash uninstall.sh   # ayarları /opt/<slug>/config'te bırak
```

- Kaldırmadan önce `config/` dizini `/root/agfo-uninstall-<slug>-<sürüm>-<zaman>.tar.gz`
  olarak **yalnızca** `AGFO_UNINSTALL_BACKUP=1` verilirse yedeklenir
  (varsayılan: yedek yok, çünkü yedek de bir izdir).
- Kaldırma idempotenttir: yarıda kalırsa tekrar çalıştırılabilir.
- Kaldırma sonunda **iz denetimi** çalışır (`agfo-trace-check <slug>`):
  manifestteki her öğenin gerçekten yok olduğunu doğrular, kalan varsa listeler
  ve sıfırdan farklı çıkış kodu döner.
- App Store'daki "Kaldır" düğmesi bu betiği çağırır; ayrı bir silme mantığı
  taşımaz.
- App Store'un kurduğu siteler/veritabanları CyberPanel'e aittir, App Store
  kaldırılınca silinmez (mevcut davranış korunur).
- Hetzner Cloud Firewall kuralları sunucunun dışındadır; kaldırma sonunda
  "Hetzner Console'dan şu inbound kuralı silin: TCP 8823" uyarısı basılır.

**Kabul ölçütü:** kurulum öncesi ve kaldırma sonrası alınan sistem
görüntüsü (`/opt`, `/etc/systemd/system`, `/etc/crowdsec`, firewall kuralları,
CyberPanel şablonları, `dpkg -l`) arasında fark yok.

### 3.4 Paket arşivi ve "en güncel ZIP" — ZORUNLU

Orijinal kurulum ZIP'leri **tek bir klasörde**, sürüm numarasıyla tutulur
ve en güncel olan otomatik bulunup indirilebilir.

**Adlandırma:** `agfo-<araç>-<MAJOR.MINOR.PATCH>.zip` — ek son ek yok.

**a) Depoda — kaynak arşiv**

```
packages/
  index.json
  agfo-app-store/
    agfo-app-store-1.2.0.zip
    agfo-app-store-1.1.2.zip
  agfo-firewall-ai/
    agfo-firewall-ai-1.1.2.zip
  …
```

`index.json`:

```json
{
  "generated_at": "2026-10-29T12:00:00Z",
  "tools": {
    "agfo-app-store": {
      "latest": "1.2.0",
      "versions": {
        "1.2.0": {"file": "agfo-app-store/agfo-app-store-1.2.0.zip",
                  "sha256": "…", "size": 147456, "date": "2026-10-28"}
      }
    }
  }
}
```

- `tools/make-packages.sh` ZIP'i `dist/` yerine `packages/<araç>/` altına
  yazar, `index.json`'ı günceller, SHA-256 hesaplar.
- Aynı sürüm numarasıyla farklı içerikli ZIP üretilirse betik **durur**
  (sürüm numarası yükseltilmeden yayın yok).
- "En güncel" = semver'e göre en yüksek sürüm (dosya tarihine göre değil).
- GitHub Release iş akışı aynı ZIP'leri sürüm etiketine de ekler (mevcut).

**b) Sunucuda — kurulu paket arşivi**

```
/var/lib/agfo/packages/<araç>/<araç>-<sürüm>.zip
/var/lib/agfo/packages/index.json
```

- Her `install.sh`, kendini kuran ZIP'in bir kopyasını buraya bırakır
  (Runner çalışma dizininden kendini yeniden paketler, SHA-256'yı kaydeder).
- Böylece her sunucuda o sunucuya **hangi sürümlerin** kurulduğu ve geri
  dönülebilecek ZIP'ler tek yerde durur.
- Bu arşiv **kasıtlı olarak** araç kaldırılınca silinmez; tamamen silmek için
  `AGFO_PURGE_ARCHIVE=1`. Son AGFO aracı da kaldırılmışsa ve bu bayrak
  verilmişse `/var/lib/agfo` tamamen silinir.

**c) İndirme**

- App Store'da **"Paketler"** sekmesi: araç başına en güncel sürüm, kurulu
  sürüm, depodaki sürüm, "İndir" ve "Bu sürüme dön" düğmeleri.
- Komut satırı: `agfo-pkg latest <araç>` (yolu basar), `agfo-pkg list`.
- Kurulu sürüm depodakinden eskiyse App Store'da "güncelleme var" rozeti.

---

## 4. Depo yapısı (hedef)

```
agfo-cyberpanel/
  SPEC.md                 # bu belge
  README.md               # araç tablosu, hızlı kurulum
  common/                 # paylaşılan kod — derlemede her ZIP'e kopyalanır
    agfo_common.py        # manifest, port, sertifika, firewall yardımcıları
    agfo-menu             # menü senkron aracı (§3.1)
    agfo-trace-check      # iz denetimi (§3.3)
    agfo-pkg              # paket arşivi aracı (§3.4)
    ui/agfo-light.css     # ortak açık tema (§3.2)
  agfo-<araç>/
    VERSION
    install.sh
    uninstall.sh
    README.md
    CHANGELOG.md
    app/  config/  systemd/
  packages/               # sürüm arşivi + index.json (§3.4)
  skills/                 # bu depoya ait Claude/ChatGPT skill'leri (§5.1)
    <skill-adı>/
      claude/SKILL.md
      chatgpt/SKILL.md (+ references/)
      <skill-adı>-chatgpt.zip
  tools/make-packages.sh
  .github/workflows/release.yml
```

Her ZIP kendi başına kurulabilir olmalıdır: `common/` içeriği derleme
sırasında ZIP'in içine kopyalanır, kurulum depoya erişim gerektirmez.

---

## 5. Sürümleme

- **SemVer:** `MAJOR.MINOR.PATCH`. Sürüm, `VERSION` dosyasında ve
  `install.sh` başındaki `APP_VERSION`'da aynıdır (derleme bunu denetler).
- PATCH: hata düzeltmesi. MINOR: yeni özellik, tema geçişi. MAJOR:
  yapılandırma biçimi değişikliği (geçiş betiği zorunlu).
- Her sürümde `CHANGELOG.md` girdisi + README araç tablosu güncellenir.

### 5.1 Depoyu güncel tutma — ZORUNLU

Depo tek dallıdır; her değişiklik **doğrudan `main`'e** gönderilir (pull
request akışı yok).

- Bir araç değişikliği **tek commit**tir ve şunları birlikte içerir: kod,
  `VERSION`, `install.sh` içindeki `APP_VERSION`, `CHANGELOG.md`, README araç
  tablosu, `packages/<araç>/` altındaki yeni ZIP ve `packages/index.json`.
  `SPEC.md` değiştiyse o da aynı commit'e girer.
- Commit mesajı mevcut düzende: `<Araç> <sürüm>: <kısa özet>`
  (birden çok araç: `Menu 1.5.1: …; Firewall AI 1.1.2, …`).
- Göndermeden önce `git fetch origin main` + `git rebase origin/main`.
- Sürüm içeren her gönderimden sonra tarih etiketi atılır:
  `vYYYY.MM.DD` (aynı gün ikincisi `vYYYY.MM.DD.2`); release iş akışı ZIP'leri
  GitHub Releases'e ekler.
- Bu depoya ait bir skill oluşturulur ya da değiştirilirse `skills/<ad>/`
  aynı şekilde güncellenip `Skill <ad>: <özet>` mesajıyla gönderilir.
- Gönderim yapılamıyorsa (erişim yok) bu açıkça söylenir ve dosyalar
  kullanıcıya teslim edilir; gönderilmiş gibi raporlanmaz.

---

## 6. Yeni araç ekleme kontrol listesi

- [ ] Slug `agfo-<ad>`, port tabloya işlendi
- [ ] `install.sh`: tty'siz, ortam değişkenli, idempotent, ayar koruyan
- [ ] Manifest her izi kaydediyor (§3.3)
- [ ] `menu.d` girdisi + `agfo-menu sync` (§3.1)
- [ ] `common/ui/agfo-light.css`, AA kontrast (§3.2)
- [ ] `uninstall.sh` manifeste göre siliyor; `agfo-trace-check` temiz
- [ ] Kurulum ZIP'in kopyasını `/var/lib/agfo/packages/` altına bırakıyor
- [ ] `make-packages.sh` ZIP'i `packages/` altına koydu, `index.json` güncel
- [ ] README + CHANGELOG + App Store kataloğu güncel
- [ ] Tek commit ile `main`'e gönderildi, tarih etiketi atıldı (§5.1)
- [ ] İki sunucuda da (Hetzner, Netcup) kurulum → kullanım → kaldırma denendi

---

## 7. Test ve kabul

Her sürüm için, mümkünse önce ayrı bir test VM'inde, sonra sırayla Netcup ve
Hetzner'da:

1. **Temiz kurulum** → servis ayakta, port açık, menü girdisi var, açık tema.
2. **Yeniden kurulum (yükseltme)** → ayarlar korunmuş, menü girdisi tek.
3. **Önceki sürüm işlev envanteri** → kaybolan uç nokta/buton yok.
4. **Tam kaldırma** → `agfo-trace-check` temiz, menü ve diğer araçlar sağlam.
5. **`AGFO_KEEP_CONFIG=1` ile kaldırma + yeniden kurulum** → ayarlar geri geliyor.
6. **CyberPanel şablonu ezilmesi** (şablon elle eski haline getirilir) →
   sync zamanlayıcısı girdileri geri koyuyor.
7. **Python 3.8 ile çalıştırma** (`python3.8 -m py_compile`).

---

## 8. Mevcut araçlardaki farklar (geçiş işleri)

Bugünkü kodda bu spesifikasyona uymayan noktalar:

| # | Bulgu | Etkilenen | Yapılacak |
|---|---|---|---|
| 1 | Menü girdisi kurulumla eklenmiyor; ayrı `agfo-ssh-menu` çalıştırılıyor | Tümü | §3.1'e geçiş; `agfo-ssh-menu` kayıt defterine uyarlanır |
| 2 | Menü geri alma "en yeni `.agfo-bak` yedeğini geri yükle" ile yapılıyor; diğer araçların girdilerini ve CyberPanel güncellemelerini geri alabilir | agfo-ssh-menu | İşaretli blok kaldırmaya geçilir |
| 3 | Kaldırma varsayılan olarak `config/` ve logları bırakıyor | Tümü | §3.3 varsayılanı: tam kaldırma |
| 4 | `ufw` kuralı yalnızca Terminal'de siliniyor; Firewall AI, App Store, File Manager sadece firewalld'yi kapatıyor | 3 araç | Manifestteki `via` alanına göre kapatma |
| 5 | Kaldırmada menü girdisi silinmiyor ("menü paketini yeniden çalıştırın" mesajı) | App Store, File Manager | §3.1 |
| 6 | `.agfo-bak-*` dosyaları CyberPanel dizininde birikiyor | agfo-ssh-menu | İşaretli blok sistemiyle yedeğe gerek kalmaz; eskiler temizlenir |
| 7 | Koyu tema (`--bg: #0b0f14`) | Terminal, Firewall AI, App Store | Sonraki minor sürümde açık tema |
| 8 | ZIP'ler `dist/`'e yazılıyor ve `.gitignore`'da; depoda sürüm arşivi yok | tools | §3.4 |
| 9 | Sunucuda hangi ZIP'in kurulduğu saklanmıyor | Tümü | §3.4-b |

Önerilen geçiş sırası: `common/` (manifest + agfo-menu + tema) →
agfo-ssh-menu 2.0.0 → App Store (Paketler sekmesi + menü editörünün kayıt
defterine bağlanması) → File Manager → Firewall AI → SSH Terminal.

---

## 9. Açık kararlar

1. **Kaldırma varsayılanı:** bu belge "tam kaldırma, ayar korumak için
   `AGFO_KEEP_CONFIG=1`" diyor. Bugünkü davranış tersidir.
2. **Terminal ekranı:** SSH Terminal'de terminalin içi de açık renk mi
   olsun, yoksa yalnızca çerçeve açık, terminal yüzeyi seçilebilir mi?
3. **Depoda ZIP saklama:** sürüm başına toplam ~4 MB (File Manager 3,5 MB).
   Tüm sürümler mi tutulsun, yoksa araç başına son N sürüm mü?
4. **Yeni araç portları:** 8825 boş; Backup Center gibi bir sonraki araca mı
   ayrılsın?

