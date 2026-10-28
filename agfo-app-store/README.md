# AGFO App Store 1.1.2

CyberPanel için tek tıkla uygulama kurulumu. Uygulamayı seçersiniz; mağaza
CyberPanel üzerinden yeni site (veya alt alan adı) açar, Let's Encrypt SSL
alır, veritabanını ve kullanıcısını oluşturur, dosyaları indirir, izinleri
CyberPanel'in kendi düzenine göre ayarlar ve mümkünse kurulumu komut satırından
bitirir. Her adım canlı günlükte görünür.

Bağımlılık yoktur: yalnızca Python 3.8+ standart kütüphanesi.

## Kurulum

AGFO Package Runner ile ZIP'i yükleyin; `install.sh` root olarak çalışır.

Elle:

```bash
unzip agfo-app-store-1.1.2.zip && cd agfo-app-store-1.1.2 && bash install.sh
```

Kurulum sonunda panel adresi, menü linki ve (ilk kurulumda) panel şifresi
yazılır. Ardından `agfo-ssh-menu` 1.5.0 paketini çalıştırırsanız menüye
**AGFO App Store** girdisi şifresiz giriş jetonuyla eklenir.

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `AGFO_STORE_PORT` | `8824` | Panel portu |
| `AGFO_STORE_DOMAIN` | 8090 sertifikasından | TLS için alan adı |
| `AGFO_STORE_CERT` / `_KEY` | — | Sertifikayı elle vermek için |
| `AGFO_STORE_PASSWORD` | üretilir | Panel şifresi (yükseltmede korunur) |
| `AGFO_STORE_ALLOW_IPS` | — | Yalnız bu IP'ler erişsin |
| `AGFO_STORE_PHP` | `8.2` | Yeni sitelerin PHP sürümü |
| `AGFO_STORE_TLS` | `1` | `0` = düz HTTP |
| `AGFO_STORE_WAIT` | `600` | Yükseltmede süren kurulum için bekleme (sn) |

Alan adı verilmezse betik CyberPanel'in 8090 portundaki sertifikadan alan
adını okur ve aynı Let's Encrypt sertifikasını kullanır; böylece tarayıcı
uyarısı çıkmaz.

## Katalog (63 uygulama)

