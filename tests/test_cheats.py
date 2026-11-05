"""Trucos de la base de datos de Xenia (game-patches) y parche XEXP propio.   python tests/test_cheats.py"""
import hashlib
import io
import os
import struct
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-cheats-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)

from reforge import cheats, xexpatch  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


TID = 0x4D53082D
AES = bytes(range(16, 32))


def fake_xex(code_pages=(1, 2), page_flag_4k=False):
    """XEX2 base: 0x82000000, 4 páginas de 64 KB; las de `code_pages` son de código."""
    h = bytearray(0x400)
    struct.pack_into(">4sIIIII", h, 0, b"XEX2", 1, 0x400, 0, 0x100, 2)
    struct.pack_into(">IIII", h, 0x18, 0x000003FF, 0x50, 0x00040006, 0x70)
    struct.pack_into(">IHH", h, 0x50, 16, 1, 1)
    struct.pack_into(">IIII", h, 0x70, 0x1234, 0x00000005, 0, TID)
    sec = 0x100
    struct.pack_into(">II", h, sec, 0x184 + 4 * 24, 0x40000)
    h[sec + 8: sec + 0x108] = bytes(range(256))
    struct.pack_into(">II", h, sec + 0x10C, 0x10000000 if page_flag_4k else 0, 0x82000000)
    h[sec + 0x150: sec + 0x160] = AES
    struct.pack_into(">I", h, sec + 0x180, 4)
    for i in range(4):
        struct.pack_into(">I", h, sec + 0x184 + i * 24, (1 << 4) | (1 if i in code_pages else 2))
    return bytes(h) + bytes(0x100)


PATCH_TOML = '''title_name = "Gears of War 2"
title_id = "4D53082D" # MS-2093
hash = ["BDB97753374D520A", "0123456789ABCDEF"]

[[patch]]
    name = "Munición infinita"
    desc = "No gasta balas."
    author = "Alguien"
    is_enabled = false

    [[patch.be32]]
        address = 0x82010010
        value = 0x60000000

[[patch]]
    name = "Valores de datos"
    author = "Otro"
    is_enabled = false

    [[patch.be8]]
        address = 0x82030000
        value = 0x01
    [[patch.be16]]
        address = 0x82030002
        value = 0xabcd
    [[patch.f32]]
        address = 0x82030004
        value = 1.5
    [[patch.string]]
        address = 0x82030010
        value = "ok"
    [[patch.u16string]]
        address = 0x82030020
        value = "Hi"
    [[patch.array]]
        address = 0x82030030
        value = "0xdeadbeef"
'''

print("Base de datos")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("game-patches-main/patches/4D53082D - Gears of War 2.patch.toml", PATCH_TOML)
    z.writestr("game-patches-main/patches/README.md", "x")
    z.writestr("game-patches-main/patches/58410A1B - Otro.patch.toml", 'title_name="x"\ntitle_id="58410A1B"\nhash="1"\n')
check(cheats.install_db_zip(buf.getvalue()) == 2 and cheats.db_info()["files"] == 2, "instala la base de datos (zip de GitHub)")
files = cheats.files_for_title("4d53082d")
check(len(files) == 1 and files[0].hashes == ["BDB97753374D520A", "0123456789ABCDEF"], "encuentra el archivo del juego")
p = {x.name: x for x in files[0].patches}
data = dict(p["Valores de datos"].writes)
check(data[0x82030000] == b"\x01" and data[0x82030002] == b"\xab\xcd" and data[0x82030004] == struct.pack(">f", 1.5)
      and data[0x82030010] == b"ok" and data[0x82030020] == "Hi".encode("utf-16-le")
      and data[0x82030030] == bytes.fromhex("deadbeef"), "convierte todos los tipos como Xenia")
check(len(cheats.patches_for("4D53082D", "BDB97753374D520A")) == 2, "con el hash de tu versión salen sus parches")
check(cheats.patches_for("4D53082D", "FFFFFFFFFFFFFFFF") == [], "con otra versión no sale ninguno")
check(cheats.patches_for("4D53082D", "") == [], "sin hash conocido no se ofrece nada (evita romper el juego)")

print("Parche XEXP propio")
xex = fake_xex()
check(cheats.code_ranges(xex) == [(0x82010000, 0x82020000), (0x82020000, 0x82030000)], "secciones de código del XEX")
check(cheats.code_ranges(fake_xex(page_flag_4k=True))[0] == (0x82001000, 0x82002000), "páginas de 4 KB")
xp = xexpatch.build_xexp(xex, [(0x82010010, b"\x60\0\0\0"), (0x82030004, b"\x3f\xc0\0\0")])
flags, hsize, _r, sec, count = struct.unpack_from(">IIIII", xp, 4)
hdr = {struct.unpack_from(">I", xp, 0x18 + i * 8)[0]: struct.unpack_from(">I", xp, 0x1C + i * 8)[0] for i in range(count)}
check(xp[:4] == b"XEX2" and flags == 0x40 and hdr.keys() >= {0x3FF, 0x5FF}, "XEX2 de tipo «patch delta»")
d = hdr[0x5FF]
key = xexpatch.aes_decrypt_block(xexpatch.RETAIL_KEY, AES)
check(xp[d + 0xC: d + 0x20] == hashlib.sha1(bytes(range(256))).digest(), "huella del XEX base (la comprueba rexglue)")
check(xexpatch.aes_decrypt_block(key, xp[d + 0x20: d + 0x30]) == key, "clave de imagen válida para el cargador")
ff = hdr[0x3FF]
_sz, enc, comp, window, bsize = struct.unpack_from(">IHHII", xp, ff)
block = xp[hsize:]
check(enc == 0 and comp == 3 and len(block) == bsize and hashlib.sha1(block).digest() == xp[ff + 16: ff + 36],
      "bloque de datos con su hash (sin cifrar, delta)")
