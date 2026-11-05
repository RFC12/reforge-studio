"""Análisis profundo de entradas de función y mantenimiento.   python tests/test_deepscan.py"""
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-deep-")
sys.path.insert(0, ROOT)
from reforge import deepscan, game  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


BASE, PAGE = 0x82000000, 0x10000


def xex_with_pages(types):
    sec = 0x200
    x = bytearray(0x1000)
    struct.pack_into(">4sIIII", x, 0, b"XEX2", 0, 0x1000, 0, sec)
    struct.pack_into(">II", x, sec + 0x10C, 0, BASE)
    struct.pack_into(">I", x, sec + 0x180, len(types))
    for i, t in enumerate(types):
        struct.pack_into(">I", x, sec + 0x184 + i * 24, (1 << 4) | t)
    return bytes(x)


# página 0: datos · página 1: código · página 2: datos
xex = xex_with_pages([2, 1, 2])
img = bytearray(3 * PAGE)
code = BASE + PAGE
f1, f2, f3 = code + 0x100, code + 0x200, code + 0x300          # funciones registradas
missing_vt = code + 0x248                                       # entrada secundaria a mitad de f2 (vtable)
missing_lis = code + 0x3A0                                      # dirección formada con lis/addi en f1
registered = {f1, f2, f3, code + 0x400}
vt = 2 * PAGE + 0x80                                            # tabla de métodos virtuales en datos
for k, v in enumerate([f1, f2, missing_vt, f3]):
    struct.pack_into(">I", img, vt + 4 * k, v)
struct.pack_into(">II", img, 0x40, 0x12345678, code + 0x10)    # datos sueltos: no son una tabla
o = f1 - BASE + 0x10                                           # en f1: lis r11,hi ; addi r11,r11,lo
hi, lo = missing_lis >> 16, missing_lis & 0xFFFF
if lo & 0x8000:
    hi += 1
struct.pack_into(">II", img, o, (15 << 26) | (11 << 21) | hi, (14 << 26) | (11 << 21) | (11 << 16) | lo)
o2 = f2 - BASE + 0x10                                          # en f2: dirección de su propio switch
struct.pack_into(">II", img, o2, (15 << 26) | (10 << 21) | (code >> 16), (14 << 26) | (10 << 21) | (10 << 16) | 0x220)

print("Análisis profundo")
found = deepscan.scan(bytes(img), xex, registered)
check(missing_vt in found, "encuentra la entrada que falta en una tabla de métodos virtuales")
check(missing_lis in found, "encuentra una dirección de código formada con lis/addi en otra función")
check(code + 0x220 not in found, "ignora la base de un switch de la misma función")
check(code + 0x10 not in found, "ignora punteros sueltos fuera de tablas")
check(not (set(found) & registered), "no repite funciones ya registradas")

proj = os.path.join(TMP, "proj")
os.makedirs(os.path.join(proj, "assets"))
os.makedirs(os.path.join(proj, "build"))
open(os.path.join(proj, "assets", "default.xex"), "wb").write(xex)
gen = os.path.join(proj, "generated", "default")
os.makedirs(gen)
open(os.path.join(gen, "g_register.cpp"), "w").write(
    "".join(f"  registrar->SetFunction(0x{a:08X}, sub_{a:08X});\n" for a in sorted(registered)))
exe = os.path.join(proj, "build", "g.exe")
check(deepscan.deep_scan_project(proj, exe, gen) is None, "sin imagen volcada todavía: lo dice (None)")
open(os.path.join(proj, "build", deepscan.IMAGE_FILE), "wb").write(bytes(img))
cands = deepscan.deep_scan_project(proj, exe, gen)
check(set(cands) == set(found), "usa la imagen que vuelca el juego (reforge_image.bin)")
open(os.path.join(proj, "g_manifest.toml"), "w").write('[project]\nname = "g"\n\n[entrypoint]\nfile_path = "assets/default.xex"\n')
new = game.declare_functions(proj, cands, "entrada encontrada por el análisis profundo")
check(set(new) == set(cands) and game.declare_functions(proj, cands, "x") == [],
      "las declara todas de una vez, sin duplicar")

print("Varios fallos en el mismo arranque")
log = os.path.join(TMP, "g_001.log")
open(log, "w").write("[critical] [FATAL] Call to invalid or unregistered function at guest address 0x828777D0\n"
                     "[critical] [FATAL] Call to invalid or unregistered function at guest address 0x828777E0\n"
                     "[critical] [FATAL] Call to invalid or unregistered function at guest address 0x828777D0\n")
check(game.unregistered_in_log(log) == [0x828777D0, 0x828777E0], "lee todas las direcciones del log, sin repetir")
print(f"\nTodas las pruebas pasaron ({ok}).")