| Uygulama | Kategori | Kurulum | PHP | Kaynak | Not |
|---|---|---|---|---|---|
| Backdrop CMS | İçerik yönetimi | sihirbaz | 8.1+ | GitHub son sürüm | korunan klasör |
| Bludit | İçerik yönetimi | sihirbaz | 8.0+ | sabit sürüm | korunan klasör |
| Concrete CMS | İçerik yönetimi | sihirbaz | 8.1+ | GitHub son sürüm | korunan klasör |
| Dotclear | İçerik yönetimi | sihirbaz | 8.2+ | resmi son sürüm | korunan klasör |
| Drupal | İçerik yönetimi | sihirbaz | 8.3+ | resmi son sürüm | – |
| e107 | İçerik yönetimi | sihirbaz | 8.1+ | sabit sürüm | korunan klasör |
| ExpressionEngine | İçerik yönetimi | sihirbaz | 8.1+ | GitHub son sürüm | korunan klasör |
| Grav | İçerik yönetimi | tek tıkla | 8.0+ | resmi son sürüm | – |
| Joomla | İçerik yönetimi | sihirbaz | 8.3+ | GitHub son sürüm | – |
| Omeka Classic | İçerik yönetimi | sihirbaz | 8.1+ | GitHub son sürüm | korunan klasör |
| ProcessWire | İçerik yönetimi | sihirbaz | 8.1+ | resmi son sürüm | korunan klasör |
| Serendipity | İçerik yönetimi | sihirbaz | 8.1+ | GitHub son sürüm | korunan klasör |
| Textpattern | İçerik yönetimi | sihirbaz | 8.1+ | GitHub son sürüm | – |
| Typemill | İçerik yönetimi | sihirbaz | 8.2+ | indirme sayfasından | korunan klasör |
| WonderCMS | İçerik yönetimi | tek tıkla | 8.0+ | GitHub son sürüm | korunan klasör |
| WordPress | İçerik yönetimi | tek tıkla | 7.4+ | resmi son sürüm | – |
| XOOPS | İçerik yönetimi | sihirbaz | 8.1+ | sabit sürüm | korunan klasör |
| AbanteCart | E-ticaret | sihirbaz | 8.2+ | sabit sürüm | korunan klasör |
| OpenCart | E-ticaret | sihirbaz | 8.1+ | GitHub son sürüm | korunan klasör |
| PrestaShop | E-ticaret | sihirbaz | 8.1+ | sabit sürüm | – |
| QloApps | E-ticaret | sihirbaz | 8.1+ | GitHub son sürüm | – |
| thirty bees | E-ticaret | sihirbaz | 8.2+ | GitHub son sürüm | – |
| WooCommerce | E-ticaret | tek tıkla | 7.4+ | resmi son sürüm | – |
| Zen Cart | E-ticaret | sihirbaz | 8.2+ | sabit sürüm | korunan klasör |
| Dolibarr | CRM ve iş | sihirbaz | 8.1+ | sabit sürüm | – |
| EspoCRM | CRM ve iş | sihirbaz | 8.3+ | GitHub son sürüm | – |
| Mautic | CRM ve iş | sihirbaz | 8.2+ | GitHub son sürüm | – |
| SuiteCRM 8 | CRM ve iş | sihirbaz | 8.1+ | GitHub son sürüm | web kökü public/ |
| Akaunting | Muhasebe ve fatura | sihirbaz | 8.1+ | GitHub son sürüm | – |
| Invoice Ninja | Muhasebe ve fatura | sihirbaz | 8.2+ | GitHub son sürüm | web kökü public/ |
| InvoicePlane | Muhasebe ve fatura | sihirbaz | 8.1+ | GitHub son sürüm | korunan klasör |
| Kanboard | Proje ve görev | tek tıkla | 8.1+ | sabit sürüm | korunan klasör |
| Leantime | Proje ve görev | sihirbaz | 8.2+ | GitHub son sürüm | web kökü public/ |
| FreeScout | Destek masası | sihirbaz | 8.2+ | resmi son sürüm | web kökü public/ |
| osTicket | Destek masası | sihirbaz | 8.2+ | GitHub son sürüm | korunan klasör |
| Chamilo | Eğitim | sihirbaz | 8.3+ | GitHub son sürüm | web kökü public/, yalnız kök |
| Gibbon | Eğitim | sihirbaz | 8.1+ | GitHub son sürüm | korunan klasör |
| Moodle | Eğitim | tek tıkla | 8.1+ | resmi son sürüm | – |
| DokuWiki | Wiki ve bilgi | sihirbaz | 8.2+ | GitHub son sürüm | korunan klasör |
| MediaWiki | Wiki ve bilgi | tek tıkla | 8.1+ | sabit sürüm | – |
| phpMyFAQ | Wiki ve bilgi | sihirbaz | 8.3+ | sabit sürüm | – |
| PmWiki | Wiki ve bilgi | tek tıkla | 8.1+ | resmi son sürüm | korunan klasör |
| MyBB | Forum | sihirbaz | 8.1+ | GitHub son sürüm | – |
| phpBB | Forum | sihirbaz | 8.0+ | sabit sürüm | – |
| Friendica | İşbirliği | sihirbaz | 8.1+ | sabit sürüm | korunan klasör |
| HumHub | İşbirliği | sihirbaz | 8.2+ | sabit sürüm | korunan klasör |
| Nextcloud | İşbirliği | tek tıkla | 8.3+ | resmi son sürüm | – |
| FileGator | Dosya ve medya | tek tıkla | 8.1+ | resmi son sürüm | web kökü dist/ |
| Lychee | Dosya ve medya | sihirbaz | 8.4+ | GitHub son sürüm | web kökü public/ |
| Piwigo | Dosya ve medya | sihirbaz | 8.1+ | indirme sayfasından | – |
| Tiny File Manager | Dosya ve medya | tek tıkla | 8.0+ | resmi son sürüm | – |
| Zenphoto | Dosya ve medya | sihirbaz | 8.1+ | sabit sürüm | korunan klasör |
| phpList | E-posta | sihirbaz | 8.1+ | resmi son sürüm | korunan klasör |
| Roundcube | E-posta | sihirbaz | 8.1+ | GitHub son sürüm | web kökü public_html/ |
| SnappyMail | E-posta | tek tıkla | 8.0+ | sabit sürüm | korunan klasör |
| LimeSurvey | Analitik ve anket | sihirbaz | 8.1+ | indirme sayfasından | – |
| Matomo | Analitik ve anket | sihirbaz | 8.0+ | resmi son sürüm | – |
| Revive Adserver | Analitik ve anket | sihirbaz | 8.1+ | indirme sayfasından | korunan klasör |
| Adminer | Araçlar | tek tıkla | 8.0+ | GitHub son sürüm | – |
| FreshRSS | Araçlar | sihirbaz | 8.1+ | sabit sürüm | web kökü p/ |
| phpMyAdmin | Araçlar | tek tıkla | 8.1+ | resmi son sürüm | korunan klasör |
| Shaarli | Araçlar | sihirbaz | 8.2+ | GitHub son sürüm | korunan klasör |
| YOURLS | Araçlar | sihirbaz | 8.1+ | sabit sürüm | – |

