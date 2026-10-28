# AGFO CyberPanel Araçları

CyberPanel / OpenLiteSpeed sunucularında çalışan AGFO araçları. Hepsi **AGFO
Package Runner** ile kurulur: paketi yükleyin, `bash install.sh` çalıştırın.

Ortak tasarım kuralları:

* **Harici bağımlılık yok.** Hepsi yalnızca Python standart kütüphanesini
  kullanır — `pip install` yok, sanal ortam yok, derleme yok. Sunucudaki
  Python 3.8+ yeterlidir.
* **Kurulum tty istemez**, soru sormaz; tüm ayarlar ortam değişkeniyle verilir.
* **Yükseltmede ayarlar korunur:** panel şifresi, API anahtarları, kayıtlı
  oturumlar ve sertifikalar aynı betikle yeniden kurulumda yerinde kalır.
* Her araç systemd servisi olarak çalışır, kendi kaldırma betiğiyle gelir.

| Araç | Sürüm | Ne yapar |
|---|---|---|
| [agfo-ssh-terminal](agfo-ssh-terminal/) | 1.2.0 | Tarayıcıdan PuTTY tarzı SSH terminali; root kabuğu, sekmeler, kayıtlı oturumlar |
| [agfo-ssh-menu](agfo-ssh-menu/) | 1.2.0 | SSH Terminal bağlantısını CyberPanel kenar menüsüne ekler |
| [agfo-firewall-ai](agfo-firewall-ai/) | 1.0.0 | CrowdSec üzerine AI destekli güvenlik duvarı paneli; öneri üretir, siz onaylarsınız |

## Hızlı kurulum

```bash
# Web terminali (8822)
AGFO_SSH_DOMAIN=alanadiniz.com bash agfo-ssh-terminal/install.sh

# CyberPanel menüsüne bağlantı ekle
bash agfo-ssh-menu/install.sh

# Güvenlik duvarı paneli (8823) — CrowdSec'i de kurar
AGFO_FW_DOMAIN=alanadiniz.com AGFO_FW_ALLOW_IPS="sabit.ip.adresiniz" bash agfo-firewall-ai/install.sh
```

Her aracın kendi klasöründeki `README.md` dosyası tüm ortam değişkenlerini,
güvenlik notlarını ve sorun giderme adımlarını içerir.

## Güvenlik notu

`agfo-ssh-terminal` ve `agfo-firewall-ai` sunucuda **root yetkisiyle** çalışır
ve panellerine giren kişi sunucuya hâkim olur. İkisinde de:

* PBKDF2-SHA256 ile saklanan panel şifresi, IP başına kaba kuvvet kilidi
* HttpOnly + SameSite çerez, CSRF başlığı, Origin denetimi, varsayılan HTTPS
* `allow_ips` ile IP kısıtlaması (sabit IP'nizle kullanmanız önerilir)

Kurulumda `AGFO_*_DOMAIN` verirseniz CyberPanel'in mevcut Let's Encrypt
sertifikası bulunur ve tarayıcı uyarısı çıkmaz; sertifika yenilendiğinde
servisi tazeleyen günlük bir denetim de kurulur.

## Sürüm takibi

Sürüm numaraları her aracın `VERSION` dosyasında ve `install.sh` başındaki
`APP_VERSION` değişkenindedir. Sunucuda kurulu sürümü görmek için:

```bash
cat /opt/agfo-ssh-terminal/VERSION
cat /opt/agfo-firewall-ai/VERSION
```

Yükseltmek için ilgili klasörü indirip `install.sh`'i yeniden çalıştırmak
yeterlidir.

### Runner'a yüklenecek ZIP'ler

```bash
bash tools/make-packages.sh    # dist/agfo-<arac>-<surum>.zip üretir
```

Her ZIP'in kökünde `install.sh` bulunur, yani doğrudan Package Runner'a
yüklenebilir.

Bir sürüm etiketi gönderildiğinde bu paketler GitHub Releases'e otomatik
eklenir:

```bash
git tag v2026.10.28 && git push origin v2026.10.28
```

Böylece sunucuya kurulan sürümü Releases sayfasındakiyle karşılaştırarak
güncelliği takip edebilirsiniz.
