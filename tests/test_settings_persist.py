"""Los ajustes del juego y sus datos se encuentran igual al abrir el .exe desde otro directorio."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge.game_options import GameOptions, runtime_config_path  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


root = os.path.abspath(tempfile.mkdtemp())
os.makedirs(os.path.join(root, "assets"), exist_ok=True)
os.makedirs(os.path.join(root, "build"), exist_ok=True)
exe = os.path.join(root, "build", "asuraswrath.exe")
open(exe, "wb").write(b"\0")

print("Los ajustes se guardan en el proyecto (ruta absoluta), no dependen del directorio actual")
o = GameOptions()
o.fullscreen = True
o.resolution_scale = 2          # render interno 2× (distinto del valor por defecto, prueba persistencia real)
o.input_backend = "xinput"
o.save(root)

# cambiar el directorio de trabajo a otro sitio y volver a cargar por la ruta absoluta del proyecto
otro = tempfile.mkdtemp()
old = os.getcwd()
try:
    os.chdir(otro)
    reload = GameOptions.load(root)
    check(reload.fullscreen is True and reload.resolution_scale == 2 and reload.input_backend == "xinput",
          "abrir desde otro directorio conserva los ajustes (se cargan por la ruta del proyecto)")
    check(os.path.isabs(runtime_config_path(exe)),
          "la config del runtime vive junto al .exe con ruta absoluta: se encuentra desde cualquier directorio")
finally:
    os.chdir(old)

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
