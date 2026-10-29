---
name: agfo-cyberpanel-dev
description: Hetzner/Netcup CyberPanel sunucuları için AGFO aracı (downtownck/agfo-cyberpanel) yazarken veya revize ederken: menü girdisi, açık tema, izsiz kaldırma, sürümlü ZIP arşivi kuralları.
---

# AGFO CyberPanel Araçları — Geliştirme Standardı

Bu skill, `downtownck/agfo-cyberpanel` deposundaki her araç için geçerlidir: yeni araç yazmak, mevcut aracı revize etmek, paketlemek, kurulum/kaldırma betiği hazırlamak. Ayrıntılı gerekçeler `references/SPEC.md` dosyasındadır. GitHub bağlantısı varsa depodaki güncel `SPEC.md`'yi oku; çelişki varsa depodaki sürüm esas alınır, yoksa `references/SPEC.md` kullanılır.

"ZORUNLU" maddeler sağlanmadan sürüm paketlenmez.

## 0. Çalışmaya başlarken

**İlk adım: hedef sunucuyu sor.** Kullanıcı mesajında ya da sohbette hedef sunucu açıkça belli değilse, koda başlamadan önce kullanıcıya tek bir soru sor (seçenekli soru aracı varsa onu kullan, yoksa düz metinle sor):

> "Bu araç hangi sunucu için?" — seçenekler: **Hetzner (agfo.app)**, **Netcup (agfocert.net)**, **İkisi de**

Kullanıcı sunucuyu zaten söylediyse (ör. "agfo.app'e kuracağım", "Netcup için") tekrar sorma. Sohbet başında bir kez sorulur; aynı sohbette sonraki revizyonlar için cevabı yeniden kullan. Kullanıcı yanıt vermiyorsa ya da oturum gözetimsizse **İkisi de** varsay ve bunu çıktının başında belirt. Cevaba göre §1'deki sunucuya özel kuralları uygula.

1. Depoya erişim varsa (GitHub bağlantısı veya kod çalıştırma ortamı) `SPEC.md`, `README.md` ve ilgili aracın `VERSION`, `install.sh`, `uninstall.sh` dosyalarını oku. Erişim yoksa kullanıcıdan ilgili aracın ZIP'ini ya da dosyalarını yüklemesini iste; dosyaları görmeden revizyon yapma.
2. Revizyonsa önce **işlev envanteri** çıkar (uç noktalar, butonlar, ayarlar, ortam değişkenleri). Teslimden önce yeni sürümle karşılaştır; açıkça istenmedikçe hiçbir işlev kaybolamaz.
3. Depo herkese açıktır (Public): koda, belgelere ve commit mesajlarına IP adresi, jeton, şifre, API anahtarı yazılmaz.
4. Teslim: aracın **tam ZIP paketi** (`agfo-<araç>-<MAJOR.MINOR.PATCH>.zip`), kökünde `install.sh`. Paket adında ek son ek yok; "staging" kelimesi hiçbir yerde kullanılmaz.

## 1. Hedef sunucular

| | Hetzner | Netcup |
|---|---|---|
| Alan adı | agfo.app | agfocert.net |
| Ön güvenlik duvarı | Hetzner Cloud Firewall — portları kullanıcı Hetzner Console'dan elle açar | Sunucu içi firewalld/ufw |
| Python | 3.11'in altında | kurulumda tespit |
| Not | PHP 8.4 korunmalı | AGFO SafeGuard kurulmaz |

Ortak kod (`common/`, menü, manifest, tema) iki sunucuda da aynıdır; seçilen sunucu yalnızca aşağıdaki noktaları değiştirir.

