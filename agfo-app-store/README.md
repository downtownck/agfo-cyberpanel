# AGFO App Store 1.0.3

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
unzip agfo-app-store-1.0.3.zip && cd agfo-app-store-1.0.3 && bash install.sh
```

Kurulum sonunda panel adresi, menü linki ve (ilk kurulumda) panel şifresi
yazılır. Ardından `agfo-ssh-menu` 1.4.0 paketini çalıştırırsanız menüye
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

## Katalog (12 uygulama)

| Uygulama | Kurulum | Kaynak | PHP |
|---|---|---|---|
| WordPress | tam otomatik (wp-cli) | resmi "son sürüm" adresi | 7.4+ |
| Nextcloud | tam otomatik (occ) | resmi "son sürüm" adresi | 8.1+ |
| Moodle | tam otomatik | 4.5 LTS son yama (resmi) | 8.1+ |
| MediaWiki | tam otomatik | 1.43.10 LTS | 8.1+ |
| Grav | tam otomatik | resmi "son sürüm" adresi | 8.0+ |
| Joomla | sihirbaz | GitHub'daki son kararlı sürüm | 8.3+ |
| Drupal | sihirbaz | resmi "son sürüm" adresi | 8.3+ |
| EspoCRM | sihirbaz | GitHub'daki son kararlı sürüm | 8.3+ |
| phpMyFAQ | sihirbaz | 4.1.11 | 8.3+ |
| Matomo | sihirbaz | resmi "son sürüm" adresi | 8.0+ |
| phpBB | sihirbaz | 3.3.19 | 8.0+ |
| Dolibarr | sihirbaz | 24.0.1 (yalnız `htdocs/`) | 8.1+ |

**Tam otomatik**: kurulum bittiğinde yönetici kullanıcı ve şifre hazırdır.
**Sihirbaz**: site, SSL, veritabanı ve dosyalar hazırlanır; sonuç ekranındaki
veritabanı bilgileriyle uygulamanın kendi kurulum sihirbazını tarayıcıda
bitirirsiniz.

Kaynaklar mümkün olduğunca sürüm numarası içermeyen resmi "son sürüm"
adreslerinden ya da GitHub'ın son kararlı sürüm kaydından kurulum anında
bulunur; böylece eskimez. Sürüme sabit olanlar (phpBB, phpMyFAQ, MediaWiki,
Dolibarr) 2026-10-28'de resmi kaynaklarda doğrulandı ve zamanla güncellenmelidir.
İlk iş olarak *Ayarlar → Kataloğu doğrula* düğmesine basın: sunucu her
uygulamanın gerçek indirme adresini kurulumda kullanılan yolla yoklar.

**PHP:** mevcut bir siteye kurulumda uygulama o sitenin PHP sürümüyle çalışır.
Uygulama daha yüksek bir sürüm istiyorsa kurulum hiçbir şey oluşturmadan
reddedilir ve ne yapılacağı yazılır. Yeni site açılırken gereken sürüm
otomatik seçilir; sunucuda o `lsphp` kurulu değilse yine baştan reddedilir.

**Çıkarılanlar:** PrestaShop 9 (GitHub'da kurulabilir paket yok, yalnız
derlenmesi gereken kaynak), SuiteCRM 8 (belge kökünün `public/` olmasını
ister), LimeSurvey (paket adı her sürümde değişiyor, kalıcı adres yok) ve
Laravel (uygulama değil, Composer isteyen iskelet).

## Kurulum başarısız olursa

Önce indirme yapılır ve dosyanın gerçekten arşiv olduğu doğrulanır; adres
bozuksa site ya da veritabanı hiç açılmaz. Sonraki bir adım başarısız olursa
o kurulumun oluşturduğu her şey geri alınır: veritabanı, alt dizin, veri
klasörleri ve (siteyi bu kurulum açtıysa) site. Önceden var olan site ve
dosyalara dokunulmaz.

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
