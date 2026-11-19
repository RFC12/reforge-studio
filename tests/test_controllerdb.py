"""Base de mapeos de mando (gamecontrollerdb) y aviso del DualSense."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import controllerdb as C                    # noqa: E402
from reforge import controller as CT                      # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


print("Base de mapeos SDL empaquetada")
src = C.bundled_path()
check(bool(src) and os.path.isfile(src), "assets/gamecontrollerdb.txt está empaquetado")
texto = open(src, encoding="utf-8").read() if src else ""
check(C._version(texto) is not None, "lleva la cabecera REFORGE-GCDB con versión")
# un mando moderno al menos (DualSense = «PS5 Controller» en la base SDL)
check("PS5 Controller" in texto, "incluye el DualSense (PS5 Controller)")
# alguna línea de mapeo real: GUID + nombre + al menos 15 asignaciones
mapeos = [ln for ln in texto.splitlines() if ln and not ln.startswith("#") and ln.count(",") >= 15]
check(len(mapeos) > 100, f"trae muchos mapeos reales ({len(mapeos)})")

print("Colocación no destructiva")
with tempfile.TemporaryDirectory() as d:
    ok, _ = C.place(d, src=src)
    dst = os.path.join(d, "gamecontrollerdb.txt")
    check(ok and os.path.isfile(dst), "se coloca cuando no hay ninguno")
    ok2, _ = C.place(d, src=src)
    check(not ok2, "no reescribe si ya está al día")

with tempfile.TemporaryDirectory() as d:
    dst = os.path.join(d, "gamecontrollerdb.txt")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("# mis mapeos propios\n030000001234,Mi mando,a:b0,\n")
    ok, motivo = C.place(d, src=src)
    propio = open(dst, encoding="utf-8").read()
    check(not ok and "Mi mando" in propio, "respeta un gamecontrollerdb.txt propio (sin cabecera)")

with tempfile.TemporaryDirectory() as d:
    dst = os.path.join(d, "gamecontrollerdb.txt")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("# REFORGE-GCDB v999\n030000009999,Futuro,a:b0,\n")
    ok, _ = C.place(d, src=src)
    check(not ok and "Futuro" in open(dst, encoding="utf-8").read(),
          "no pisa una versión REFORGE-GCDB más nueva")

print("Aviso DualSense / Steam Input")
sony = ["USB\\VID_054C&PID_0CE6\\ABC", "HID\\VID_045E&PID_02FF\\XYZ"]
xbox = ["USB\\VID_045E&PID_02FF\\XYZ"]
check(CT.dualsense_present(sony), "detecta un DualSense (054C:0CE6)")
check(not CT.dualsense_present(xbox), "no lo detecta con solo un mando Xbox")
check("Steam Input" in CT.advice(sony), "da el consejo de Steam Input con un mando Sony")
check(CT.advice(xbox) == "", "no molesta si no hay mando Sony")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
