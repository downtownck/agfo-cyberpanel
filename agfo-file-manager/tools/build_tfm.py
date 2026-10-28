#!/usr/bin/env python3
"""Tiny File Manager'i AGFO File Manager icin uyarlar (tekrarlanabilir).

Kullanim: build_tfm.py <tinyfilemanager.php> <translation.json> <hedef_www_dizini>

Yamalar (her biri dogrulanir; kaynak degistiyse betik durur):
  1. Varsayilan ayarlar: Turkce, gizli dosyalar gorunur, koyu tema.
  2. Uygulama basligi: "AGFO File Manager"; <title> icindeki kacissiz
     ?view=/?edit= degeri fm_enc ile kacirilir (upstream XSS duzeltmesi).
  3. Kok dizin "/" destegi: TFM sondaki "/"'i kirpip bos yol yapiyordu.
  4. Harici CDN kaynaklari -> /fm-assets/ altindaki yerel kopyalar
     (root yetkili bir aracta ucuncu taraf JS yuklenmez).
"""
import json, os, re, sys

src, translation, out = sys.argv[1:4]
text = open(src, encoding="utf-8").read()

def sub(old, new, count=1):
    global text
    if old not in text:
        sys.exit("YAMA UYGULANAMADI (kaynak degismis): %r" % old[:80])
    text = text.replace(old, new, count)

# 1) varsayilanlar
m = re.search(r"^\$CONFIG = '(\{.*?\})';", text, re.M)
if not m:
    sys.exit("YAMA UYGULANAMADI: $CONFIG satiri")
cfg = json.loads(m.group(1))
cfg.update({"lang": "tr", "show_hidden": True, "theme": "dark"})
text = text[:m.start(1)] + json.dumps(cfg, separators=(",", ":")) + text[m.end(1):]

# 2) baslik
sub("define('APP_TITLE', 'Tiny File Manager');", "define('APP_TITLE', 'AGFO File Manager');")

# 3) kok dizin "/"
sub("$root_path = rtrim($root_path, '\\\\/');\n$root_path = str_replace('\\\\', '/', $root_path);",
    "$root_path = rtrim($root_path, '\\\\/');\n$root_path = str_replace('\\\\', '/', $root_path);\n"
    "if ($root_path === '') { $root_path = '/'; } // AGFO: kok dizin destegi")

# 2b) baslik etiketi: upstream ?view=/?edit= degerini kacissiz basiyordu (yansitilan XSS).
sub("""<?php echo (isset($_GET['view']) ? $_GET['view'] : ((isset($_GET['edit'])) ? $_GET['edit'] : "H3K")); ?></title>""",
    """<?php echo fm_enc(isset($_GET['view']) ? $_GET['view'] : (isset($_GET['edit']) ? $_GET['edit'] : 'AGFO')); ?></title>""")

# 4) CDN -> yerel
A = "/fm-assets"
local = {
    "css-bootstrap": '<link href="%s/bootstrap/css/bootstrap.min.css" rel="stylesheet">' % A,
    "css-dropzone": '<link href="%s/dropzone/dropzone.min.css" rel="stylesheet">' % A,
    "css-font-awesome": '<link rel="stylesheet" href="%s/font-awesome/css/font-awesome.min.css">' % A,
    "css-highlightjs": "<link rel=\"stylesheet\" href=\"%s/highlightjs/styles/' . $highlightjs_style . '.min.css\">" % A,
    "js-ace": '<script src="%s/ace/ace.js"></script>' % A,
    "js-bootstrap": '<script src="%s/bootstrap/js/bootstrap.bundle.min.js"></script>' % A,
    "js-dropzone": '<script src="%s/dropzone/dropzone.min.js"></script>' % A,
    "js-jquery": '<script src="%s/jquery/jquery.min.js"></script>' % A,
    "js-jquery-datatables": '<script src="%s/datatables/jquery.dataTables.min.js" defer></script>' % A,
    "js-highlightjs": '<script src="%s/highlightjs/highlight.min.js"></script>' % A,
    "pre-jsdelivr": "",
    "pre-cloudflare": "",
}
start = text.index("$external = array(")
end = text.index(");", start) + 2
block = "$external = array(\n" + ",\n".join(
    "    %s => %s" % (json.dumps(k), "'" + v.replace("'", "\\'") + "'" if "' . $highlightjs_style" not in v else "'" + v + "'")
    for k, v in local.items()) + "\n);"
# json.dumps cift tirnak uretir; PHP icin anahtarlari tek tirnaga cevir
block = re.sub(r'^    "([a-z-]+)" =>', r"    '\1' =>", block, flags=re.M)
text = text[:start] + block + text[end:]
left = re.findall(r"https://(?:cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com|code\.jquery\.com|cdn\.datatables\.net)[^\"' ]*", text)
if left:
    sys.exit("YAMA EKSIK: hala harici kaynak var: %s" % left[:3])

os.makedirs(out, exist_ok=True)
open(os.path.join(out, "index.php"), "w", encoding="utf-8").write(text)
open(os.path.join(out, "translation.json"), "w", encoding="utf-8").write(open(translation, encoding="utf-8").read())
print("tamam: %s (%d bayt)" % (os.path.join(out, "index.php"), len(text)))
