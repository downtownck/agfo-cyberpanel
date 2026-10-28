# AGFO SSH Terminal 1.3.2

CyberPanel sunucunuzda çalışan, tarayıcıdan kullanılan **PuTTY tarzı SSH terminali**.
Sunucuya **root erişimi** verir: hem sunucunun kendi root kabuğunu açar, hem de
oradan başka sunuculara SSH ile bağlanır.

## Neden bu tasarım

* **Hiçbir Python bağımlılığı yok.** HTTP, WebSocket, TLS ve PTY katmanlarının
  tamamı standart kütüphane ile yazıldı. `pip install` yok, sanal ortam yok,
  derleme yok. Sunucunun Python'u 3.6 ve üzeri olması yeterli.
* **SSH işini OpenSSH yapar.** Bağlantı, gerçek bir PTY içinde sistemdeki `ssh`
  ikilisi çağrılarak kurulur. Böylece host key doğrulaması, `~/.ssh/config`,
  anahtar ve `ssh-agent` desteği, `ProxyJump`, şifre istemi — hepsi OpenSSH'in
  kendi davranışıyla çalışır. Şifre sorulduğunda istem doğrudan terminalde çıkar,
  tıpkı PuTTY'deki gibi; şifre hiçbir yerde saklanmaz.
* **İnternet gerektirmez.** xterm.js ve eklentileri paketin içinde gelir; CDN'e
  çıkış yoktur.

## Kurulum (AGFO Package Runner)

ZIP'i Package Runner'a yükleyip çalıştırın. Betik tty istemez, soru sormaz.

```
bash install.sh
```

Varsayılanlar: `0.0.0.0:8822`, HTTPS (kendinden imzalı sertifika), rastgele
üretilmiş panel şifresi. Şifre kurulum çıktısında **bir kez** yazdırılır.

### Ortam değişkenleri

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `AGFO_SSH_PORT` | `8822` | Dinlenecek port |
| `AGFO_SSH_BIND` | `0.0.0.0` | `127.0.0.1` verilirse yalnız yerelden erişilir |
| `AGFO_SSH_PASSWORD` | (rastgele) | Panel şifresi |
| `AGFO_SSH_TLS` | `1` | `0` = düz HTTP (yalnızca ters vekil arkasında kullanın) |
| `AGFO_SSH_DOMAIN` | — | Panele bu alan adıyla erişilir; sertifikası otomatik bulunur |
| `AGFO_SSH_CERT` / `AGFO_SSH_KEY` | — | Sertifikayı elle vermek isterseniz |
| `AGFO_SSH_ALLOW_IPS` | boş | `78.1.2.3,88.99.*` — yalnız bu IP'lere açık |
| `AGFO_SSH_SESSION_LOG` | `0` | `1` = oturum çıktıları sunucuya kaydedilir |
| `AGFO_SSH_SKIP_FIREWALL` | `0` | `1` = güvenlik duvarına dokunma |
| `AGFO_SSH_FRAME_ANCESTORS` | boş | Paneli iframe içinde gösterebilecek adresler (varsayılan: hiçbiri) |
| `AGFO_SSH_COOKIE_SAMESITE` | `Strict` | Farklı alan adı altından çerçeveleme için `None` (TLS şart) |

### Alan adıyla kurulum (SSL uyarısından kurtulmak için)

```
AGFO_SSH_DOMAIN=agfocert.net bash install.sh
```

Betik şunları yapar:

1. Alan adının **bu sunucuya** çözümlenip çözümlenmediğini denetler, farklıysa uyarır.
2. CyberPanel'in mevcut Let's Encrypt sertifikasını arar —
   `/etc/letsencrypt/live/<alan>/`, `…/<alan>-0001/`,
   `/usr/local/lsws/conf/vhosts/<alan>/`, `…/www.<alan>/` sırasıyla.
3. Bulursa doğrudan onu kullanır; panele `https://agfocert.net:8822/` adresinden
   girersiniz ve tarayıcı uyarı vermez.
