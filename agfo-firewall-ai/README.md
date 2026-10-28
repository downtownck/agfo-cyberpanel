# AGFO Firewall AI 1.0.0

Açık kaynak **CrowdSec** motorunun üzerine kurulan, yapay zekâ destekli güvenlik
duvarı yönetim paneli. Sunucudaki saldırı olaylarını okur, seçtiğiniz AI
sağlayıcısına yorumlatır ve **yalnızca öneri üretir** — hiçbir kural sizin
onayınız olmadan uygulanmaz.

## Mimari

```
   OpenLiteSpeed / sshd kayıtları
              ↓
         CrowdSec ajanı            (tespit: senaryolar, CVE'ler, kaba kuvvet)
              ↓            ↘
   firewall bouncer          AGFO Firewall AI paneli
   (iptables + ipset)        ├─ olay panosu, kararlar, denetim günlüğü
   gerçek engelleme          ├─ AI analizi → öneri kuyruğu
                             └─ Uygula / Reddet  → cscli
```

* Panelin **hiçbir Python bağımlılığı yoktur**; HTTP, TLS ve AI istemcisi
  standart kütüphane ile yazılmıştır.
* CrowdSec ile `cscli` üzerinden konuşur: sürüm farklarına dayanıklıdır,
  ayrı kimlik doğrulama gerektirmez.
* Panel root olarak çalışır (kural uygulayabilmesi için), dolayısıyla erişimi
  kısıtlamak önemlidir — aşağıdaki güvenlik bölümüne bakın.

## Kurulum

Package Runner ile:

```
bash install.sh
```

Alan adı ve sertifikayla (tarayıcı uyarısı çıkmaz):

```
AGFO_FW_DOMAIN=alanadiniz.com AGFO_FW_ALLOW_IPS="78.1.2.3" bash install.sh
```

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `AGFO_FW_PORT` | `8823` | Panel portu |
| `AGFO_FW_BIND` | `0.0.0.0` | `127.0.0.1` = yalnız yerel |
| `AGFO_FW_PASSWORD` | üretilir | Panel şifresi (yükseltmede korunur) |
| `AGFO_FW_DOMAIN` | — | Let's Encrypt sertifikası bu alan adından bulunur |
| `AGFO_FW_CERT` / `AGFO_FW_KEY` | — | Sertifikayı elle vermek için |
| `AGFO_FW_TLS` | `1` | `0` = düz HTTP |
| `AGFO_FW_ALLOW_IPS` | boş | Panele erişebilecek IP'ler (virgülle) |
| `AGFO_FW_INSTALL_CROWDSEC` | `1` | `0` = CrowdSec kurulumunu atla |
| `AGFO_FW_BOUNCER` | `auto` | `auto` \| `iptables` \| `nftables` \| `none` |
| `AGFO_FW_SKIP_FIREWALL` | `0` | `1` = güvenlik duvarına dokunma |

Aynı betik yükseltme için de kullanılır: şifre, API anahtarları, öneri geçmişi
ve sertifika korunur.

### Kurulum CrowdSec tarafında ne yapar

1. **Depo + paket:** resmî CrowdSec deposunu ekler, `crowdsec` paketini kurar.
   Paket kendi `cscli setup unattended` adımını çalıştırıp `sshd` ve `linux`
   kaynaklarını `setup.*.yaml` olarak tanımlar.
2. **Bouncer:** `crowdsec-firewall-bouncer-iptables` kurar. **nftables sürümü
   bilerek seçilmemiştir:** o sürüm kararlardaki CIDR maskesini düşürüyor, yani
   `1.2.3.0/24` yasağı yalnızca `1.2.3.0` adresini engelliyor. iptables sürümü
   ipset `nethash` kullandığı için aralıklar doğru çalışır. Ubuntu 24.04'te
   iptables zaten nftables arka ucuyla çalışır ve firewalld ile ayrı tablolarda
   durdukları için çakışmazlar (CrowdSec zinciri öncelik -10, firewalld +10).
3. **Log kaynakları** — kendi dosya adlarımızla, paketin ürettiklerinin üzerine
   yazmadan:
   * `/home/*/logs/*.access_log` → `apache2` ayrıştırıcısı. CyberPanel'in OLS
     log biçimi Apache "combined" olduğu için bu ayrıştırıcı doğru olanıdır;
     `litespeed` ayrıştırıcısı bayt alanı `-` olan satırları (304, HEAD)
     reddeder.
   * `/usr/local/lsws/logs/*`, `/usr/local/lsws/admin/logs/*`, site
     `*.error_log` dosyaları → `litespeed` ayrıştırıcısı (yönetim paneli giriş
     denemelerini yakalar).
   * Yeni site açtığınızda yeniden başlatma gerekmesin diye `discovery_poll`
     açıktır.
