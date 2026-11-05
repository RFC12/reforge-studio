"""Icono del juego sacado del XEX (XDBF) para el .exe.   python tests/test_gameicon.py"""
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-icon-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from reforge import gameicon, sweep  # noqa: E402
from reforge.xexpatch import RETAIL_KEY, aes_encrypt_block  # noqa: E402

app = QGuiApplication.instance() or QGuiApplication([])
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


def png_of(color, size=64):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(color)
    return gameicon._png_bytes(img)


def xdbf(png):
    entries = [(1, 0x1234, 0, 4), (2, 0x8000, 4, len(png))]         # una entrada cualquiera + imagen del título
    head = struct.pack(">4sIIIII", b"XDBF", 0x10000, len(entries), len(entries), 1, 0)
    table = b"".join(struct.pack(">HQII", *e) for e in entries) + bytes(8)
    return head + table + b"abcd" + png


def make_xex(png, title_id=0x4D53ABCD, encrypt=True, comp=1, base=0x82000000):
    """XEX2 mínimo: imagen = [relleno][XDBF] con compresión básica (datos + ceros) y cifrado retail."""
    db = xdbf(png)
    res_off = 0x3000
    image = bytearray(0x1000) + bytes(0x2000) + db          # el bloque de ceros cae en 0x1000..0x3000
    image += bytes(-len(image) % 16)
    image_size = len(image)
    blocks = [(0x1000, 0x2000), (image_size - res_off, 0)]
    stream = image[:0x1000] + image[res_off:]
    session = bytes(range(16))
    if encrypt:
        out, prev = bytearray(), bytes(16)
        for i in range(0, len(stream), 16):
            c = aes_encrypt_block(session, bytes(a ^ b for a, b in zip(stream[i:i + 16], prev)))
            out += c
            prev = c
        stream = bytes(out)
    enc_key = aes_encrypt_block(RETAIL_KEY, session)
    header_size, sec = 0x1000, 0x200
    x = bytearray(header_size)
    hdrs = [(0x00040006, 0x400), (0x000002FF, 0x500), (0x000003FF, 0x600)]
    struct.pack_into(">4sIIII", x, 0, b"XEX2", 0, header_size, 0, sec)
    struct.pack_into(">I", x, 0x14, len(hdrs))
    for i, (k, v) in enumerate(hdrs):
        struct.pack_into(">II", x, 0x18 + i * 8, k, v)
    struct.pack_into(">II", x, sec, 0x180, image_size)
    struct.pack_into(">I", x, sec + 0x110, base)
    x[sec + 0x150: sec + 0x160] = enc_key
    struct.pack_into(">IIII", x, 0x400, 0, 0, 0, title_id)
    struct.pack_into(">I8sII", x, 0x500, 20, f"{title_id:08X}".encode(), base + res_off, len(db))
    struct.pack_into(">IHH", x, 0x600, 8 + 8 * len(blocks), 1 if encrypt else 0, comp)
    for i, (d, z) in enumerate(blocks):
        struct.pack_into(">II", x, 0x608 + i * 8, d, z)
    return bytes(x) + stream, bytes(image)


print("Extraer la imagen oficial del XEX")
red = png_of(0xFFCC0000)
for enc in (True, False):
    xex, image = make_xex(red, encrypt=enc)
    path = os.path.join(TMP, f"x{int(enc)}.xex")
    open(path, "wb").write(xex)
    png, src = gameicon.title_png(path)
    check(png == red and src == "xex", f"compresión básica {'cifrada' if enc else 'sin cifrar'} → PNG exacto")

xex, image = make_xex(red, comp=2)                       # LZX: no se lee directo
path = os.path.join(TMP, "lzx.xex")
open(path, "wb").write(xex)
check(gameicon.title_png(path) == (b"", ""), "LZX sin imagen cargada → nada (sin errores)")
img_bin = os.path.join(TMP, "reforge_image.bin")
open(img_bin, "wb").write(image)
check(gameicon.title_png(path, img_bin) == (red, "imagen"), "LZX con reforge_image.bin → PNG de la partida")
check(gameicon.title_png(os.path.join(TMP, "no.xex")) == (b"", ""), "sin XEX → nada")

print("Juegos reales (si están)")
for g in ("gears_of_war_2_latino", "f_f_showdown"):
    real = f"/mnt/user-data/uploads/ReForgeProjects/{g}/assets/default.xex"
    if os.path.isfile(real):
        png, src = gameicon.title_png(real)
        check(png.startswith(gameicon.PNG_MAGIC) and src == "xex", f"{g}: icono oficial del XEX")

print(".ico")
ico = gameicon.build_ico(red)
parts = gameicon.parse_ico(ico)
check([p[0] for p in parts] == [s % 256 for s in gameicon.ICON_SIZES], "un PNG por tamaño (16…256)")
check(all(p[6].startswith(gameicon.PNG_MAGIC) for p in parts), "entradas PNG válidas")
big = QImage.fromData(parts[-1][6])
check(big.width() == 256 and big.pixelColor(128, 128).red() > 200, "256 px escalado con el color original")
grp = gameicon._group_entry(*parts[0][:6], parts[0][6], 1)
check(len(grp) == 14, "entrada de grupo de iconos de 14 bytes (GRPICONDIRENTRY)")
fb = gameicon.fallback_png("castle crashers")
check(QImage.fromData(fb).width() == 256, "icono de respaldo con iniciales")

print("Aplicar al proyecto")
root = os.path.join(TMP, "juego")
os.makedirs(os.path.join(root, "assets"))
os.makedirs(os.path.join(root, "build"))
xex, _ = make_xex(red)
open(os.path.join(root, "assets", "default.xex"), "wb").write(xex)
exe = os.path.join(root, "build", "juego.exe")
open(exe, "wb").write(b"MZ")
msg = gameicon.ensure(exe, root, "Juego")
check(os.path.isfile(os.path.join(root, "build", gameicon.ICO_FILE)), ".ico guardado junto al .exe")
check(open(os.path.join(root, gameicon.PNG_FILE), "rb").read() == red, "PNG oficial copiado al proyecto")
if sys.platform != "win32":
    check(msg == "", "fuera de Windows no toca el .exe")
    check(sweep.check_icon(root, exe) == [], "barrido: capa de icono sin ruido fuera de Windows")
check(gameicon.ensure("", root) == "", "sin .exe: no hace nada")
print(f"\nTodas las pruebas pasaron ({ok}).")
