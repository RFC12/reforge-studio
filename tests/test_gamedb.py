"""Base de datos de compatibilidad por Title ID: fusión de capas, aplicación al proyecto, aprender/compartir."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import gamedb              # noqa: E402
from reforge.game_options import GameOptions  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


tmp = tempfile.mkdtemp()
proj = os.path.join(tmp, "mi_juego")
cfg = os.path.join(tmp, "config")
os.makedirs(proj, exist_ok=True)
os.makedirs(cfg, exist_ok=True)

# Redirigir la carpeta de configuración (base de usuario) y el lector de Title ID.
gamedb.config_dir = lambda: cfg
_TID = {"v": ""}
gamedb.title_id_of = lambda root: _TID["v"]


print("La semilla verificada se ve en la ficha (Asura's Wrath, gamma UNORM16)")
rec = gamedb.record("43430817")
check(rec is not None and rec["flags"].get("gfx_gamma_unorm16") is True, "ficha de semilla con su arreglo gráfico")
check(rec and rec.get("conf") == "verificado", "marcada como verificada")

print("Aplicar una ficha de usuario pone el modo de imagen y las banderas idóneas")
_TID["v"] = "4D5309AB"
gamedb._save_user({"4D5309AB": {"name": "Juego X", "preset": "rov_inv",
                                "flags": {"gfx_fuzzy_alpha": True}, "guide": "efectos aditivos",
                                "source": "prueba", "conf": "probado"}})
msgs = gamedb.apply(proj)
o = GameOptions.load(proj)
check(o.preset() == "rov_inv", "aplica el modo de imagen de la ficha")
check(o.rov_required is True, "marca que el juego necesita ROV")
check(o.gfx_fuzzy_alpha is True, "aplica la bandera gráfica de la ficha")
check(len(msgs) >= 1, "informa de lo que aplicó")

print("No pisa un modo de imagen que el usuario ya eligió a mano")
o2 = GameOptions.load(proj)
o2.apply_preset("rtv")
o2.gfx_fuzzy_alpha = False
o2.save(proj)
gamedb.apply(proj)
check(GameOptions.load(proj).preset() == "rtv", "respeta el modo elegido a mano")

print("remember() guarda la config actual del juego en la base de usuario")
_TID["v"] = "ABCDEF01"
o3 = GameOptions.load(proj)
o3.apply_preset("rov")
o3.gfx_gamma_unorm16 = True
o3.save(proj)
ok = gamedb.remember(proj, guide="va fino", source="yo")
r = gamedb.record("ABCDEF01")
check(ok and r is not None, "se guardó")
check(r and r.get("preset") == "rov", "recordó el modo de imagen")
check(r and r["flags"].get("gfx_gamma_unorm16") is True, "recordó la bandera gráfica no estándar")

print("Exportar e importar la base de usuario")
expath = os.path.join(tmp, "compat.json")
n = gamedb.export_db(expath)
check(n >= 2 and os.path.isfile(expath), "exporta a JSON")
gamedb._save_user({})
check(gamedb.record("ABCDEF01") is None, "base de usuario vaciada")
add = gamedb.import_db(expath)
check(add >= 2 and gamedb.record("ABCDEF01") is not None, "reimporta los juegos")

print("forget() quita un juego")
check(gamedb.forget("ABCDEF01") is True and gamedb.record("ABCDEF01") is None, "lo elimina")

print("La guía incluye el Title ID y el enlace de referencia de Xenia")
_TID["v"] = "4D5309AB"
g = gamedb.guide(proj)
check("4D5309AB" in g, "muestra el Title ID")
check("xenia" in g.lower(), "enlaza la referencia de Xenia")

print("summary() cuenta los juegos de la base")
s = gamedb.summary()
check("juego" in s.lower(), "resume el contenido")

print("Candado de framerate: Asura's Wrath está marcado (fuente: catálogo de Xenia/boma)")
fl = gamedb.frame_lock("43430817")
check(fl is not None and fl.get("locked") is True, "Asura marcado como frame-locked")
check(fl and "boma" in (fl.get("source") or "").lower(), "cita la fuente del catálogo")

print("frame_advice avisa en un juego con candado y desbloqueo de FPS activo")
_TID["v"] = "43430817"
oa = GameOptions.load(proj)
oa.fps_unlocked = True
oa.smooth_motion = False
oa.save(proj)
locked, adv = gamedb.frame_advice(proj)
check(locked is True and "Movimiento Suave" in adv, "recomienda Movimiento Suave")
check(adv.startswith("⚠"), "avisa porque el desbloqueo está activo")

print("auto_relaunch está desactivado por defecto (cerrar un juego no lo reabre solo)")
check(GameOptions().auto_relaunch is False, "auto_relaunch por defecto = False")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