4. Sertifika yenilendiğinde servisin eski sertifikayla kalmaması için günlük bir
   denetim (`agfo-ssh-terminal-certwatch.timer`) kurar: sertifika dosyası
   değiştiğinde servisi kendiliğinden yeniden başlatır.

Alan adı için henüz sertifika çıkarılmadıysa kendinden imzalıyla devam eder;
CyberPanel > SSL > Manage SSL ile sertifikayı çıkarıp paketi tekrar çalıştırın.

Örnek — sadece ofis IP'sine açık, alan adıyla:

```
AGFO_SSH_DOMAIN=agfocert.net AGFO_SSH_ALLOW_IPS="78.1.2.3" bash install.sh
```

Aynı betik yükseltme için de kullanılır: mevcut `config.json`, kayıtlı oturumlar,
anahtarlar ve panel şifresi korunur, yalnız uygulama dosyaları yenilenir.

## Şifresiz giriş (menü linki)

Kurulumda panel şifresinden bağımsız bir **giriş jetonu** üretilir. Menü linki
bu jetonu taşır (`?t=…`), tıklayınca şifre sorulmadan içeri girersiniz. Jeton
doğrulanır doğrulanmaz tarayıcı temiz adrese yönlendirilir, böylece jeton adres
çubuğunda ve geçmişte kalmaz; diğer parametreler (`open=root`) korunur.

Jeton da bir anahtardır: linki görebilen CyberPanel yöneticisi sunucuya root
erişir — zaten CyberPanel yöneticisi olduğu için bu kabul edilebilir bir sınır.
Yine de `AGFO_SSH_ALLOW_IPS` ile sabit IP'nize kilitlemenizi öneririm.
Kapatmak için `config.json` içinde `auth.token_login` değerini `false` yapın;
jetonu yenilemek için `auth.login_token` alanını silip kurulumu tekrarlayın.
Hatalı jeton denemeleri de şifre gibi IP başına kilitlenir.

## Güvenlik — önce bunu okuyun

Bu panele giren kişi sunucuda **root**'tur. Sunucu `root` kullanıcısı ile çalışır
ve alt süreç/PTY açabilmesi için systemd sandbox'ı bilerek uygulanmaz.

Uygulanan korumalar:

* PBKDF2-SHA256 (240.000 tur) ile saklanan panel şifresi, IP başına kaba kuvvet
  kilidi (varsayılan 6 hatada 15 dakika).
* HttpOnly + SameSite=Strict + Secure çerez, POST isteklerinde CSRF başlığı,
  WebSocket ve API'de Origin denetimi.
* Varsayılan HTTPS; HSTS, CSP, `X-Content-Type-Options`, `X-Frame-Options`.
* `ssh` komut satırı doğrudan birleştirilmez: host, kullanıcı, port, anahtar ve
  ProxyJump alanları düzenli ifadeyle doğrulanır; ek seçeneklerde yalnız
  `-o Anahtar=Deger` ve `-C -4 -6 -A -q` kabul edilir. `ProxyCommand`,
  `LocalCommand`, `PermitLocalCommand` ve `Include` kalıcı olarak engellidir,
  `PermitLocalCommand=no` her bağlantıda zorlanır. Kabuk aracılığıyla çalıştırma
  (`shell=True`) hiçbir yerde kullanılmaz.
* Özel anahtarlar `config/keys/` altında 0600 izniyle, `config.json` 0600 ile tutulur.

Önerilen sıkılaştırma:

