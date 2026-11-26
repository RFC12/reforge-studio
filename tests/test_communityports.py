"""Gestor de puertos de la comunidad: registro, búsqueda por juego y estado de archivos."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import communityports as cp  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


tmp = tempfile.mkdtemp()
cp.config_dir = lambda: tmp   # no tocar la config real del usuario

print("Hay puertos registrados y se encuentran por Title ID del juego")
check(len(cp.all_ports()) >= 1, "el registro no está vacío")
port = cp.for_title("565507E4")
check(port is not None and "VitoMiguelF" in port.author, "encuentra el puerto de Crash of the Titans por su Title ID")
forza = cp.for_title("4D5309C9")
check(forza is not None and forza.author == "arcanite24" and forza.engine == "ShiftGlue",
      "encuentra el puerto de Forza Horizon (Pinyon Shift, familia ShiftGlue)")
check(cp.for_title("43430817") is None, "un juego sin puerto registrado devuelve None")
check(cp.by_id("crashott") is port, "se puede buscar por id")
check(port.engine == "XenonRecomp" and "default.xex" in port.game_files, "guarda el motor y los archivos que aporta el usuario")

print("Estado del puerto y de los archivos de juego")
check(port.is_cloned() is False, "todavía no está clonado")
check(port.dir().startswith(tmp), "la carpeta del puerto está dentro de la config de ReForge")

game = tempfile.mkdtemp()
st = cp.game_files_status(port, game)
check(st == {"default.xex": False, "default.rcf": False}, "detecta que faltan los archivos de juego")
open(os.path.join(game, "default.xex"), "w").write("x")
open(os.path.join(game, "default.rcf"), "w").write("x")
check(all(cp.game_files_status(port, game).values()), "detecta cuando ya están los archivos")
check(cp.ready_to_build(port, game) is False, "no está listo si no se ha clonado aún")

print("for_project sugiere el puerto a partir del Title ID del proyecto")
root = tempfile.mkdtemp()
os.makedirs(os.path.join(root, "assets"), exist_ok=True)
open(os.path.join(root, "assets", "default.xex"), "wb").write(b"\0" * 32)
cp.gameicon = __import__("reforge.gameicon", fromlist=["gameicon"])
cp._title_id_of = lambda r: "565507E4"
check(cp.for_project(root) is port, "relaciona el proyecto con su puerto de la comunidad")

print("Plan de construcción: pasos claros y en orden")
pasos = cp.build_plan(port)
check(len(pasos) >= 3 and any("release" in p.lower() for p in pasos), "el plan menciona descargar el release")
check(any("lanzador" in p.lower() or "biblioteca" in p.lower() for p in pasos), "y envolverlo con comodidades")

print("Detecta el .exe construido ignorando herramientas del toolchain")
pd = port.dir()
os.makedirs(pd, exist_ok=True)
open(os.path.join(pd, "XenonRecomp.exe"), "wb").write(b"\0" * 5000)      # herramienta: se ignora
open(os.path.join(pd, "CrashOTT.exe"), "wb").write(b"\0" * 20000)        # el juego: el mayor que no es tool
check(cp.locate_built_exe(port).endswith("CrashOTT.exe"), "elige el .exe del juego, no XenonRecomp.exe")
check(cp.is_built(port) is True, "is_built detecta que ya hay .exe")

print("Envuelve el .exe con las comodidades de ReForge (lanzador, icono, Biblioteca)")
hechos = {"launcher": None, "icon": None, "lib": []}


def fake_launcher(exe, root, title):
    hechos["launcher"] = (exe, title)
    return os.path.join(os.path.dirname(exe), "Jugar.bat")


def fake_icon(exe, root, title, force=False):
    hechos["icon"] = title
    return "icono aplicado"


class FakeLib:
    def upsert(self, p):
        hechos["lib"].append(p)

    def save(self):
        pass


gr = tempfile.mkdtemp()
proj = cp.wrap_in_reforge(port, cp.locate_built_exe(port), gr, lib=FakeLib(),
                          write_launcher=fake_launcher, ensure_icon=fake_icon)
check(proj is not None and proj.title_id == "565507E4", "crea el Project del puerto")
check(hechos["launcher"] is not None and port.name in hechos["launcher"][1], "le pone el lanzador temático de ReForge")
check(hechos["icon"] == port.name, "le pone el icono")
check(len(hechos["lib"]) == 1, "lo añade a la Biblioteca")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