pos, seen = 24, []
while True:
    old, new, ulen, clen = struct.unpack_from(">IIHH", block, pos)
    if not (old or new or ulen or clen):
        break
    lz = block[pos + 12: pos + 12 + clen]
    seen.append((new, lz[16:16 + ulen]))
    check(lz[:2] != b"\0\0" and struct.unpack_from("<III", lz, 4) == (1, 1, 1), "LZX: bloque sin comprimir alineado")
    pos += 12 + clen
check(seen == [(0x10010, b"\x60\0\0\0"), (0x30004, b"\x3f\xc0\0\0")], "escribe los bytes en su sitio de la imagen")
try:
    xexpatch.build_xexp(xex, [(0x90000000, b"\0")])
    check(False, "fuera del ejecutable")
except xexpatch.XexPatchError:
    check(True, "rechaza direcciones fuera del ejecutable")

print("Aplicar al proyecto")
root = os.path.join(TMP, "gow2")
os.makedirs(os.path.join(root, "assets"))
os.makedirs(os.path.join(root, "generated", "default"))
open(os.path.join(root, "assets", "default.xex"), "wb").write(xex)
open(os.path.join(root, "gow2_manifest.toml"), "w").write('[entrypoint]\nout_directory_path = "generated/default"\n')
stamp = os.path.join(root, "generated", "default", "codegen.build.stamp")
open(stamp, "w").write("x")
check(cheats.apply_cheats(root, [p["Munición infinita"]]) is True and not os.path.exists(stamp),
      "un truco de código pide recompilar (y fuerza regenerar el código)")
check(os.path.isfile(os.path.join(root, "assets", "default.xexp")) and
      cheats.cheats_state(root)["patches"] == ["Munición infinita"], "deja default.xexp y recuerda la selección")
open(stamp, "w").write("x")
check(cheats.apply_cheats(root, [p["Munición infinita"], p["Valores de datos"]]) is False and os.path.exists(stamp),
      "añadir uno de datos no obliga a recompilar")
check(cheats.apply_cheats(root, []) is True and not os.path.exists(os.path.join(root, "assets", "default.xexp")),
      "quitarlos borra el parche y vuelve a recompilar el código original")
from reforge import title_update  # noqa: E402
open(os.path.join(root, "assets", "default.xexp"), "wb").write(b"TU")
try:
    cheats.apply_cheats(root, [p["Munición infinita"]])
    check(False, "TU")
except cheats.CheatError as e:
    check("actualización" in str(e), "no pisa una actualización instalada")
os.remove(os.path.join(root, "assets", "default.xexp"))
cheats.apply_cheats(root, [p["Valores de datos"]])
check(title_update.installed_update(root) is None, "el parche de trucos no cuenta como actualización")
try:
    title_update.check_update(root, os.path.join(TMP, "x.xexp"))
    check(False, "trucos activos")
except title_update.TitleUpdateError as e:
    check("trucos" in str(e), "y no se instala una actualización encima de los trucos")

print("Juego: versión exacta y aviso de trucos")
exe = os.path.join(root, "build", "gow2.exe")
os.makedirs(os.path.dirname(exe))
open(exe, "w").write("")
open(os.path.join(root, "build", "reforge_module.txt"), "w").write("title_id=4D53082D\nhash=bdb97753374d520a\n")
check(cheats.read_module_info(exe)["hash"] == "BDB97753374D520A", "lee el hash que anota el juego")
from reforge.profile import ext_ini_path, write_ext_ini  # noqa: E402
write_ext_ini(exe)
check("cheats = 1" in open(ext_ini_path(exe), encoding="utf-8").read(), "el juego sabe que tiene trucos (no reescribe el hash)")
from reforge.ext_cpp import EXT_SOURCE  # noqa: E402
check("XXH3_64bits" in EXT_SOURCE and "0x44, 0x00, 0x00, 0x42" in EXT_SOURCE and "reforge_module.txt" in EXT_SOURCE,
      "la extensión calcula el hash como Xenia (con los thunks reescritos)")

print("Ventana 🎯 Trucos")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
app = QApplication.instance() or QApplication([])
from reforge.core import AppConfig  # noqa: E402
from reforge import cheats_ui  # noqa: E402
cheats_ui.game.game_exe = lambda r, n="": exe
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)
rebuilt = []
dlg = cheats_ui.CheatsDialog(None, AppConfig(), root, "gow2", rebuild=rebuilt.append)
check(dlg.list.count() == 2 and "BDB97753374D520A" in dlg.ver_lbl.text(), "muestra los trucos de tu versión")
states = {dlg.list.item(i).data(0x0100): dlg.list.item(i).checkState() for i in range(dlg.list.count())}
check(states["Valores de datos"].value == 2 and states["Munición infinita"].value == 0, "marca los que ya están activos")
dlg._check_all(True)
dlg.apply()
check(rebuilt == [root] and set(cheats.cheats_state(root)["patches"]) == {"Munición infinita", "Valores de datos"},
      "aplica y pide recompilar cuando cambia el código")
print(f"\nTodas las pruebas pasaron ({ok}).")
