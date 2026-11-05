"""Barrido completo: revisión de todas las capas.   python tests/test_sweep.py"""
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-sweep-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)
from reforge import game_options as go, sweep  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


root = os.path.join(TMP, "juego")
for d in ("assets/media", "build", "src"):
    os.makedirs(os.path.join(root, d))
x = bytearray(0x20000)
struct.pack_into(">4sIIII", x, 0, b"XEX2", 0, 0x1000, 0, 0x200)
open(os.path.join(root, "assets", "default.xex"), "wb").write(bytes(x))
open(os.path.join(root, "assets", "media", "nivel1.pak"), "wb").write(b"x" * 5000)
open(os.path.join(root, "assets", "media", "vacio.pak"), "wb").write(b"")
open(os.path.join(root, "build", "CMakeCache.txt"), "w").write(
    "CMAKE_BUILD_TYPE:STRING=Debug\nCMAKE_CXX_COMPILER:FILEPATH=C:/LLVM/bin/clang++.exe\n")
go.GameOptions().save(root)


class Cfg:
    build_type = "Debug"
    cxx_compiler = "clang++"
    saved = False

    def save(self):
        self.saved = True


print("Compilación")
cfg = Cfg()
rows = sweep.check_build(cfg, root)
check(cfg.build_type == "Release" and cfg.saved and rows[0][1] == sweep.FIXED,
      "modo Debug → Release (optimizaciones de C++) y se reconfigura")
check(not os.path.isfile(os.path.join(root, "build", "CMakeCache.txt")), "borra la caché para reconfigurar")
check(sweep.check_build(cfg, root)[0][1] == sweep.OK, "en Release: correcto")

print("XEX y archivos")
check(sweep.check_xex(root)[0][1] == sweep.OK, "XEX2 válido")
open(os.path.join(root, "assets", "default.xex"), "r+b").write(b"XBEH")
check(sweep.check_xex(root)[0][1] == sweep.FAIL, "XEX dañado o de otra consola → fallo")
a = sweep.check_assets(root)
check(any(st == sweep.WARN and "vacio.pak" in t for _l, st, t in a), "detecta archivos vacíos (extracción incompleta)")

print("Avisos del compilador")
lines = ["gen.cpp:10:5: warning: unused variable 'x' [-Wunused-variable]",
         "gen.cpp:20:1: warning: non-void function does not return a value [-Wreturn-type]",
         "gen.cpp:30:1: warning: variable 'r' is uninitialized when used here [-Wuninitialized]"]
d = sweep.audit_build_warnings(lines, os.path.join(root, "build"))
check(d["total"] == 3 and d["critical"] == {"Wreturn-type": 1, "Wuninitialized": 1}, "separa los avisos críticos")
w = sweep.check_warnings(root)
check(w[0][1] == sweep.WARN and "Wreturn-type" in w[0][2], "el informe los nombra")
sweep.audit_build_warnings(lines[:1], os.path.join(root, "build"))
check(sweep.check_warnings(root)[0][1] == sweep.OK, "solo avisos normales: correcto")

print("Procesador y funciones del sistema")
from reforge import optimizer  # noqa: E402
optimizer.cached_hardware = lambda: {"avx2": True}
r = sweep.check_cpu(root)
check(r[0][1] == sweep.FIXED and go.GameOptions.load(root).cpu_native, "AVX2 disponible → -march=native")
check(sweep.check_cpu(root)[0][1] == sweep.OK, "ya activado: correcto")
gexe = os.path.join(root, "build", "juego.exe")
open(gexe, "w").write("")
os.makedirs(os.path.join(root, "build", "logs"))
open(os.path.join(root, "build", "logs", "juego_001.log"), "w").write(
    "[w] [krnl] __imp__NetDll_getsockopt STUB\n[e] [krnl] Unimplemented XLIVEBASE message app=FC\n")
check(sweep.check_stubs(gexe)[0][1] == sweep.OK, "solo red/Live sin implementar: normal")
open(os.path.join(root, "build", "logs", "juego_001.log"), "a").write("[w] [krnl] __imp__XAudioSubmitFrame STUB\n")
st = sweep.check_stubs(gexe)
check(st[0][1] == sweep.WARN and "XAudioSubmitFrame" in st[0][2], "funciones del sistema que importan → aviso")

print("Mandos e informe")
check(sweep.check_input(root)[0][1] == sweep.OK, "mando revisado")
rep = sweep.format_report([("Capa", sweep.FIXED, "x"), ("Capa", sweep.FAIL, "y")])
check(rep[0].startswith("🔧") and rep[1].startswith("✖"), "informe con iconos por estado")
print(f"\nTodas las pruebas pasaron ({ok}).")
