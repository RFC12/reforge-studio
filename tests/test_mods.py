"""Packs, texturas XPR2 e iconos de PlayStation.   python tests/test_mods.py"""
import os
import shutil
import struct
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-mods-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402

from reforge import controller, game, glyphs, mods, xpr  # noqa: E402
from reforge.game_options import GameOptions  # noqa: E402

app = QGuiApplication.instance() or QGuiApplication([])
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


def circle_tex(w, h, color):
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(*color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QRectF(2, 2, w - 4, h - 4))
    p.end()
    return glyphs.from_qimage(img)


def diagram(size=128):
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(235, 235, 235))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    for (x, y), col in (((90, 40), (220, 160, 20)), ((76, 54), (60, 90, 200)), ((104, 54), (210, 40, 40)),
                        ((90, 68), (60, 170, 40))):
        p.setBrush(QColor(*col))
        p.drawEllipse(QRectF(x - 6, y - 6, 12, 12))
    p.end()
    return glyphs.from_qimage(img)


def make_xpr(textures):
    """XPR2 con texturas [(nombre, formato, ancho, alto, rgba)], en mosaico."""
    n = len(textures)
    names = b""
    name_offs = []
    for t in textures:
        name_offs.append(16 * n + 4 + 52 * n + len(names))
        names += t[0].encode() + b"\0"
    hsize = (16 * n + 4 + 52 * n + len(names) + 0x7FF) & ~0x7FF
    base, blobs = 0, []
    for i, (name, fmt, w, h, _rgba) in enumerate(textures):
        tex = xpr.Texture(name, fmt, 1 if fmt != xpr.FMT_8888 else 2, w, h, max(32, (w + 31) & ~31), True, 0)
        size = (tex.layout()[6] + 4095) & ~4095
        blobs.append((tex, base))
        base += size
    data = bytearray(struct.pack(">4sIII", b"XPR2", hsize, base, n))
    for i in range(n):
        data += struct.pack(">4sIII", b"TX2D", 16 * n + 4 + 52 * i, 52, name_offs[i])
    data += b"\0" * (12 + 16 * n + 4 - len(data))
    for i, (name, fmt, w, h, _rgba) in enumerate(textures):
        tex, b = blobs[i]
        dw0 = (1 << 31) | ((tex.pitch // 32) << 22) | 2
        dw1 = (b & ~0xFFF) | (tex.endian << 6) | fmt
        dw2 = (w - 1) | ((h - 1) << 13)
        data += struct.pack(">7I", 3, 1, 0, 0, 0, 0, 0) + struct.pack(">6I", dw0, dw1, dw2, 0, 0, 0)
    data += names
    data += b"\0" * (12 + hsize - len(data)) + b"\0" * base
    for (name, fmt, w, h, rgba), (tex, b) in zip(textures, blobs):
        tex.offset = 12 + hsize + b
        xpr.encode_into(data, tex, rgba)
    return bytes(data)


print("Texturas XPR2")
green = circle_tex(26, 26, (60, 170, 40))
red = circle_tex(26, 26, (210, 40, 40))
diag = diagram()
data = make_xpr([("A", xpr.FMT_DXT5, 26, 26, green), ("BTN_B", xpr.FMT_8888, 26, 26, red),
                 ("LT", xpr.FMT_DXT5, 24, 30, circle_tex(24, 30, (40, 40, 40))),
                 ("CONTROLS_P1", xpr.FMT_DXT5, 128, 128, diag), ("Fondo", xpr.FMT_DXT1, 64, 64, circle_tex(64, 64, (9, 9, 9)))])
texs = {t.name: t for t in xpr.parse(data)}
check(sorted(texs) == sorted(["A", "BTN_B", "LT", "CONTROLS_P1", "Fondo"]), "lee los nombres de las texturas")
check(xpr.decode(data, texs["BTN_B"]) == red, "8888 en mosaico: ida y vuelta exacta")
a = xpr.decode(data, texs["A"])
check(sum(abs(x - y) for x, y in zip(a, green)) / len(a) < 4, "DXT5 en mosaico: ida y vuelta casi exacta")
check(xpr.tiled_index(0, 0, 32, 4) == 0 and len({xpr.tiled_index(x, y, 32, 4) for x in range(32) for y in range(32)})
      == 1024, "mosaico de Xenos: biyección en 32×32")

print("Reconocer botones")
for name, want in (("A", "cross"), ("B", "circle"), ("X", "square"), ("Y", "triangle"), ("BTN_LB", "L1"),
                   ("button_rb_small", "R1"), ("LT", "L2"), ("RightTrigger", "R2"), ("Start", "options"),
                   ("Back", "create"), ("xbox_a", "cross"), ("Guide", "ps"),
                   ("arrowsLTn", ""), ("BGshapeLG", ""), ("LEGAL", ""), ("tab", ""), ("Dpad", ""), ("AREA_B", "")):
    check(glyphs.classify(name) == want, f"«{name}» → {want or 'no es un botón'}")

print("Diagrama del mando")
found = glyphs.find_face_buttons(diag, 128, 128)
check(all(found.get(c) for c in ("green", "red", "blue", "yellow")), "encuentra los 4 botones de colores")
check(glyphs.ps_diagram(diag, 128, 128) is not None, "repinta el diagrama con ✕ ○ □ △")
check(glyphs.ps_diagram(green + bytes(128 * 128 * 4 - len(green)), 128, 128) is None,
      "sin los 4 botones no toca nada")

print("Aplicar y quitar")
root = os.path.join(TMP, "juego")
os.makedirs(os.path.join(root, "assets", "MEDIA"))
xpr_path = os.path.join(root, "assets", "MEDIA", "ui.xpr")
open(xpr_path, "wb").write(data)
open(os.path.join(root, "assets", "MEDIA", "strings.bin"), "wb").write(b"ORIGINAL")
msgs = mods.apply(root, "playstation")
check(msgs and "PlayStation" in msgs[0], "capa PlayStation aplicada")
new = open(xpr_path, "rb").read()
check(len(new) == len(data) and new != data, "el .xpr cambia sin cambiar de tamaño")
t2 = {t.name: t for t in xpr.parse(new)}
check(xpr.decode(new, t2["Fondo"]) == xpr.decode(data, texs["Fondo"]), "las texturas que no son botones no se tocan")
check(xpr.decode(new, t2["A"]) != a, "la A ya es ✕")
check(mods.apply(root, "playstation") == [], "segunda vez: nada que hacer (rápido)")
mods.apply(root, "xbox")
check(open(xpr_path, "rb").read() == data, "volver a Xbox devuelve el archivo original byte a byte")
check(not os.listdir(os.path.join(root, "mods", ".reforge", "originales", "MEDIA")), "copia de seguridad retirada")

print("Packs")
pack = os.path.join(root, "mods", "Mi pack")
os.makedirs(os.path.join(pack, "MEDIA", "ui.xpr"))
QImage(10, 10, QImage.Format.Format_ARGB32).save(os.path.join(pack, "MEDIA", "ui.xpr", "Fondo.png"))
open(os.path.join(pack, "MEDIA", "strings.bin"), "wb").write(b"TRADUCIDO")
open(os.path.join(pack, "MEDIA", "extra.dat"), "wb").write(b"NUEVO")
msgs = mods.apply(root, "xbox")
check(any("Mi pack" in m for m in msgs), "pack aplicado")
check(open(os.path.join(root, "assets", "MEDIA", "strings.bin"), "rb").read() == b"TRADUCIDO", "archivo reemplazado")
now = open(xpr_path, "rb").read()
check(xpr.decode(now, t2["Fondo"]) != xpr.decode(data, texs["Fondo"]), "PNG de otro tamaño ajustado y aplicado")
check(xpr.decode(now, t2["A"]) == a, "sin estilo PlayStation la A sigue igual")
mods.apply(root, "xbox", disabled={"Mi pack"})
check(open(os.path.join(root, "assets", "MEDIA", "strings.bin"), "rb").read() == b"ORIGINAL", "pack desactivado: original")
check(not os.path.exists(os.path.join(root, "assets", "MEDIA", "extra.dat")), "archivo añadido por el pack, retirado")
check(open(xpr_path, "rb").read() == data, ".xpr original de nuevo")
open(os.path.join(root, "assets", "MEDIA", "strings.bin"), "wb").write(b"ACTUALIZADO")
mods.apply(root, "xbox")
check(open(os.path.join(root, "assets", "MEDIA", "strings.bin"), "rb").read() == b"TRADUCIDO", "pack sobre el archivo")
open(os.path.join(root, "assets", "MEDIA", "strings.bin"), "wb").write(b"PARCHE DEL JUEGO")
mods.apply(root, "xbox", disabled={"Mi pack"})
check(open(os.path.join(root, "assets", "MEDIA", "strings.bin"), "rb").read() == b"PARCHE DEL JUEGO",
      "si algo de fuera cambió el archivo, ese pasa a ser el original")

zpath = os.path.join(TMP, "Botones HD.zip")
with zipfile.ZipFile(zpath, "w") as z:
    z.writestr("Botones HD/pack.json", '{"nombre": "Botones HD", "autor": "yo"}')
    z.writestr("Botones HD/MEDIA/ui.xpr/A.png", open(os.path.join(pack, "MEDIA", "ui.xpr", "Fondo.png"), "rb").read())
name = mods.import_pack(root, zpath)
packs = {p["name"]: p for p in mods.list_packs(root)}
check(name == "Botones HD" and packs[name]["info"]["autor"] == "yo" and packs[name]["files"] == 1,
      "importar .zip (con carpeta raíz) y leer pack.json")

print("Exportar")
n = mods.export_textures(root)
check(n == 5 and os.path.isfile(os.path.join(root, "mods", mods.EXPORT_DIR, "MEDIA", "ui.xpr", "A.png")),
      "texturas exportadas a PNG")
check(not any(p["name"].startswith("_") for p in mods.list_packs(root)), "la exportación no cuenta como pack")

print("Mando conectado")
ds_bt = r"BTHENUM\{00001124-0000-1000-8000-00805F9B34FB}_VID&0002054C_PID&0CE6\8&3A358462&0&48188D6603AF_C00000000"
check(controller.detect([ds_bt, r"ROOT\SYSTEM\0001"]) == "playstation", "DualSense por Bluetooth (con DS4Windows/ViGEm)")
check(controller.detect([r"USB\VID_054C&PID_0CE6\5&1"]) == "playstation", "DualSense por USB")
check(controller.detect([r"USB\VID_045E&PID_028E\1"]) == "xbox", "mando de Xbox")
check(controller.resolve("xbox", [ds_bt]) == "xbox" and controller.resolve("auto", [ds_bt]) == "playstation",
      "lo elegido a mano manda; «auto» sigue al mando")
o = GameOptions.load(root)
check(o.button_style == "auto" and o.mods_disabled == [], "opciones por defecto: automático, todos los packs")
check(isinstance(game.apply_visual_layers(root, log=lambda m: None), list), "aplicar al jugar nunca lanza")

real = "/mnt/user-data/uploads/ReForgeProjects/castlevania_sotn/assets/MEDIA/uiresource.xpr"
if os.path.isfile(real):
    print("Castlevania SOTN (real)")
    sroot = os.path.join(TMP, "sotn")
    os.makedirs(os.path.join(sroot, "assets", "MEDIA"))
    shutil.copy(real, os.path.join(sroot, "assets", "MEDIA"))
    mods.apply(sroot, "playstation")
    st = mods._load_state(sroot)["escaneo"]["MEDIA/uiresource.xpr"]["found"]
    check({"A", "B", "X", "Y", "BTN_LB", "BTN_RB", "LT", "RT", "Start", "ALUCARDCONTROLS_P1"} <= set(st),
          "botones y diagramas del juego reconocidos")
    mods.apply(sroot, "xbox")
    check(open(os.path.join(sroot, "assets", "MEDIA", "uiresource.xpr"), "rb").read() == open(real, "rb").read(),
          "y vuelta al original exacto")
print(f"\nTodas las pruebas pasaron ({ok}).")
