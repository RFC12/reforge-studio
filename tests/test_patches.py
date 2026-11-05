"""Pruebas del sistema de parches y del parche Utilidades Xbox.  python tests/test_patches.py"""
import hashlib
import json
import os
import struct
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-test-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "patches", "xbox_utility"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from make_patch import build  # noqa: E402
from reforge.patches import PatchError, PatchManager, check_requirement  # noqa: E402
from reforge.xiso import XisoImage  # noqa: E402
from xbe import read_xbe_info  # noqa: E402
from xiso_writer import create_xiso  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


def make_patch_dir(pid, version, api=1, req=">=1.1.0", body="def register(api): pass\n"):
    d = os.path.join(TMP, "src", f"{pid}-{version}")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.json"), "w") as f:
        json.dump({"id": pid, "name": pid, "version": version, "api": api, "requires_core": req,
                   "entry": "plugin.py"}, f)
    with open(os.path.join(d, "plugin.py"), "w") as f:
        f.write(body)
    return build(d, os.path.join(TMP, "dist"))


print("Requisitos de versión")
check(check_requirement(">=1.1.0,<2.0.0", "1.1.0"), "1.1.0 cumple >=1.1.0,<2.0.0")
check(not check_requirement(">=1.1.0,<2.0.0", "2.0.0"), "2.0.0 no cumple <2.0.0")
check(not check_requirement(">=1.2", "1.1.9"), "1.1.9 no cumple >=1.2")

print("Instalación, actualización y reversión")
pm = PatchManager("1.1.0", {1})
real = build(os.path.join(ROOT, "patches", "xbox_utility"), os.path.join(TMP, "dist"))
info = pm.install(real)
check(info.id == "xbox-utility" and info.status, "parche real instalado")
p1 = make_patch_dir("demo", "1.0.0")
p2 = make_patch_dir("demo", "1.1.0")
pm.install(p1)
pm.install(p2)
pm.scan()
check(pm.patches["demo"].version == "1.1.0" and pm.patches["demo"].has_backup == "1.0.0",
      "actualización guarda copia de la versión anterior")
pm.rollback("demo")
check(pm.patches["demo"].version == "1.0.0", "revertir vuelve a la v1.0.0")

print("Protecciones")
bad = os.path.join(TMP, "dist", "tampered.rfpatch")
with zipfile.ZipFile(p2) as a, zipfile.ZipFile(bad, "w") as b:
    for n in a.namelist():
        b.writestr(n, a.read(n) + (b"#x" if n == "plugin.py" else b""))
try:
    pm.install(bad)
    raise AssertionError("aceptó un parche manipulado")
except PatchError:
    check(True, "rechaza parche manipulado (SHA-256)")
evil = os.path.join(TMP, "dist", "evil.rfpatch")
with zipfile.ZipFile(evil, "w") as z:
    data = b"x"
    z.writestr("manifest.json", json.dumps({"id": "evil", "name": "e", "version": "1", "api": 1,
                                            "requires_core": "", "entry": "plugin.py",
                                            "files": {"../../escape.py": hashlib.sha256(data).hexdigest(),
                                                      "plugin.py": hashlib.sha256(data).hexdigest()}}))
    z.writestr("../../escape.py", data)
    z.writestr("plugin.py", data)
try:
    pm.install(evil)
    raise AssertionError("aceptó ruta peligrosa")
except PatchError:
    check(True, "rechaza rutas que escapan de la carpeta")
fut = make_patch_dir("future", "1.0", api=2)
new, _old, why = pm.inspect(fut)
check(bool(why), "detecta parche incompatible (API v2)")


class FakeAPI:
    def __init__(self):
        self.rolled = False

    def _rollback(self):
        self.rolled = True


broken = make_patch_dir("broken", "1.0", body="def register(api):\n    raise RuntimeError('boom')\n")
pm.install(broken)
pm.install(fut)
pm.set_enabled("xbox-utility", False)   # su interfaz necesita Qt; aquí se prueba solo el cargador
apis = {}
pm.load_all(lambda i: apis.setdefault(i.id, FakeAPI()))
check(pm.patches["broken"].status == "error" and apis["broken"].rolled, "parche roto aislado y revertido")
check(pm.patches["future"].status == "incompatible", "parche incompatible no se carga")
check(pm.patches["demo"].status == "activo", "los demás parches siguen activos")
with open(pm.flag_path, "w") as f:
    f.write("demo")
pm2 = PatchManager("1.1.0", {1})
check(pm2.check_crash_guard() == "demo", "guardia anti-caídas identifica el parche")
pm2.scan()
check(not pm2.patches["demo"].enabled, "el parche culpable queda desactivado")

print("Creador de ISO y XBE")
src = os.path.join(TMP, "game")
os.makedirs(os.path.join(src, "media", "deep"))
x = bytearray(0x400)
x[0:4] = b"XBEH"
struct.pack_into("<I", x, 0x104, 0x10000)
struct.pack_into("<I", x, 0x118, 0x10200)
struct.pack_into("<I", x, 0x208, 0x4D530004)
t = "Juego Clásico".encode("utf-16-le")
x[0x20C:0x20C + len(t)] = t
open(os.path.join(src, "default.xbe"), "wb").write(bytes(x))
for i in range(300):
    open(os.path.join(src, "media", "deep" if i % 3 else "", f"f{i:03d}_{'z' * (i % 25)}.dat"), "wb").write(
        os.urandom(i * 37))