**Tam otomatik**: kurulum bittiğinde yönetici kullanıcı ve şifre hazırdır.
**Sihirbaz**: site, SSL, veritabanı ve dosyalar hazırlanır; sonuç ekranındaki
veritabanı bilgileriyle uygulamanın kendi kurulum sihirbazını tarayıcıda
bitirirsiniz.

Kaynaklar mümkün olduğunca sürüm numarası içermeyen resmi "son sürüm"
adreslerinden ya da GitHub'ın son kararlı sürüm kaydından kurulum anında
bulunur; böylece eskimez. "Sabit sürüm" olanlar 2026-10-28/29'da resmi kaynaklarda doğrulandı ve zamanla güncellenmelidir;
sağlık testi eskiyenleri gösterir, *AI'ya sor* yenisini önerir.
İlk iş olarak *Ayarlar → Kataloğu doğrula* düğmesine basın: sunucu her
uygulamanın gerçek indirme adresini kurulumda kullanılan yolla yoklar.

**PHP:** mevcut bir siteye kurulumda uygulama o sitenin PHP sürümüyle çalışır.
Uygulama daha yüksek bir sürüm istiyorsa kurulum hiçbir şey oluşturmadan
reddedilir ve ne yapılacağı yazılır. Yeni site açılırken gereken sürüm
otomatik seçilir; sunucuda o `lsphp` kurulu değilse yine baştan reddedilir.

**Alınmayanlar ve nedenleri** (2026-10-29 araştırması): ownCloud (PHP 7.4'e
kilitli), Grocy ve Firefly III (PHP 8.5 ister), BookStack, Kimai ve Laravel
(hazır paket yok, Composer derlemesi ister), Wallabag ve ProjectSend (web
kurulumu yok, komut satırı ve kuyruk işçisi ister), SMF (resmi paket adresi
doğrulanamadı), MODX (kalıcı indirme adresi yok), Pico (geliştiricileri
terk etti), YetiForce (depo arşivlendi), Kirby (açık sitelerde ücretli lisans),
HESK (kalıcı adres yok, açık kaynak değil). PrestaShop 8.x PHP 8.1'de kaldığı
için PrestaShop 9 paketi kullanılır; LimeSurvey ve SuiteCRM artık destekleniyor.

**OpenLiteSpeed notu:** OpenLiteSpeed `.htaccess` içindeki `Deny`/`Require`
satırlarını uygulamaz, yalnızca yönlendirme kurallarını işler. Pek çok uygulama
hassas klasörlerini (veri, config, log) bu satırlarla korur. Tariflerdeki
`deny` listesi bu klasörleri yönlendirme kuralıyla (`[F]`) kapatır; deneme
kurulumu da bu klasörleri dışarıdan çağırıp gerçekten kapalı olduklarını
doğrular.

## Kurulum başarısız olursa

Önce indirme yapılır ve dosyanın gerçekten arşiv olduğu doğrulanır; adres
bozuksa site ya da veritabanı hiç açılmaz. Sonraki bir adım başarısız olursa
o kurulumun oluşturduğu her şey geri alınır: veritabanı, alt dizin, veri
klasörleri ve (siteyi bu kurulum açtıysa) site. Önceden var olan site ve
dosyalara dokunulmaz.

## Kurulum önerileri

Kurulum penceresi açıldığında sunucu incelenir ve öneriler kart olarak gelir;
birine tıklamak alanları doldurur:

- **Yeni alt alan adı** (ör. `moodle.alanadi.com`): uygulamaya ayrı bir ev.
  DNS'in bu sunucuyu gösterip göstermediği belirtilir.
- **Boş mevcut site** ya da **dolu sitede alt dizin** (`/moodle`): sitedeki
  kurulumlar ve kök dizinin doluluğu dikkate alınır.