**Hetzner seçildiyse:**
- Sunucu dışındaki Hetzner Cloud Firewall'ı kurulum açamaz. Yeni dış port varsa kurulum çıktısının sonunda ve kullanıcıya teslim notunda "Hetzner Console → Firewall → Inbound: TCP <port> ekleyin" uyarısı bulunur; kaldırmada aynı kuralın silinmesi hatırlatılır.
- Python 3.11'in altında: 3.8 uyumu zorunlu; `match`, `tomllib`, `str | None` gibi yeni sözdizimi/modül kullanılmaz.
- PHP 8.4'e ve mevcut lsphp sürümlerine dokunulmaz; PHP gerekiyorsa kurulu sürüm tespit edilip kullanılır, yenisi kurulmaz/kaldırılmaz.
- agfo.app sitelerini etkileyen OLS/vhost değişikliği yapılmaz; gerekirse işaretli blokla yapılır ve manifeste yazılır.

**Netcup seçildiyse:**
- Portlar sunucu içi firewalld/ufw ile açılır; hangisiyle açıldığı manifestteki `via` alanına yazılır.
- agfocert.net DNS'i bu sunucuda (ns1/ns2.agfocert.net); DNS bölgelerine/PowerDNS'e dokunan işlem açık onay olmadan yapılmaz.
- AGFO SafeGuard bu sunucuya kurulmaz; ona bağımlılık eklenmez.
- `disable_functions` geniş olabilir (`mail`, `shell_exec`, `system`…); PHP bileşenleri bunlara dayanmaz.