1. `AGFO_SSH_ALLOW_IPS` ile sabit IP'nize kilitleyin.
2. Gerçek bir sertifika kullanın (tarayıcı uyarısını kaldırır, MITM'i zorlaştırır).
3. Panele çıkıştan sonra şifreyi **Ayarlar** ekranından kendi belirlediğiniz
   güçlü bir değerle değiştirin.
4. Daha da kapalı isterseniz: `AGFO_SSH_BIND=127.0.0.1` ile kurun ve yalnız
   SSH tüneliyle kullanın: `ssh -L 8822:127.0.0.1:8822 root@sunucu`

## Kullanım

* **Root kabuğu** — sunucunun kendisinde doğrudan root kabuğu (şifre sorulmaz,
  servis zaten root çalışır). Kısayol: `Ctrl+Shift+L`
* **root@localhost** — aynı sunucuya SSH ile bağlanır (sshd ayarlarını test etmek için).
* **Bağlantı formu** — host, port, kullanıcı, özel anahtar, ProxyJump, ek `ssh`
  seçenekleri ve bağlantıda çalışacak uzak komut. Formu bir **oturum adı** ile
  kaydedebilirsiniz; kayıtlı oturuma çift tıklayınca bağlanır.
* **Sekmeler** — en fazla 12 eşzamanlı terminal.

Kısayollar: `Ctrl+Shift+C/V` kopyala-yapıştır, `Shift+Insert` yapıştır,
`Ctrl+Insert` kopyala, orta tık yapıştır, `Ctrl+Shift+F` ara,
`Ctrl+Shift+W` sekmeyi kapat, `Ctrl+Shift+L` root kabuğu, `Alt+1…9` sekme değiştir.

Temalar: AGFO Koyu, PuTTY Klasik, Solarized Koyu, Yeşil Fosfor, Aydınlık.
Tema ve yazı boyutu tarayıcıda saklanır.

Alt çubuktaki ok ile o sekmenin tüm çıktısını `.log` olarak indirebilirsiniz.
`AGFO_SSH_SESSION_LOG=1` ile kurulduysa oturumlar sunucuda da
`/var/log/agfo-ssh-terminal/sessions/` altında tutulur.

## CyberPanel menüsüne ekleme

Panel bağımsız bir servistir; CyberPanel'e bir şey kurmaz. "AGFO TOOLS" menünüze
yeni sekmede açılan bir bağlantı eklemek yeterlidir:

```html
<a href="https://agfocert.net:8822/?open=root" target="_blank" rel="noopener">AGFO SSH Terminal</a>
```

Bu girdiyi sizin yerinize ekleyen ayrı bir paket var: `agfo-ssh-menu`. Adresi
`config.json` içindeki `public_url` alanından kendisi alır.

Adresteki `?open=` parametresi, giriş yapıldıktan sonra hangi terminalin kendiliğinden
açılacağını belirler — menüden tek tıkla doğrudan çalışan bir kabuğa düşersiniz:

| Parametre | Sonuç |
|---|---|
| `?open=root` | Sunucunun yerel root kabuğu (şifre sorulmaz) |
| `?open=localhost` | `root@127.0.0.1` SSH oturumu |
| `?open=Hetzner%20root` | Bu adla kaydettiğiniz oturum |
| `?embed=1` | Marka satırını gizleyen dar mod (çerçeve içi kullanım için) |

Parametreler birleştirilebilir: `?embed=1&open=root`

**Not:** Linkin `127.0.0.1` değil sunucunun adresini göstermesi gerekir; `127.0.0.1`
tarayıcıda sizin kendi makineniz demektir.

### İsteğe bağlı: CyberPanel sayfasının içine gömme

Panel varsayılan olarak çerçevelenmeye kapalıdır. CyberPanel sayfasının içinde bir
iframe olarak göstermek isterseniz, CyberPanel adresini açıkça tanıtın:

```
AGFO_SSH_FRAME_ANCESTORS="https://SUNUCU-IP:8090" bash install.sh
```

```html
<iframe src="https://SUNUCU-IP:8822/?embed=1&open=root"
        allow="clipboard-read; clipboard-write"
        style="width:100%;height:80vh;border:0"></iframe>
```

İki uyarı: kendinden imzalı sertifika kullanıyorsanız tarayıcı uyarıyı iframe içinde
gösteremez — paneli önce bir kez normal sekmede açıp sertifikayı kabul etmeniz gerekir.
CyberPanel başka bir **alan adı** altındaysa (aynı IP'nin başka portu değil), ek olarak
`AGFO_SSH_COOKIE_SAMESITE=None` gerekir.

Alan adı üzerinden sunmak isterseniz iki yol var:

1. **Doğrudan (önerilen):** `AGFO_SSH_CERT`/`AGFO_SSH_KEY` ile Let's Encrypt
   sertifikasını uygulamaya verin, porta alan adıyla erişin.
2. **Ters vekil:** OpenLiteSpeed vhost'unda `/` için proxy, ayrıca **Web Socket
   Proxy** bölümünde `URI = /ws`, `Address = 127.0.0.1:8822` tanımlayın. WebSocket
   tanımı olmadan terminal açılmaz.

## Yapılandırma

Kurulumdan sonra tüm ayarlar `/opt/agfo-ssh-terminal/config/config.json`
içindedir (`config/config.example.json` örnek olarak paketle birlikte gelir).
Değişiklikten sonra:

```
systemctl restart agfo-ssh-terminal
```

Dikkate değer alanlar: `limits.idle_timeout` (saniye, 0 = kapalı),
`limits.max_sessions`, `auth.session_ttl`, `defaults.local_shell`,
`defaults.host_key_policy`, `allow_ips`, `frame_ancestors`, `cookie_samesite`.

## Sorun giderme

| Belirti | Bakılacak yer |
|---|---|
| Servis açılmıyor | `journalctl -u agfo-ssh-terminal -n 50` |
| "ssh istemcisi yok" uyarısı | `dnf -y install openssh-clients` (Debian/Ubuntu: `apt -y install openssh-client`) |
| Sayfa açılıyor, terminal açılmıyor | Ters vekil kullanıyorsanız WebSocket (`/ws`) tanımı eksiktir |
| Porta erişilemiyor | `firewall-cmd --list-ports`; CSF kullanıyorsanız `TCP_IN` listesine portu ekleyip `csf -r` |
| Şifre unutuldu | `AGFO_SSH_PASSWORD=yeniSifre bash install.sh` ile yeniden çalıştırın |
| Tarayıcı sertifika uyarısı | IP ile giriyorsunuz demektir; `AGFO_SSH_DOMAIN=alanadiniz` ile kurup alan adıyla girin |
| Sertifika yenilendi, uyarı döndü | `systemctl status agfo-ssh-terminal-certwatch.timer`; elle: `systemctl restart agfo-ssh-terminal` |
| Menü linki "bağlanmayı reddetti" | Adres `127.0.0.1` değil sunucunun IP/alan adı olmalı, port 8822 |
| iframe içinde boş/engelli | `frame_ancestors` tanımlı değil, ya da sertifika henüz kabul edilmemiş |

Servis komutları:

```
systemctl status  agfo-ssh-terminal
systemctl restart agfo-ssh-terminal
journalctl -u agfo-ssh-terminal -f
```

## Kaldırma

```
bash /opt/agfo-ssh-terminal/uninstall.sh                 # ayarlar kalır
AGFO_SSH_PURGE=1 bash /opt/agfo-ssh-terminal/uninstall.sh  # her şey silinir
```

## Paket içeriği

```
install.sh                      kurulum / yükseltme (root, tty gerektirmez)
uninstall.sh                    kaldırma
VERSION                         sürüm
app/server.py                   HTTP + WebSocket + PTY sunucusu (tek dosya, stdlib)
app/static/index.html|app.css|app.js   arayüz
app/static/vendor/              xterm.js 5.5.0 + fit/web-links/search eklentileri
app/certwatch.sh                sertifika yenilenince servisi tazeler
systemd/agfo-ssh-terminal.service      servis birimi şablonu
systemd/*-certwatch.{service,timer}    günlük sertifika denetimi
config/config.example.json      örnek yapılandırma
```
