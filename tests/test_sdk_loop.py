"""La caché de CMake no puede reconfigurarse en bucle cuando el SDK configurado no es el que el proyecto pide.

El Taller comparaba la carpeta del SDK de la caché con la que tiene configurada ReForge. En un proyecto 0.11
con ReForge apuntando al 0.10, CMake resolvía el 0.11 (por el entorno), la comparación fallaba, se borraba la
caché... y en la siguiente pasada volvía a pasar: el juego se recompilaba entero una y otra vez.

python tests/test_sdk_loop.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from reforge import game  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


class Cfg:
    cxx_compiler = ""
    generator = ""
    ninja = ""

    def __init__(self, prefix):
        self.prefix = prefix

    def sdk_prefix(self):
        return self.prefix


def proyecto(sdk_version, pide):
    root = tempfile.mkdtemp(prefix="reforge-loop-")
    with open(os.path.join(root, "CMakeLists.txt"), "w", encoding="utf-8") as f:
        f.write(f"find_package(rexglue {pide} REQUIRED CONFIG)\n")
    build = os.path.join(root, "build")
    sdk = os.path.join(root, "sdk", "0.11.0.13-dev.g115171b4-fsr", "win-amd64")   # otra instalación, misma versión
    cmake = os.path.join(sdk, "lib", "cmake", "rexglue")
    os.makedirs(cmake)
    os.makedirs(build)
    with open(os.path.join(cmake, "rexglueConfigVersion.cmake"), "w", encoding="utf-8") as f:
        f.write(f'set(PACKAGE_VERSION "{sdk_version}")\n')
    with open(os.path.join(build, "CMakeCache.txt"), "w", encoding="utf-8") as f:
        f.write(f"rexglue_DIR:PATH={cmake.replace(os.sep, '/')}\n")
    return root, build


print("Otra instalación de la misma versión no obliga a recompilar")
root, build = proyecto("0.11.0.13", "0.11.0")
cfg = Cfg("C:/Users/x/ReForge Studio/tools/rexglue-sdk/0.10.0.24-dev.gbd833a2-fsr/win-amd64")
check(game.sdk_mismatch(cfg, build) == "", "el proyecto pide 0.11.0 y la caché tiene 0.11.0.13: se compila tal cual")
check(game.cache_mismatch(cfg, build) == "", "y el Taller no borra la caché")

print("Una versión que no sirve sí reconfigura, pero una sola vez")
root2, build2 = proyecto("0.10.0.24", "0.11.0")
why = game.sdk_mismatch(cfg, build2)
check(why.startswith("el SDK"), f"0.10 en la caché para un proyecto 0.11: {why!r}")
check(game.sdk_mismatch(cfg, build2) == "", "si CMake vuelve a elegir el mismo, no se repite (no hay bucle)")
check(game.cache_mismatch(cfg, build2) == "", "la segunda pasada del Taller ya no borra nada")

print("Un SDK más nuevo que el pedido también vale")
root3, build3 = proyecto("0.12.0.1", "0.11.0")
check(game.sdk_mismatch(cfg, build3) == "", "0.12.0.1 cumple lo que pide un proyecto 0.11.0")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
