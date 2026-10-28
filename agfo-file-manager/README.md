# AGFO File Manager 1.0.0

CyberPanel sunucusu için **root yetkili web dosya yöneticisi**. Kök dizin `/`:
`/root`, `/etc`, `/usr/local/lsws`, tüm sitelerin `/home/*` dizinleri dahil her
şeye tarayıcıdan erişirsiniz.

Arayüz, açık kaynak **[Tiny File Manager](https://github.com/prasathmani/tinyfilemanager)**
(GPL-3.0) üzerine kuruludur; AGFO'ya uyarlanmış ve önüne AGFO'nun güvenlik
katmanı konmuştur.

## Neler yapabilir

* Tüm diskte gezinme, gizli dosyalar görünür, tam yol gösterimi
* **Kod düzenleyici** (Ace, sözdizimi renklendirme, monokai) — `.htaccess`,
  `wp-config.php`, `vhost.conf`, `.env`… doğrudan düzenlenir
* Sürükle-bırak **yükleme** (parçalı, büyük dosya destekli), indirme
* Yeni dosya/klasör, yeniden adlandırma, kopyala/taşı, toplu silme
* **Zip / tar** oluşturma ve açma
* **İzin (chmod)** değiştirme, sahip/grup görüntüleme
* Dosya içi arama, resim/video/ses/PDF önizleme
* Türkçe arayüz, koyu tema

## Kurulum

```bash
unzip agfo-file-manager-1.0.0.zip && cd agfo-file-manager-1.0.0
AGFO_FM_ALLOW_IPS="sabit.ip.adresiniz" bash install.sh
bash ../agfo-ssh-menu-1.5.0/install.sh     # CyberPanel menüsüne "AGFO File Manager"
```

Kurulum sonunda adres, menü linki ve (ilk kurulumda) panel şifresi yazılır.
Yükseltmede şifre, jeton ve sertifika korunur.

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `AGFO_FM_PORT` | `8826` | Panel portu |
| `AGFO_FM_BIND` | `0.0.0.0` | Dinlenen adres |
| `AGFO_FM_PASSWORD` | üretilir | Panel şifresi |
| `AGFO_FM_DOMAIN` | CyberPanel sertifikasından | TLS alan adı |
| `AGFO_FM_CERT` / `AGFO_FM_KEY` | otomatik | Sertifikayı elle verin |
| `AGFO_FM_ALLOW_IPS` | boş (herkes) | İzinli IP'ler, virgülle |
| `AGFO_FM_PHP` | en yeni lsphp | Arka uç PHP sürümü, ör. `8.3` |
| `AGFO_FM_TIMEZONE` | `Europe/Istanbul` | Tarih gösterimi |
| `AGFO_FM_TLS` | `1` | `0` = düz HTTP (önerilmez) |
| `AGFO_FM_SKIP_FIREWALL` | `0` | `1` = firewalld'a dokunma |

## Mimari ve güvenlik

```
tarayıcı ──HTTPS:8826──> agfo-file-manager (Python, AGFO giriş katmanı)
                               │  gizli anahtar başlığı
                               ▼
                 agfo-file-manager-backend (lsphp -S 127.0.0.1:18096, root)
                               │
                          Tiny File Manager
```

* **Giriş:** PBKDF2 şifre, IP başına kaba kuvvet kilidi, HttpOnly + Secure +
  SameSite=Strict çerez, menüden jetonla şifresiz giriş (`?t=`), `allow_ips`.
* **Arka uç dışarıya kapalı:** yalnızca 127.0.0.1'i dinler ve her istekte ön
  panelin eklediği 64 karakterlik gizli anahtarı ister; anahtarsız istek 403
  alır. Kurulum bu denetimi yapar, başarısızsa servisleri durdurur.
* **Değiştirilen başlıklar ayıklanır:** dışarıdan gelen anahtar ve
  `X-Forwarded-*` başlıkları silinir.
* **CSRF:** her POST'ta Origin/Referer aynı köken olmalı; ayrıca Tiny File
  Manager'ın kendi jetonu.
* **CDN yok:** Bootstrap, jQuery, Ace, Dropzone vb. pakete gömülüdür; tarayıcı
  sunucunuz dışında hiçbir adrese bağlanmaz (CSP ile zorlanır).
* PHP hataları ekrana basılmaz, `logs/php-error.log` dosyasına yazılır.

> Bu panelden giren kişi sunucunun tamamını okuyup değiştirebilir. Paneli
> `AGFO_FM_ALLOW_IPS` ile sabit IP'nize kilitleyin ve menü linkini paylaşmayın.

## .htaccess hakkında

`.htaccess`, Apache'den gelen **dizin bazlı ayar dosyasıdır** (yönlendirme,
erişim engeli, PHP ayarı). CyberPanel'in web sunucusu OpenLiteSpeed bu dosyadan
**yalnızca rewrite (yönlendirme) kurallarını** uygular; `Deny from all`,
`Require all denied`, `php_value` satırlarını yok sayar. Ayrıca kurulacak bir
şey değildir — AGFO App Store gereken korumaları zaten rewrite kuralı olarak
(`RewriteRule ^config(/|$) - [F,L]` gibi) yazar ve sağlık testinde doğrular.
Bu dosya yöneticisiyle istediğiniz sitenin `.htaccess` dosyasını açıp
düzenleyebilirsiniz; değişiklik sonrası OpenLiteSpeed'i nazikçe yeniden
başlatmak gerekebilir (`/usr/local/lsws/bin/lswsctrl restart`).

## Servisler

```
systemctl status agfo-file-manager agfo-file-manager-backend
journalctl -u agfo-file-manager -f
```

## Kaldırma

```
bash /opt/agfo-file-manager/uninstall.sh            # ayarlar korunur
AGFO_FM_PURGE=1 bash /opt/agfo-file-manager/uninstall.sh   # tamamen sil
```

## Lisans

AGFO katmanı (`app/`, betikler) AGFO'ya aittir. `www/index.php`, Tiny File
Manager'ın (CCP Programmers, GPL-3.0) değiştirilmiş sürümüdür; lisans metni
`www/LICENSE-tinyfilemanager.txt`, kaynak commit `tools/TFM_UPSTREAM_COMMIT`.
Değişiklikler `tools/build_tfm.py` içinde: Türkçe varsayılanlar, `/` kök dizin
desteği, yerel varlıklar (CDN kaldırıldı).
