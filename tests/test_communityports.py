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
check(hechos["launcher"] is not None and port.play_name in hechos["launcher"][1],
      "le pone el lanzador temático de ReForge con el nombre bonito")
check(hechos["icon"] == port.play_name, "le pone el icono")
check(len(hechos["lib"]) == 1, "lo añade a la Biblioteca")

print("Nombres bonitos y carpetas de salida conocidas")
check(forza.play_name == "Forza Horizon" and forza.exe_base == "Horizon", "Forza Horizon → Horizon")
check(port.play_name == "Crash of the Titans", "Crash tiene nombre de juego")
check(any("win-amd64-release" in d for d in forza.known_dirs), "conoce la carpeta de salida de Pinyon Shift")

print("Recordar / olvidar la ruta del .exe")
cp.remember_exe(forza, os.path.join(pd, "CrashOTT.exe"))
check(cp.saved_exe(forza).endswith("CrashOTT.exe"), "recuerda la ruta elegida")
cp.forget_exe(forza)
check(cp.saved_exe(forza) == "", "la olvida cuando toca")

print("Renombrar el .exe del puerto al nombre bonito (conserva el icono embebido)")
rtmp = tempfile.mkdtemp()
src_exe = os.path.join(rtmp, "pinyon_shift.exe")
open(src_exe, "wb").write(b"\0" * 1000)
ok, new = cp.rename_built(forza, src_exe)
check(ok and os.path.basename(new) == "Horizon.exe", "pinyon_shift.exe → Horizon.exe")
check(not os.path.isfile(src_exe) and os.path.isfile(new), "mueve el archivo, no lo duplica")
check(cp.saved_exe(forza) == new, "recuerda la nueva ruta")

print("find_installed detecta el puerto instalado a mano en una carpeta conocida")
kd = tempfile.mkdtemp()
open(os.path.join(kd, "pinyon_shift.exe"), "wb").write(b"\0" * 60000)
forza.known_dirs = [kd]
cp.forget_exe(forza)
found = cp.find_installed(forza)
check(found.endswith("pinyon_shift.exe"), "lo encuentra en la carpeta de salida conocida")
check(cp.saved_exe(forza) == found, "y lo recuerda para «Jugar»")

print("install_build sin instalador ejecutable devuelve el plan, no un falso éxito")
ok2, msg2 = cp.install_build(forza, game_dir="", launch=False)
check(ok2 is False and "releases" in msg2.lower(), "es honesto cuando no hay instalador que lanzar")

print("launch usa el lanzador generado (con --game_data_root), no el .exe pelado")
ltmp = tempfile.mkdtemp()
lexe = os.path.join(ltmp, "Horizon.exe")
open(lexe, "wb").write(b"\0" * 100)
# sin lanzador aún: cae al .exe; sin proyecto del juego, sin args (y lo avisa)
mode, target, largs = cp.launch_plan(forza, lexe)
check(mode == "exe" and target == lexe, "sin lanzador, apunta al .exe")
# con el lanzador .bat de ReForge al lado: lo prefiere
open(os.path.join(ltmp, "Jugar Forza Horizon.bat"), "w").write("@echo off")
open(os.path.join(ltmp, "Jugar Forza Horizon (directo).bat"), "w").write("@echo off")
mode2, target2, _ = cp.launch_plan(forza, lexe)
check(mode2 == "launcher" and target2.endswith("Jugar Forza Horizon.bat"),
      "con el lanzador al lado, lo usa (lleva --game_data_root y el puente con ReForge)")
check(cp.launcher_bat(lexe).endswith("Jugar Forza Horizon.bat"), "prefiere el lanzador principal, no el (directo)")

print("Puente: agregar puertos desde GitHub y abrir su runtime original")
before = len(cp.all_ports())
up = cp.add_user_port("Mi Puerto Test", repo="https://github.com/autor/mi-puerto", title_id="ABCD1234")
check(up.id and up.repo.endswith("mi-puerto"), "add_user_port crea el puerto con su repo")
check(len(cp.all_ports()) == before + 1, "aparece junto a los preconfigurados")
check(cp.by_id(up.id) is not None and cp.is_user_port(cp.by_id(up.id)), "se reconoce como puerto del usuario")
check(cp.for_title("ABCD1234").id == up.id, "se encuentra por Title ID")

# abrir el runtime original: sin ejecutable elegido, avisa; con uno, lo abre (sin añadir args)
ok3, msg3 = cp.open_original(up)
check(ok3 is False and "Elegir runtime" in msg3, "sin runtime elegido, pide elegirlo (no lanza nada)")
rt = tempfile.mkdtemp()
orig = os.path.join(rt, "AuthorLauncher.exe")
open(orig, "wb").write(b"\0" * 100)
abierto = {}
cp.subprocess.Popen = lambda args, **k: abierto.update(args=args)
ok4, _ = cp.open_original(up, orig)
check(ok4 and abierto.get("args", [None])[0] == orig, "abre el runtime original tal cual (su propio .exe/lanzador)")
check(cp.saved_exe(up) == orig, "recuerda la ruta del runtime")

check(cp.remove_user_port(up.id) is True and cp.by_id(up.id) is None, "se puede quitar de la lista")

print("apply_title_update delega en title_update.install_update")
import reforge.title_update as tu  # noqa: E402
llamado = {}
tu.install_update = lambda root, src, log=None: llamado.update(root=root, src=src) or {"version": "1.2"}
info = cp.apply_title_update("/proyecto/forza", "/downloads/FHL-DLC-TU-GOD")
check(llamado.get("src", "").endswith("FHL-DLC-TU-GOD") and info["version"] == "1.2",
      "aplica la actualización (español latino) al proyecto del juego")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
