"""Conexión de perfil/logros con puertos de la comunidad (mismo Title ID)."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import communityports as cp  # noqa: E402
from reforge import portachievements as pa  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


port = cp.by_id("pinyonshift")
d = tempfile.mkdtemp()
exe = os.path.join(d, "Horizon.exe")
open(exe, "wb").write(b"\0" * 1000)

print("link_profile deja la identidad de ReForge junto al .exe del puerto")
# write_ext_ini necesita Qt para algunos sidecars; se prueba que no rompe y que escribe el .ini.
ini = pa.link_profile(exe)
check(ini == "" or (os.path.isfile(ini) and os.path.dirname(ini) == d),
      "escribe reforge_ext.ini junto al .exe (o '' si no hay perfil), sin reventar")

print("progress lee el estado de guardado del puerto si existe")
check(pa.progress(port, exe) is None, "sin carpeta de estado, no inventa progreso")
state = os.path.join(d, "pinyon_shift_state")
os.makedirs(state, exist_ok=True)
with open(os.path.join(state, "achievements.json"), "w", encoding="utf-8") as f:
    json.dump({"unlocked": ["a", "b", "c"], "total": 12}, f)
prog = pa.progress(port, exe)
check(prog is not None and prog["unlocked"] == 3 and prog["total"] == 12, "cuenta 3/12 desbloqueados")

print("_count_from tolera varios formatos")
check(pa._count_from({"achievements": {"x": True, "y": False, "z": True}}) == (2, 3), "dict de logros")
check(pa._count_from([{"unlocked": True}, {"unlocked": False}]) == (1, 2), "lista de logros")

print("connect devuelve un resumen honesto")
res = pa.connect(port, exe, game_root=d)
check(isinstance(res["summary"], str) and "Biblioteca" in res["summary"],
      "el resumen dice que lo añade a la Biblioteca con la carátula")
check("BACK + START" in res["summary"] and "LOGROS" in res["summary"],
      "e indica el menú del propio puerto (Back+Start) con los logros del juego")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
