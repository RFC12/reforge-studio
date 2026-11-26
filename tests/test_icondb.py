"""Base de datos de iconos por Title ID (se aprende al recompilar y se reutiliza).

python tests/test_icondb.py
"""
import os
import struct
import sys
import tempfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from reforge import gameicon, icondb  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


def png(size=256, rgb=(90, 160, 200)):
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


TMP = tempfile.mkdtemp(prefix="reforge-icons-")
icondb.icons_dir = lambda: TMP          # base de datos de pruebas, sin tocar la del usuario

print("Base de datos de iconos")
imagen = png()
check(icondb.lookup("43430842") == b"", "un juego que aún no se conoce no tiene icono")
check(icondb.remember("43430842", imagen), "se guarda el icono que trae el juego")
check(icondb.lookup("43430842") == imagen, "y se recupera igual (mismo Title ID)")
check(icondb.lookup("43430817") == b"", "cada juego tiene el suyo: no se mezclan")
check(icondb.remember("53450813", b"no es un png") is False, "solo se guardan PNG de verdad")
check(icondb.count() == 1, f"la base cuenta los juegos guardados ({icondb.count()})")

print("El .exe se queda con el icono de la base")
root = tempfile.mkdtemp(prefix="reforge-icons-proj-")
os.makedirs(os.path.join(root, "assets"), exist_ok=True)
os.makedirs(os.path.join(root, "build"), exist_ok=True)
with open(os.path.join(root, "assets", "default.xex"), "wb") as f:
    f.write(b"\0" * 64)
exe = os.path.join(root, "build", "juego.exe")
with open(exe, "wb") as f:
    f.write(b"MZ" * 200)
gameicon.title_id = lambda _p: "43430842"     # el XEX de prueba no es real: se fija el Title ID
hecho = gameicon.ensure(exe, root, "Juego", force=True)
junto = os.path.join(os.path.dirname(exe), "reforge_icon.png")
check(os.path.isfile(junto) and open(junto, "rb").read() == imagen, "sale el icono guardado, no el de iniciales")
if sys.platform == "win32":   # fuera de Windows no se incrusta el icono en el .exe (ensure devuelve "")
    check("base de iconos" in hecho or "no se pudo grabar" in hecho, f"lo dice al aplicarlo: {hecho!r}")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
