# AGFO App Store 1.0.1

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
unzip agfo-app-store-1.0.1.zip && cd agfo-app-store-1.0.1 && bash install.sh
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

## Katalog (16 uygulama)

| Uygulama | Kurulum | Sürüm |
|---|---|---|
| WordPress | tam otomatik (wp-cli) | latest |
| Nextcloud | tam otomatik (occ) | latest |
| Moodle | tam otomatik | latest |
| MediaWiki | tam otomatik | 1.43.1 |
| Grav | tam otomatik | latest |
| Joomla | sihirbaz | 5.3.2 |
| Drupal | sihirbaz | 11.1.0 |
| Matomo | sihirbaz | latest |
| phpBB | sihirbaz | 3.3.14 |
| PrestaShop | sihirbaz | 8.2.0 |
| Dolibarr | sihirbaz | 21.0.0 |
| EspoCRM | sihirbaz | 8.4.2 |
| SuiteCRM | sihirbaz | 8.7.1 |
| LimeSurvey | sihirbaz | 6.6.4 |
| phpMyFAQ | sihirbaz | 4.0.9 |
| Laravel | sihirbaz | 11.0.0 |

**Tam otomatik**: kurulum bittiğinde yönetici kullanıcı ve şifre hazırdır.
**Sihirbaz**: site, SSL, veritabanı ve dosyalar hazırlanır; sonuç ekranındaki
veritabanı bilgileriyle uygulamanın kendi kurulum sihirbazını tarayıcıda
bitirirsiniz.

**Önemli:** Sürüme sabitlenmiş indirme adresleri zamanla eskir. İlk iş olarak
*Ayarlar → Kataloğu doğrula* düğmesine basın; sunucu her adresi kontrol eder
ve erişilemeyenleri listeler. Adresi değiştirmek için
`/opt/agfo-app-store/app/catalog/<uygulama>.json` içindeki `download.url`
alanını güncelleyin (paneli yeniden başlatmaya gerek yok).

Softaculous'un 400+ uygulamalık kataloğu lisanslı ve kapalıdır; buraya
kopyalanamaz. Bunun yerine her uygulama tek bir JSON tarifidir; yeni uygulama
eklemek için mevcut bir tarifi kopyalayıp düzenlemek yeterlidir.

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
