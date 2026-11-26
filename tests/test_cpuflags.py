"""Flags de compilación del código recompilado: -ffp-contract=off siempre (precisión FP, de ShiftGlue) y los
niveles de CPU (compatible / moderno x86-64-v3 / nativo)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import core  # noqa: E402
from reforge.game_options import GameOptions  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


class Cfg:
    build_type = "Release"
    generator = "Ninja"
    c_compiler = ""
    cxx_compiler = ""
    ninja = ""
    extra_cmake_args = ""

    def tool(self, _name):
        return "cmake"


def cxx_flags(root):
    for a in core.cmake_configure_cmd(Cfg(), root, os.path.join(root, "build")):
        if a.startswith("-DCMAKE_CXX_FLAGS="):
            return a[len("-DCMAKE_CXX_FLAGS="):]
    return None


root = tempfile.mkdtemp()

print("Precisión FP: -ffp-contract=off va siempre, incluso sin tocar nada")
GameOptions().save(root)
f = cxx_flags(root)
check(f is not None and "-ffp-contract=off" in f, "incluye -ffp-contract=off por defecto (como el Xbox 360)")
check("march" not in f, "sin baseline elegido no añade -march")

print("CPU moderna → x86-64-v3 + FMA, manteniendo la precisión FP")
o = GameOptions.load(root)
o.cpu_baseline = "moderno"
o.save(root)
f = cxx_flags(root)
check("-march=x86-64-v3" in f and "-mfma" in f and "-ffp-contract=off" in f, "AVX2/FMA portable + precisión FP")

print("CPU de este PC → -march=native")
o.cpu_baseline = "nativo"
o.save(root)
check("-march=native" in cxx_flags(root), "compila para este procesador")

print("Compat: la opción antigua cpu_native sigue valiendo")
o.cpu_baseline = ""
o.cpu_native = True
o.save(root)
check("-march=native" in cxx_flags(root), "cpu_native=True aún da -march=native")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
