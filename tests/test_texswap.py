"""Reconocer botones en texturas volcadas por la GPU y preparar las parejas.   python tests/test_texswap.py"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-texswap-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen  # noqa: E402

from reforge import glyphs, texswap, xpr  # noqa: E402

app = QGuiApplication.instance() or QGuiApplication([])
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


def glyph(size, color, letter, outline=True):
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(*color))
    p.setPen(QPen(QColor(20, 20, 20), 2) if outline else Qt.PenStyle.NoPen)
    p.drawEllipse(QRectF(2, 2, size - 4, size - 4))
    if letter:
        f = QFont()
        f.setBold(True)
        f.setPixelSize(int(size * 0.6))
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(0, 0, size, size), int(Qt.AlignmentFlag.AlignCenter), letter)
    p.end()
    return glyphs.from_qimage(img)


def dump(folder, key, rgba, w, h, fmt=xpr.FMT_DXT5, pitch=128):
    tex = xpr.Texture("", fmt, 1 if fmt != xpr.FMT_8888 else 2, w, h, pitch, True, 0)
    blob = bytearray(tex.layout()[6])
    xpr.encode_into(blob, tex, rgba)
    with open(os.path.join(folder, key + ".rftx"), "wb") as f:
        f.write(f"RFTX1 {fmt} {w} {h} {pitch} 1 {tex.endian} {len(blob)} 0\n".encode() + bytes(blob))
    return bytes(blob)


print("Reconocer por el aspecto")
a = glyph(48, (60, 170, 40), "A")
check(texswap.analyze(a, 48, 48) == ("button", "cross"), "círculo verde con «A» → ✕")
check(texswap.analyze(glyph(48, (210, 40, 40), "B"), 48, 48) == ("button", "circle"), "rojo con «B» → ○")
check(texswap.analyze(glyph(48, (50, 90, 210), "X"), 48, 48) == ("button", "square"), "azul con «X» → □")
check(texswap.analyze(glyph(48, (230, 190, 20), "Y"), 48, 48) == ("button", "triangle"), "amarillo con «Y» → △")
check(texswap.analyze(glyph(48, (230, 190, 20), "", outline=False), 48, 48) is None,
      "una moneda amarilla sin letra no es un botón")
check(texswap.analyze(glyph(48, (60, 170, 40), "A"), 48, 48, name="BTN_LB") == ("button", "L1"),
      "con nombre del .xpr manda el nombre")
sheet = QImage(128, 64, QImage.Format.Format_ARGB32_Premultiplied)
sheet.fill(Qt.GlobalColor.transparent)
p = QPainter(sheet)
for i, (col, l) in enumerate((((60, 170, 40), "A"), ((210, 40, 40), "B"), ((50, 90, 210), "X"))):
    p.drawImage(i * 40, 8, glyphs.to_qimage(glyph(36, col, l), 36, 36))
p.end()
sh = glyphs.from_qimage(sheet)
plan = texswap.analyze(sh, 128, 64)
check(plan and plan[0] == "blobs" and sorted(k for _b, k in plan[1]) == ["circle", "cross", "square"],
      "hoja con varios iconos: cada uno a su sitio")

print("Volcados de la GPU → parejas")
exe_dir = os.path.join(TMP, "juego", "build")
root = os.path.join(TMP, "juego")
os.makedirs(os.path.join(root, "assets"))
os.makedirs(exe_dir)
exe = os.path.join(exe_dir, "juego.exe")
open(exe, "wb").write(b"MZ")
d = texswap.tex_dir(exe)
os.makedirs(os.path.join(d, "dump"))
orig = dump(os.path.join(d, "dump"), "00000000000000aa", a, 48, 48)
dump(os.path.join(d, "dump"), "00000000000000bb", glyph(48, (230, 190, 20), "", outline=False), 48, 48)
dump(os.path.join(d, "dump"), "00000000000000cc", sh, 128, 64)
n = texswap.prepare(exe, root, "playstation")
check(n == 2, "dos texturas reconocidas (icono y hoja), la moneda no")
idx = open(os.path.join(d, "index.txt")).read().split()
check(idx == ["pares/00000000000000aa.x.bin", "pares/00000000000000aa.p.bin",
              "pares/00000000000000cc.x.bin", "pares/00000000000000cc.p.bin"], "index.txt con las parejas")
x = open(os.path.join(d, "pares", "00000000000000aa.x.bin"), "rb").read()
p_ = open(os.path.join(d, "pares", "00000000000000aa.p.bin"), "rb").read()
check(x == orig and len(p_) == len(x) and p_ != x, "original exacto y versión PlayStation del mismo tamaño")
check(open(os.path.join(d, "style.txt")).read().strip() == "playstation" and os.path.isfile(os.path.join(d, "dump.on")),
      "estilo y aprendizaje activados")
check(texswap.prepare(exe, root, "xbox") == 0 and open(os.path.join(d, "style.txt")).read().strip() == "xbox",
      "cambiar a Xbox solo cambia style.txt (sin reprocesar)")
check([k for k, _v in texswap.recognized(exe)] == ["00000000000000aa", "00000000000000cc"], "lista de reconocidas")

print("Menú Guía ↔ opciones")
check(texswap.menu_style(exe) == "", "sin elección en el juego")
texswap.set_menu_style(exe, "playstation")
check(texswap.menu_style(exe) == "playstation", "elección del juego leída")
texswap.set_menu_style(exe, "")
check(texswap.menu_style(exe) == "", "volver a automático")
check(texswap.plugin_supports(exe) is False, "un DLL sin el parche no se usa")
print(f"\nTodas las pruebas pasaron ({ok}).")
