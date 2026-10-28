# AGFO SSH Terminal — CyberPanel menü girdisi

Bu küçük paket **yalnızca** CyberPanel kenar menüsüne "AGFO SSH Terminal"
girdisini ekler. Terminalin kendisini kurmaz (onu `agfo-ssh-terminal` paketi kurar).

## Nasıl çalışır

Menüdeki mevcut **AGFO Root Terminal** girdinizi şablonlarda arar ve onu çevreleyen
bloğu kopyalar; etiketini ve adresini değiştirip hemen altına ekler. Böylece yeni
girdi sizin kendi kalıbınızla aynı görünür — ikon, sınıflar, girinti dahil.

Üç kalıp sırayla denenir: `<li>…</li>` (alt menü barındırmıyorsa), `<a>…</a>`
(gerekirse kendi `<li>` sarmalıyla), son çare olarak etiketi içeren tek satır.
Hiçbiri tutmazsa dosyaya dokunmaz ve şablonun o bölümünü günlüğe basar — o çıktıyı
bana iletirseniz kesin yamayı ona göre hazırlarım.

Link adresi `/opt/agfo-ssh-terminal/config/config.json` içindeki `public_url`
alanından alınır; terminali `AGFO_SSH_DOMAIN` ile kurduysanız alan adı kullanılır
ve tarayıcı SSL uyarısı vermez.

Kopyalanan bloğun `title` ipucu, eski girdinin metnini taşımaması için yeni
etiketle değiştirilir (`AGFO_MENU_TITLE` ile kendiniz verebilirsiniz).

Değiştirdiği her dosyanın yanına `.agfo-bak-<tarih>` uzantılı yedeğini bırakır ve
eklediği bloğu ekrana yazar. Aynı paketi iki kez çalıştırmak girdiyi iki kez
eklemez: girdi zaten varsa **adresi günceller** — örneğin terminali sonradan
`AGFO_SSH_DOMAIN` ile kurup IP'den alan adına geçtiğinizde paketi tekrar
çalıştırmanız yeterlidir.

## Kullanım

Package Runner ile:

```
bash install.sh
```

Link adresi `/opt/agfo-ssh-terminal/config/config.json` ve sunucu IP'sinden
otomatik üretilir (`https://IP:PORT/?open=root`). Kendiniz vermek isterseniz:

```
AGFO_MENU_URL="https://panel.alanadiniz.com:8822/?open=root" bash install.sh
```

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `AGFO_MENU_URL` | otomatik | Menü linkinin adresi |
| `AGFO_MENU_LABEL` | `AGFO SSH Terminal` | Menüde görünecek ad |
| `AGFO_MENU_ANCHOR` | `AGFO Root Terminal` | Kalıbı kopyalanacak mevcut girdi |
| `AGFO_MENU_ROOT` | `/usr/local/CyberCP` | Şablonların bulunduğu dizin |
| `AGFO_MENU_TITLE` | etiketle aynı | Bağlantının `title` ipucu |
| `AGFO_MENU_SKIP_RESTART` | `0` | `1` = CyberPanel servisini yeniden başlatma |

Kurulumdan sonra CyberPanel sayfasını **Ctrl+F5** ile yenileyin.

Betik sırasıyla `lscpd`, `lswsctrl restart` (nazik, siteleri kesmez) ve `lsws`
dener. Hiçbiri yoksa dosya değişikliği yine yerindedir; çoğu kurulumda sayfayı
yenilemek yeterlidir, girdi görünmezse `systemctl restart lscpd` deneyin.

## Geri alma

```
bash restore.sh
```

En son yedeği geri yükler ve lscpd'yi yeniden başlatır.

## Kalıp bulunamazsa

Menü girdilerinizi şablon dosyası dışında bir yöntemle eklediyseniz betik hiçbir
dosyaya dokunmaz, durumu bildirip çıkar. O durumda girdiyi kendi eklediğiniz yere
elle koyun; kullanacağınız bağlantı şudur:

```html
<li class="treeview">
  <a target="_blank" rel="noopener" href="https://SUNUCU-IP:8822/?open=root">
    <i class="fa fa-terminal"></i> <span>AGFO SSH Terminal</span>
  </a>
</li>
```

`?open=root` parametresi, giriş yapıldıktan sonra root kabuğunun kendiliğinden
açılmasını sağlar; bunun için terminal paketinin 1.1.0 veya üstü olması gerekir.
