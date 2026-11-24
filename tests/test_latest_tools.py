"""Al compilar se usan las versiones MÁS NUEVAS instaladas de VS, CMake, Ninja y Clang (y el SDK más nuevo).

Se comprueba que solo sube de versión (nunca degrada una configuración que funciona), que el SDK no cambia por
sorpresa en un proyecto ya compilado, y que Ninja llega a CMake de forma explícita.

   python tests/test_latest_tools.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from reforge import game, toolchain                      # noqa: E402
from reforge.core import AppConfig, cmake_configure_cmd  # noqa: E402

TMP = tempfile.mkdtemp(prefix="reforge-tools-")
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


def fake(rel):
    p = os.path.join(TMP, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write("")
    return p


cmake_old = fake("old/cmake/bin/cmake.exe")
cmake_new = fake("new/cmake/bin/cmake.exe")
clang_old = fake("old/llvm/bin/clang++.exe")
clang_new = fake("new/llvm/bin/clang++.exe")
clangc_old = fake("old/llvm/bin/clang.exe")
clangc_new = fake("new/llvm/bin/clang.exe")
ninja_old = fake("old/ninja/ninja.exe")
ninja_new = fake("new/ninja/ninja.exe")
vs_root_old = os.path.join(TMP, "vs17")
vs_root_new = os.path.join(TMP, "vs18")
os.makedirs(vs_root_old, exist_ok=True)
os.makedirs(vs_root_new, exist_ok=True)
vcvars_old = fake("vs17/VC/Auxiliary/Build/vcvars64.bat")
vcvars_new = fake("vs18/VC/Auxiliary/Build/vcvars64.bat")
sdk_old = os.path.join(TMP, "sdk", "0.10.0.24-dev.gbd833a2-fsr")
sdk_new = os.path.join(TMP, "sdk", "0.11.0.13-dev.g115171b4-fsr")
for sdk in (sdk_old, sdk_new):
    os.makedirs(os.path.join(sdk, "win-amd64", "bin"), exist_ok=True)
    open(os.path.join(sdk, "win-amd64", "bin", "rexglue.exe"), "w").close()

REAL_VERSIONS = toolchain._version_of
REAL_VS = toolchain.vs_installations
toolchain._version_of = lambda p: ((9, 0) if "new" in (p or "") else (1, 0)) if p else ()
toolchain.vs_installations = lambda: [
    {"path": vs_root_new, "vcvars": vcvars_new, "version": "18.4.0", "name": "VS 18"},
    {"path": vs_root_old, "vcvars": vcvars_old, "version": "17.14.0", "name": "VS 17"},
]

INFO = {
    "vs": {"path": vs_root_new, "vcvars": vcvars_new, "version": "18.4.0", "name": "VS 18"},
    "vcvars": vcvars_new,
    "cmake": {"path": cmake_new, "version": "4.3.1"},
    "ninja": {"path": ninja_new, "version": "1.13.2"},
    "clang": {"cc": clangc_new, "cxx": clang_new, "version": "23.1.3", "origin": "LLVM"},
    "sdk": {"version": "0.11.0.13-dev.g115171b4-fsr", "prefix": os.path.join(sdk_new, "win-amd64"),
            "exe": os.path.join(sdk_new, "win-amd64", "bin", "rexglue.exe")},
}

print("Solo sube de versión")
cfg = AppConfig(cmake=cmake_old, cxx_compiler=clang_old, c_compiler=clangc_old,
                vcvars=vcvars_old, ninja=ninja_old,
                rexglue_sdk=os.path.join(sdk_old, "win-amd64"),
                rexglue=os.path.join(sdk_old, "win-amd64", "bin", "rexglue.exe"))
changes, info = toolchain.upgrade_config(cfg, INFO, allow_sdk=False)
check(cfg.cmake == cmake_new, "CMake pasa al más nuevo")
check(cfg.ninja == ninja_new, "Ninja pasa al más nuevo")
check(cfg.cxx_compiler == clang_new and cfg.c_compiler == clangc_new, "Clang pasa al más nuevo (C y C++)")
check(cfg.vcvars == vcvars_new, "vcvars pasa a la instalación más nueva de Visual Studio")
check(cfg.rexglue_sdk == os.path.join(sdk_old, "win-amd64"),
      "en una build existente el SDK NO cambia solo (evita recompilar/romper el juego)")
check(toolchain.sdk_update_available(cfg, INFO) == "0.11.0.13-dev.g115171b4-fsr",
      "pero sí se informa de que hay un SDK más nuevo")
check(len(changes) == 4 and any("Clang" in c for c in changes), "se explican los cambios en el log")

cfg2 = AppConfig(cmake=cmake_new, cxx_compiler=clang_new, vcvars=vcvars_new, ninja=ninja_new)
before = (cfg2.cmake, cfg2.cxx_compiler, cfg2.ninja, cfg2.vcvars)
toolchain.upgrade_config(cfg2, INFO, allow_sdk=False)
check((cfg2.cmake, cfg2.cxx_compiler, cfg2.ninja, cfg2.vcvars) == before,
      "si ya está en la última versión no se toca nada")

print("Proyecto nuevo: SDK más nuevo")
cfg3 = AppConfig(rexglue_sdk=os.path.join(sdk_old, "win-amd64"),
                 rexglue=os.path.join(sdk_old, "win-amd64", "bin", "rexglue.exe"), cli_flavor="project")
toolchain.upgrade_config(cfg3, INFO, allow_sdk=True)
check(cfg3.rexglue_sdk == os.path.join(sdk_new, "win-amd64") and cfg3.rexglue.endswith("rexglue.exe"),
      "el proyecto nuevo se crea con el SDK más nuevo")
check(cfg3.cli_flavor == "", "se vuelve a detectar el CLI del SDK nuevo")

print("Versiones y Ninja explícito")
check(toolchain._sdk_key("0.11.0.13-dev.g115171b4") > toolchain._sdk_key("0.10.0.24-dev.gbd833a2"),
      "0.11 se considera más nuevo que 0.10 (orden numérico, no alfabético)")
check(toolchain._sdk_key("0.11.0.13-fsr") > toolchain._sdk_key("0.11.0.13"),
      "a igual versión se prefiere la variante FSR")
line = toolchain.describe(INFO)
check("CMake 4.3.1" in line and "Ninja 1.13.2" in line and "Clang 23.1.3" in line
      and "SDK 0.11.0.13" in line, f"la línea de herramientas es legible: {line}")

cfg4 = AppConfig(generator="Ninja", ninja=ninja_new, cmake=cmake_new)
cmd = cmake_configure_cmd(cfg4, TMP, os.path.join(TMP, "build"))
check(f"-DCMAKE_MAKE_PROGRAM={ninja_new}" in cmd, "CMake recibe la ruta explícita del Ninja más nuevo")

build = os.path.join(TMP, "proyecto", "build")
os.makedirs(build, exist_ok=True)
with open(os.path.join(build, "CMakeCache.txt"), "w", encoding="utf-8") as f:
    f.write("CMAKE_GENERATOR:INTERNAL=Ninja\n")
    f.write(f"CMAKE_MAKE_PROGRAM:FILEPATH={ninja_old}\n")
check(game.cache_mismatch(AppConfig(generator="Ninja", ninja=ninja_new), build) == "",
      "solo cambia la RUTA de Ninja: no se borra la caché (no se recompila todo el juego sin motivo)")

print("Detección real (sin depender de lo instalado)")
real = toolchain.latest()
check(isinstance(real, dict) and {"vs", "cmake", "ninja", "clang", "sdk"} <= set(real),
      "latest() devuelve todas las piezas aunque falten herramientas")
check(toolchain.installed_sdks() == sorted(toolchain.installed_sdks(),
                                           key=lambda t: toolchain._sdk_key(t[0]), reverse=True),
      "los SDK instalados salen ordenados del más nuevo al más viejo")

toolchain._version_of = REAL_VERSIONS
toolchain.vs_installations = REAL_VS
shutil.rmtree(TMP, ignore_errors=True)
print(f"\nTodas las pruebas pasaron ({ok}).")