4. **Koleksiyonlar:** `crowdsecurity/linux`, `apache2`, `litespeed`,
   `wordpress`, `http-dos`. (Bunlar `base-http-scenarios`, `http-cve`, `sshd`
   ve `whitelist-good-actors` paketlerini zaten içeride getirir — Googlebot ve
   CDN'ler bu sonuncusu sayesinde engellenmez.)
5. **Doğrulama:** `crowdsec -t` ile yapılandırmayı sınar, CSF veya yanlış
   firewalld arka ucu görürse uyarır.

## İlk adımlar

1. Panele girin, **Sağlayıcılar** sekmesinden bir API anahtarı ekleyin ve
   **Test** düğmesiyle doğrulayın.
2. **AI Analizi** sekmesinde pencereyi seçip **Analiz et** deyin.
3. Gelen önerileri tek tek **Uygula** veya **Reddet**.

### Desteklenen sağlayıcılar

OpenAI, OpenRouter, Groq, DeepInfra, Together.ai, Claude, DeepSeek, NVIDIA NIM,
MiniMax, Gemini. Uç noktalar AGFO AI Manager'daki kayıtla birebir aynıdır;
Claude ve Gemini'nin kendi istek biçimleri ayrıca ele alınır. Model alanını boş
bırakırsanız sağlayıcının varsayılanı kullanılır.

Anahtarlar `config/providers.json` içinde 0600 izniyle tutulur ve panele bir
daha geri gönderilmez (yalnız son 4 hane gösterilir).

## Güvenlik

**AI asla doğrudan kural uygulamaz.** Analiz çıktısı bir öneri kuyruğuna düşer;
uygulama anında şu süzgeçlerden geçer:

* **Korumalı liste** — `127.0.0.1`, `::1`, sunucunun kendi adresleri, oturum
  açtığınız IP ve Ayarlar'da eklediğiniz adresler hiçbir koşulda engellenemez.
* **Korunan ağlar** — RFC1918 özel ağlar, loopback, link-local ve CGNAT
  (`100.64.0.0/10`) aralıkları engellenemez.
* **Aralık sınırı** — 65536 adresten geniş blok reddedilir.
* **Süre sınırı** — varsayılan üst sınır 720 saat.
* **Komut enjeksiyonu** — IP, kullanıcı adı, port ve seçenekler düzenli ifadeyle
  doğrulanır; `cscli` kabuk üzerinden değil argüman listesiyle çağrılır.
* **Denetim günlüğü** — her giriş, öneri, uygulama ve elle karar
  `config/audit.log` dosyasına yazılır ve panelde görünür.

Panel erişimi için: PBKDF2-SHA256 şifre, IP başına kaba kuvvet kilidi,
HttpOnly + SameSite çerez, CSRF başlığı, Origin denetimi, varsayılan HTTPS.
`AGFO_FW_ALLOW_IPS` ile sabit IP'nize kilitlemeniz önerilir.

## CyberPanel menüsüne ekleme

`agfo-ssh-menu` paketindeki yöntemle, ya da elle:

```html
<a href="https://alanadiniz.com:8823/" target="_blank" rel="noopener">AGFO Firewall AI</a>
```

## Sorun giderme

| Belirti | Bakılacak yer |
|---|---|
| Panel açılmıyor | `journalctl -u agfo-firewall-ai -n 50` |
| "CrowdSec kurulu değil" | `systemctl status crowdsec`, `cscli version` |
| Bouncer yok uyarısı | `systemctl status crowdsec-firewall-bouncer` — kurulu değilse CrowdSec tespit eder ama engellemez |
| Hiç uyarı görünmüyor | `cscli metrics show acquisition` — satır okunuyor mu, log yolları doğru mu |
| Çok sayıda "unparsed" satır | Normaldir (OLS hata kayıtları apache2 grok'una uymaz); CPU sorunu yoksa görmezden gelin |
| Aynı dosya iki kez okunuyor | `acquis.d` altında çakışan tanım vardır; CPU'yu boşa yakar, birini silin |
| AI hatası 401/402 | Anahtar geçersiz veya bakiye bitmiş; Sağlayıcılar sekmesinde Test |
| AI "JSON çözümlenemedi" | Model şemaya uymadı; daha güçlü bir model seçin |
| firewalld reload sonrası engeller düştü | `systemctl restart crowdsec-firewall-bouncer` |

Faydalı komutlar:

```
cscli metrics                 # ne kadar log okundu, hangi senaryo kaç kez tetiklendi
cscli decisions list          # etkin engeller
cscli alerts list --since 1h  # son uyarılar
crowdsec -t                   # yapılandırma sınaması
```

## Kaldırma

```
bash /opt/agfo-firewall-ai/uninstall.sh                      # panel gider, CrowdSec ve ayarlar kalır
AGFO_FW_PURGE=1 bash /opt/agfo-firewall-ai/uninstall.sh      # API anahtarları dahil her şey
AGFO_FW_PURGE_CROWDSEC=1 bash /opt/agfo-firewall-ai/uninstall.sh  # CrowdSec'i de kaldır
```

## Paket içeriği

```
install.sh / uninstall.sh       kurulum ve kaldırma (root, tty gerektirmez)
app/server.py                   HTTP + TLS + oturum + API
app/crowdsec.py                 cscli sarmalayıcı ve güvenlik süzgeci
app/providers.py                10 AI sağlayıcısı
app/analyst.py                  istem üretimi ve öneri ayrıştırma
app/store.py                    yapılandırma, anahtar, öneri, denetim deposu
app/certwatch.sh                sertifika yenilenince servisi tazeler
app/static/                     arayüz (bağımlılıksız)
systemd/                        servis ve sertifika denetimi birimleri
config/config.example.json      örnek yapılandırma
```