**İkisi de seçildiyse:**
- Her iki listenin kısıtları birlikte uygulanır (en kısıtlayıcı olan geçerli).
- Kurulum sunucuyu kendisi tespit eder (`common/agfo_common.py` → `/var/lib/agfo/server.json`: `hetzner` / `netcup`) ve yalnızca o sunucuya ait adımı çalıştırır (ör. Hetzner Console uyarısı sadece Hetzner'da basılır). Tespit edilemezse `AGFO_SERVER=hetzner|netcup` ortam değişkeni kullanılır.
- Teslim notunda iki sunucu için kurulum komutları ayrı ayrı yazılır; önerilen kurulum sırası Netcup → Hetzner.
- Tek ZIP her iki sunucuya da kurulur; sunucuya özel ayrı paket üretilmez.

## 2. Temel ilkeler

- **Harici bağımlılık yok:** yalnızca Python standart kütüphanesi, en düşük **Python 3.8**. PHP gerekirse CyberPanel'in `lsphp`'si.
- **Package Runner ile kurulum:** tty istemez, soru sormaz, ayarlar `AGFO_<KISA>_*` ortam değişkenleriyle. Runner `/var/lib/agfo-package-runner/work/...` altında root olarak çalışır; oradan başka kullanıcı adına dosya çalıştırma, önce `/opt/<slug>/` altına kopyala.
- **Idempotent ve ayar koruyan yükseltme:** aynı `install.sh` yeniden çalışınca şifre, IP kilidi, API anahtarları, jeton, oturumlar, sertifikalar korunur.
- **systemd servisi**, varsayılan HTTPS, CyberPanel Let's Encrypt sertifikasının bulunması, günlük `<slug>-certwatch.timer`.
- **Güvenlik tabanı:** PBKDF2-SHA256 şifre, IP başına kaba kuvvet kilidi, HttpOnly+SameSite çerez, CSRF başlığı, Origin denetimi, `allow_ips`, menüden şifresiz giriş jetonu (`auth.token_login`).

## 3. Port kaydı

| Slug | Port |
|---|---|
| agfo-ssh-terminal | 8822 |
| agfo-firewall-ai | 8823 |
| agfo-app-store | 8824 |
| (boş) | 8825 |
| agfo-file-manager | 8826 (+ iç 18096) |

Yeni araç ilk boş portu alır (8825, sonra 8827…). İç portlar 127.0.0.1'de, 18000–18999. Port, README ve SPEC.md tablosuna aynı commit'te yazılır. Kurulum öncesi portun boş olduğunu denetle.

## 4. ZORUNLU — Menü bağlantısı

Her araç kurulur kurulmaz CyberPanel kenar menüsüne **kendi** girdisini ekler, kaldırılınca **yalnızca kendi** girdisini siler. Ayrı menü paketi çalıştırmak gerekmez.

- Kayıt: `/var/lib/agfo/menu.d/<slug>.json`
  ```json
  {"slug":"agfo-x","label":"AGFO X","url_from":"/opt/agfo-x/config/config.json","token_param":true,"target":"blank","icon":"fa-...","order":50}
  ```
- `install.sh` sonunda kaydı yazar → `agfo-menu sync`; `uninstall.sh` başında kaydı siler → `agfo-menu sync`.
- `agfo-menu sync` şablona işaretli blok yazar ve kayıtta olmayan işaretli blokları siler:
  ```html
  <!-- agfo-menu:<slug>:start --> <li>…</li> <!-- agfo-menu:<slug>:end -->
  ```
  Blok, mevcut bir menü girdisinin kalıbı (ikon, sınıflar, girinti) kopyalanarak üretilir.
- **Asla** "en yeni `.agfo-bak` yedeğini geri yükle" yöntemiyle geri alma yapma; diğer araçların girdilerini ve CyberPanel güncellemelerini bozar.
- Link: `public_url` + giriş jetonu. IP ile yayınlanan panelde 8090 sertifikasının alan adı yalnızca panelin sertifikası onu kapsıyorsa kullanılır.
- CyberPanel güncellemesine dayanıklılık: `agfo-menu-sync.path` (şablonu izler) + günlük `agfo-menu-sync.timer`.
- Değişiklik sonrası `lscpd` gecikmeli, `--no-block` yeniden başlatılır.
- Varsayılan yeni sekme; elle eklenmiş Package Runner girdisinin yalnızca sekmesi ayarlanır, adresine dokunulmaz.
- App Store'un menü editörü aynı `menu.d` kayıtlarını okur/yazar.
- `agfo-menu` ve zamanlayıcıları referans sayımlı paylaşılan bileşendir: ilk araçla kurulur, son araçla kaldırılır.

## 5. ZORUNLU — Açık renk tema

Yeni araçların hepsi açık tema; CyberPanel'in açık görünümüyle uyumlu. Ortak dosya: `common/ui/agfo-light.css`.

```css
:root{color-scheme:light;
 --bg:#f5f7fa; --surface:#ffffff; --surface-2:#eef2f7; --line:#d9e0ea;
 --fg:#1f2933; --fg-dim:#52606d; --accent:#1d4ed8;
 --ok:#15803d; --warn:#b45309; --err:#b91c1c;}
```

- Metin/zemin kontrastı WCAG AA (≥ 4.5:1). Koyu zemin üzerinde koyu metin yasak.
- Sistem font yığını; kod/log alanları `ui-monospace`.
- Kod düzenleyiciler açık temayla (Ace: `github` / `textmate`).
- Koyu temalı mevcut araçlara (Terminal, Firewall AI, App Store) dokunulduğunda bir sonraki minor sürümde açık temaya geçir; hiçbir ekran işlevi kaybolmaz.

## 6. ZORUNLU — İzsiz kaldırma

Kurulum, sunucuda bıraktığı her izi manifeste yazar; kaldırma yalnızca manifeste göre çalışır, tahminle `rm` yapılmaz.

Manifest: `/var/lib/agfo/installed/<slug>.json`
```json
{"slug":"","version":"","installed_at":"","server":"hetzner|netcup",
 "paths":[],"units":[],"ports":[{"port":0,"via":"firewalld|ufw|csf"}],
 "files_added":[],"files_patched":[{"path":"","marker":""}],
 "packages":[{"name":"","preexisting":false}],"cron":[],"users":[],
 "menu":"/var/lib/agfo/menu.d/<slug>.json","shared":["agfo-menu"]}
```

Kaldırmada:
- `/opt/<slug>`, log dizinleri, `__pycache__`, `work/`, `trash/` → silinir
- systemd birimleri → durdur, devre dışı bırak, dosyayı sil, `daemon-reload`
- Portlar → hangi araçla açıldıysa (firewalld/ufw/CSF) onunla kapat
- Eklenen yapılandırma dosyaları → sil; yamalanan dosyalar → yalnızca işaretli bloğu çıkar
- apt/dnf paketleri → yalnızca `preexisting:false` ve başka AGFO aracı kullanmıyorsa kaldır
- Menü → `menu.d` sil + `agfo-menu sync`
- Bu kurulumun oluşturduğu `.agfo-bak-*` dosyaları → sil
- Paylaşılan bileşenler → referans sayısı 0 ise sil
- Manifest → en son sil
- Hetzner'da: "Hetzner Console'dan TCP <port> kuralını silin" uyarısı bas

Modlar:
```bash
bash uninstall.sh                      # TAM kaldırma, iz bırakmaz (varsayılan)
AGFO_KEEP_CONFIG=1 bash uninstall.sh   # config'i bırak
AGFO_UNINSTALL_BACKUP=1 ...            # config'i /root/agfo-uninstall-<slug>-<sürüm>-<zaman>.tar.gz olarak yedekle
```
- Kaldırma idempotenttir.
- Sonunda `agfo-trace-check <slug>` çalışır; kalan iz varsa listeler ve sıfırdan farklı kodla çıkar.
- App Store'un "Kaldır" düğmesi bu betiği çağırır, kendi silme mantığı taşımaz.
- App Store'un kurduğu siteler/veritabanları CyberPanel'e aittir, silinmez.

## 7. ZORUNLU — Sürümlü ZIP arşivi

Adlandırma: `agfo-<araç>-<MAJOR.MINOR.PATCH>.zip`, kökünde `install.sh`.

**Depoda:** `packages/<araç>/agfo-<araç>-<sürüm>.zip` + `packages/index.json`
```json
{"generated_at":"","tools":{"agfo-x":{"latest":"1.2.0","versions":{"1.2.0":{"file":"agfo-x/agfo-x-1.2.0.zip","sha256":"","size":0,"date":""}}}}}
```
- `tools/make-packages.sh` ZIP'i `packages/<araç>/` altına yazar, SHA-256 hesaplar, `index.json`'ı günceller.
- Aynı sürüm numarasıyla farklı içerik üretilirse durur: önce sürümü yükselt.
- "En güncel" = semver'e göre en yüksek sürüm.
- `config/config.json`, anahtarlar, TLS, loglar ZIP'e girmez.
- GitHub Release iş akışı aynı ZIP'leri etikete de ekler.

**Sunucuda:** her `install.sh` kendi ZIP'inin kopyasını `/var/lib/agfo/packages/<araç>/` altına bırakır ve sunucu `index.json`'ını günceller. Bu arşiv araç kaldırılınca silinmez; yalnızca `AGFO_PURGE_ARCHIVE=1` ile silinir.

**İndirme:** App Store "Paketler" sekmesi (en güncel / kurulu / depodaki sürüm, İndir, Bu sürüme dön, "güncelleme var" rozeti) ve CLI `agfo-pkg latest <araç>`, `agfo-pkg list`.

## 8. Ortak kod ve depo yapısı

```
common/agfo_common.py   manifest, port, sertifika, firewall, sunucu tespiti (/var/lib/agfo/server.json)
common/agfo-menu        menü senkronu
common/agfo-trace-check iz denetimi
common/agfo-pkg         paket arşivi aracı
common/ui/agfo-light.css
agfo-<araç>/{VERSION,install.sh,uninstall.sh,README.md,CHANGELOG.md,app/,config/,systemd/}
packages/
tools/make-packages.sh
```
`common/` derlemede her ZIP'e kopyalanır; her ZIP depoya erişmeden tek başına kurulabilir.

## 9. Sürümleme

SemVer. `VERSION` ile `install.sh` içindeki `APP_VERSION` aynı olmalı (paketleme denetler). PATCH = düzeltme, MINOR = özellik/tema geçişi, MAJOR = yapılandırma biçimi değişikliği (geçiş betiği zorunlu). Her sürümde CHANGELOG + README araç tablosu + App Store kataloğu güncellenir.

## 10. Teslim öncesi kontrol listesi

- [ ] İşlev envanteri önceki sürümle karşılaştırıldı, kayıp yok
- [ ] Port boş ve tabloya işlendi
- [ ] `install.sh` tty'siz, idempotent, ayar koruyan
- [ ] Manifest tüm izleri kaydediyor
- [ ] `menu.d` kaydı + `agfo-menu sync`; kaldırmada girdi siliniyor
- [ ] Açık tema, AA kontrast
- [ ] `uninstall.sh` manifeste göre; `agfo-trace-check` temiz
- [ ] ZIP kopyası sunucu arşivine bırakılıyor
- [ ] `packages/` ve `index.json` güncel; `VERSION` = `APP_VERSION`
- [ ] `python3.8 -m py_compile` ve `bash -n` temiz
- [ ] README, CHANGELOG, App Store kataloğu güncel
- [ ] Tek commit ile `main`'e gönderildi, tarih etiketi atıldı (§12)
- [ ] Hedef sunucu (Hetzner / Netcup / İkisi de) belli ve §1'deki kuralları uygulandı
- [ ] Kullanıcıya: kurulum komutu, gerekli ortam değişkenleri, Hetzner port uyarısı, kaldırma komutu

## 11. Test sırası

Yalnızca seçilen sunucu(lar)da; "İkisi de" ise test VM → Netcup → Hetzner:
1. Temiz kurulum: servis, port, menü girdisi, açık tema
2. Yeniden kurulum: ayarlar korunmuş, menü girdisi tek
3. Tam kaldırma: iz denetimi temiz, diğer araçların menüsü sağlam
4. `AGFO_KEEP_CONFIG=1` kaldırma + yeniden kurulum: ayarlar geri
5. Menü şablonu ezilince sync girdileri geri koyuyor

## 12. ZORUNLU — Depoyu güncel tutma

Depo (`downtownck/agfo-cyberpanel`) tek dallıdır ve tüm geçmiş doğrudan `main`'e işlenmiştir. Her değişiklik **sormadan, doğrudan `main`'e** gönderilir; dal veya pull request açılmaz. Bu karar depo yapısından çıkar, kullanıcıya tekrar sorulmaz.

- Bir araç değişikliği **tek commit**: kod, `VERSION`, `APP_VERSION`, `CHANGELOG.md`, README araç tablosu, `packages/<araç>/<araç>-<sürüm>.zip`, `packages/index.json`; `SPEC.md` değiştiyse o da.
- Commit mesajı mevcut düzende: `<Araç> <sürüm>: <kısa özet>` (çoklu: `Menu 1.5.1: …; Firewall AI 1.1.2, …`). Commit yazarı kullanıcının mevcut commit'lerindeki kimlikle aynı olur; ortam talimatı varsa yardımcı yazar satırı eklenir.
- Göndermeden önce: `git fetch origin main && git rebase origin/main`; sonra `git push origin HEAD:main`.
- Sürüm içeren gönderimden sonra tarih etiketi: `git tag vYYYY.MM.DD && git push origin vYYYY.MM.DD` (aynı gün ikincisi `vYYYY.MM.DD.2`). Release iş akışı ZIP'leri GitHub Releases'e ekler.
- `SPEC.md` değiştiğinde bağlı projedeki kopyası da güncellenir (varsa).
- Bu depoya ait bir skill (bu skill dahil) oluşturulur ya da değiştirilirse `skills/<ad>/claude/SKILL.md`, `skills/<ad>/chatgpt/` ve `skills/<ad>/<ad>-chatgpt.zip` güncellenip `Skill <ad>: <özet>` mesajıyla gönderilir.
- Ortamda depoya yazma yetkisi yoksa (GitHub bağlantısı salt okunur veya yok) değişen dosyaları ve hazır commit mesajını kullanıcıya ver.
- Gönderim başarısızsa (erişim, çakışma) bunu açıkça söyle ve dosyaları kullanıcıya teslim et; gönderilmiş gibi raporlama.
- Teslim mesajında commit kısa kodu ve etiket adı yazılır.