iso = os.path.join(TMP, "game.iso")
create_xiso(src, iso)
with XisoImage(iso) as img:
    img.extract(os.path.join(TMP, "back"))


def digest(r):
    out = {}
    for dp, _d, fn in os.walk(r):
        for f in fn:
            out[os.path.relpath(os.path.join(dp, f), r)] = hashlib.md5(open(os.path.join(dp, f), "rb").read()).hexdigest()
    return out


check(digest(src) == digest(os.path.join(TMP, "back")), "ISO creada → extraída es idéntica (301 archivos)")
xi = read_xbe_info(os.path.join(src, "default.xbe"))
check(xi["title"] == "Juego Clásico" and xi["title_id"] == "4D530004", "lee título y Title ID del XBE")

print("Entorno rexglue (núcleo)")
os.environ["REFORGE_TOOLS_DIR"] = os.path.join(TMP, "tools")
from reforge import toolchain as rsdk  # noqa: E402
from reforge.core import AppConfig, manifest_project_name, rexglue_init_cmd  # noqa: E402
proj = os.path.join(TMP, "proj")
os.makedirs(proj)
with open(os.path.join(proj, "angrybirdstrilogy_manifest.toml"), "w") as f:
    f.write('# x\n\n[project]\nname = "angrybirdstrilogy"\nsdk_version = "0.10.0"\n\n[entrypoint]\nfile_path = "a"\n')
check(manifest_project_name(proj) == "angrybirdstrilogy", "target de codegen leído del manifiesto")
check(rsdk.version_from_zip_name("rexglue-sdk-0.10.0.24-dev.gbd833a2-win-amd64.zip") == "0.10.0.24-dev.gbd833a2",
      "versión deducida del nombre del zip")
zp = os.path.join(TMP, "rexglue-sdk-9.9.9-" + rsdk.platform_tag() + ".zip")
exe_name = "rexglue.exe" if sys.platform == "win32" else "rexglue"
with zipfile.ZipFile(zp, "w") as z:
    z.writestr(f"{rsdk.platform_tag()}/bin/{exe_name}", b"#!/bin/sh\necho 9.9.9\n")
    z.writestr(f"{rsdk.platform_tag()}/lib/cmake/rexglue/rexglueConfig.cmake", b"")


class Ctx:
    def progress(self, *a):
        pass

    def cancelled(self):
        return False


prefix, exe = rsdk.install_zip(zp, "9.9.9", Ctx())
check(os.path.isfile(exe) and os.path.isdir(os.path.join(prefix, "lib")), "SDK instalado desde zip")
check(rsdk.installed_sdks()[0][0] == "9.9.9", "SDK aparece en la lista de instalados")
cfg = AppConfig()
cfg.rexglue = exe
check(cfg.sdk_prefix() == prefix and cfg.environment()["CMAKE_PREFIX_PATH"].startswith(prefix),
      "CMAKE_PREFIX_PATH apunta al SDK")
cmd = rexglue_init_cmd(cfg, "angry_birds_trilogy", "/p/abt")
check("--xex-path" in cmd and "--project-name" in cmd, "init usa la CLI actual (--project-name/--xex-path)")
cfg.cli_flavor = "app"
check("--app_name" in rexglue_init_cmd(cfg, "x", "/p/x"), "init admite la CLI antigua")

print("Codegen con corrección automática y ejecución")
from reforge import game  # noqa: E402
lines = ["UnresolvedCall (2):",
         "  0x82478B30 from 0x82471480: b 0x82478B30 from 0x82471480 - target not in any function",
         "  0x824E46D0 from 0x824D389C: b 0x824E46D0 from 0x824D389C - target not in any function"]
u = game.parse_unresolved(lines)
check([t for t, _s in u] == [0x82478B30, 0x824E46D0], "detecta llamadas no resueltas del log de rexglue")
p2 = os.path.join(TMP, "proj2")
os.makedirs(p2)
with open(os.path.join(p2, "x_manifest.toml"), "w") as f:
    f.write('[project]\nname = "x"\n\n[entrypoint]\nfile_path = "a"\nincludes = []\n\n[[modules]]\nincludes = []\n')
game.ensure_include(p2)
mtxt = open(os.path.join(p2, "x_manifest.toml")).read()
check('[entrypoint]\nfile_path = "a"\nincludes = ["reforge_functions.toml"]' in mtxt and mtxt.count("reforge_functions") == 1,
      "el include se añade solo a [entrypoint]")
check(len(game.add_functions(p2, u)) == 2 and game.add_functions(p2, u) == [], "funciones declaradas sin duplicar")
b2 = os.path.join(p2, "build")
os.makedirs(b2)
with open(os.path.join(b2, "CMakeCache.txt"), "w") as f:
    f.write("CMAKE_CXX_COMPILER:FILEPATH=C:/VS/bin/cl.exe\nCMAKE_GENERATOR:INTERNAL=Ninja\n")
c2 = AppConfig()
c2.cxx_compiler, c2.generator = r"C:\LLVM\bin\clang++.exe", "Ninja"
check(bool(game.cache_mismatch(c2, b2)), "detecta build configurado con MSVC")
game.reset_cache(b2)
check(not os.path.exists(os.path.join(b2, "CMakeCache.txt")), "borra solo la caché de CMake")
check(game.launch_args("/g/x.exe", "/p")[1] == "--game_data_root=" + os.path.join("/p", "assets"),
      "el juego recibe --game_data_root=<assets>")

print(f"\nTodas las pruebas pasaron ({ok}).")