- **PHP sürümü**: sunucudaki her `lsphp`, uygulamanın desteklediği aralığa
  (`php`–`php_max`) ve gereken PHP eklentilerinin (`php -m`) o sürümde kurulu
  olup olmadığına göre değerlendirilir; uygun olanların en yenisi seçilir.
  Eksik eklenti varsa hangi paketin kurulacağı yazılır (ör. `lsphp82-sodium`).
- **Mevcut sitenin PHP'si uymuyorsa**: kurulum başlamadan durur. İsterseniz
  "sitenin PHP sürümünü değiştir" seçeneğiyle sürüm değiştirilir; kurulum
  başarısız olursa eski sürüm geri yüklenir.
- Son kullanılan e-posta hatırlanır.

## Katalog sağlık testi

*Ayarlar → Katalog sağlık testi* her uygulamayı bu sunucuda, gerçek paketiyle
dener. Sonuç mağaza kartlarında etiket olarak görünür:
**✓ doğrulandı** (deneme kurulumu geçti), **paket tamam** (paket testi geçti,
henüz kurulmadı), **uyarılı**, **sorunlu**, **denenmedi**.

- **Paket testi** (hızlı, hiçbir şey kurmaz): paketi indirir, arşiv mi diye
  bakar, açar; kökte PHP giriş dosyası (ya da `public/index.php`), kurulum
  sihirbazının dosyası, `composer.json` varsa `vendor/` klasörünün gelip
  gelmediği (gelmediyse paket derleme ister, çalışmaz) ve paketin istediği PHP
  sürümünün sunucuda kurulu olup olmadığı denetlenir.
- **Deneme kurulumu** (asıl test): uygulama ayrı bir test sitesine
  (`Ayarlar`'da tanımlanır; yoksa App Store PHP 8.3 ile kendisi açar, DNS
  gerekmez) gerçekten kurulur, kurulum sayfası sunucunun içinden çağrılır
  (HTTP kodu, `Fatal error`/`Uncaught`/500 gibi izler aranır) ve ardından
  veritabanıyla birlikte iz bırakmadan kaldırılır.

Tüm katalogda deneme kurulumu uzun sürer ve birkaç GB indirme yapar; tek tek
*Dene* düğmesiyle de çalıştırılabilir. Başarısız uygulamalar için *AI'ya sor*
ile yeni kaynak önerisi alınabilir.

## AI desteği

Firewall AI'ya girdiğiniz sağlayıcı anahtarları (`/opt/agfo-firewall-ai/config/providers.json`)
burada da kullanılır; yeniden girmeniz gerekmez. *Ayarlar → AI desteği*
bölümünden hangi sağlayıcının ve modelin kullanılacağını seçebilir, isterseniz
yalnızca bu panele ait ayrı bir anahtar ekleyebilirsiniz (öncelikli olur).
Firewall AI ile aynı ilke geçerlidir: **AI yalnızca öneri üretir.**

- **Kurulum hatası analizi:** başarısız bir işin penceresinde *AI ile analiz et*.
  Günlük ve kurulum bilgisi gönderilir; veritabanı ve yönetici şifreleri
  gönderilmeden önce maskelenir. Sonuç: özet, kök neden, adımlar, güven düzeyi.
- **Katalog onarımı:** *Kataloğu doğrula* sonucunda erişilemeyen bir uygulama
  için *AI'ya sor*. AI yeni bir kaynak önerir, sunucu bu adresi hemen yoklar;
  erişilemiyorsa *Uygula* düğmesi kapalı kalır. Onaylanan düzeltme
  `config/catalog-overrides.json` dosyasına yazılır (paket yükseltmesinde
  kaybolmaz) ve *Geri al* ile kaldırılabilir.

AI'nın önerdiği adresler de yanlış olabilir; yoklama yalnızca adresin
indirilebildiğini gösterir, doğru paket olduğunu değil. İlk kurulumda dosya
yine arşiv olarak doğrulanır, değilse hiçbir şey oluşturulmadan durur.

## Sunucu araçları

*Sunucu araçları* sekmesi Runner ile kurulan AGFO araçlarını listeler
(`agfo-*` systemd servisleri ve `/opt/agfo-*` kurulumları): sürüm, durum, port,
panelin jetonlu açma bağlantısı. Yapılabilenler: yeniden başlatma,
durdurma/başlatma, son günlük (journalctl) ve kaldırma. Kaldırma aracın kendi
`uninstall.sh` betiğini çalıştırır; adını yazarak onaylamanız gerekir ve
betik root'a ait değilse ya da başkaları yazabiliyorsa çalıştırılmaz. App Store
kendini durduramaz ve kaldıramaz; kendi yeniden başlatması 3 saniye ertelenir.
Kaldırılan bir aracın CyberPanel menü girdisi için menü paketini yeniden
çalıştırın.

## Kaldırma

*Kurulu uygulamalar* sekmesinde her satırda **Kaldır** düğmesi vardır.
Onaylamak için alan adını aynen yazmanız gerekir.

- **Yedek (varsayılan açık):** dosyalar silinmez, taşınır; veritabanı
  `mysqldump` ile dökülür. Hepsi `/opt/agfo-app-store/trash/<alanadi>-<uygulama>-<tarih>/`
  altında durur (`files/`, `<veritabani>.sql`, `kayit.json`). Yedek
  alınamazsa hiçbir şey silinmez, işlem durur.
- **Veritabanı:** CyberPanel üzerinden silinir ve gerçekten silindiği
  kontrol edilir; silinemezse işlem uyarıyla biter ve ne yapılacağı yazılır.
- **Site:** yalnızca siteyi App Store açtıysa ve kurulum kök dizindeyse
  "siteyi de sil" seçeneği çıkar. Önceden var olan sitelerde yalnız
  uygulama dosyaları ve veritabanı kaldırılır, site yerinde kalır.
- `.well-known` (SSL doğrulaması) dokunulmadan bırakılır.

Yedekten geri dönmek için `files/` içeriğini site köküne geri taşıyıp
`.sql` dosyasını aynı adla oluşturduğunuz veritabanına yükleyin. Yedekler
kendiliğinden silinmez; gerekmediğinde `trash/` altından elle silin.

## Tarif biçimi

```json
{
  "id": "ornek", "name": "Örnek", "category": "cms", "install_mode": "cli",
  "download": {"url": "https://...", "sha256": "", "strip": 1},
  "database": true,
  "fields": [{"name": "admin_user", "label": "Yönetici", "type": "text"}],
  "steps": [
    {"type": "write", "path": "config.php", "mode": "0640", "content": "<?php $db='{db_name}';"},
    {"type": "run", "argv": ["{php}", "install.php", "--admin={admin_user}"]}
  ]
}
```

İndirme tanımı üç biçimde olabilir: sabit adres (`url`), GitHub'daki son
kararlı sürümün paketi (`github` + `asset` deseni; API sınırına takılırsa
sürüm sayfasından bulunur) ya da resmi indirme sayfasından desenle bulunan
adres (`page` + `regex`). `format: "file"` tek PHP dosyalı uygulamalar içindir
(`target` dosya adı). `only` arşivin bir alt klasörünü kurar, `web_root:
"public"` istekleri `public/` klasörüne yönlendiren ve diğer klasörleri
(`.env`, `vendor`, `storage`) dışarıya kapatan `.htaccess` yazar.

Adım türleri: `mkdir`, `write`, `copy` (ör. `.env.example` → `.env`), `env`
(`.env` dosyasına anahtar yazar), `run` (site kullanıcısıyla, kabuksuz),
`delete`, `chown`.

Adımlar kabuk kullanmaz (yalnız argv listesi), `{degisken}` yer tutucuları
doldurulur, tüm yollar site kökünün dışına çıkamaz. Komutlar site kullanıcısı
olarak çalışır, root olarak değil.

## Güvenlik

- Panel root yetkisiyle çalışır (site açmak için gerekli); bu yüzden şifre ve
  menü jetonu korunur, PBKDF2 ile saklanır, kaba kuvvet denemeleri IP bazında
  kilitlenir, tüm yazma istekleri CSRF ve Origin denetiminden geçer.
- Menü linkindeki `?t=` jetonu şifresiz giriş sağlar; linki paylaşmayın.
  Jetonu yenilemek için `config.json` içindeki `auth.login_token` alanını
  silip `install.sh`'yi yeniden çalıştırın ve ardından menü paketini çalıştırın.
- Tüm işlemler `config/audit.log` dosyasına yazılır.

## Yönetim

```bash
systemctl status agfo-app-store
journalctl -u agfo-app-store -f
bash /opt/agfo-app-store/uninstall.sh          # siteler silinmez
AGFO_STORE_PURGE=1 bash /opt/agfo-app-store/uninstall.sh
```

Servis yeniden başlarken süren bir kurulum varsa iş "hata" olarak kapatılır;
site ve veritabanı kısmen oluşmuş olabilir, CyberPanel'den kontrol edin.
