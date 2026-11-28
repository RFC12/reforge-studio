"""Selección y generación del runtime al recompilar: el runtime que ReForge elige/genera lleva el fix
utf8.   python tests/test_runtime_selection.py

Cubre las dos mitades de «el usuario pulsa Recompilar → Jugar y entra con sus DLC sin tocar nada»:
  A) GENERACIÓN: el pipeline de parches del SDK (apply_all, que corre fidelityfx.build al crear la
     variante -fsr) aplica el parche utf8 → el rexruntime.dll generado trae el fix. Y es imprescindible:
     si un ancla se rompe, la generación se detiene en vez de producir un runtime que casca.
  B) SELECCIÓN: ensure_compatible (paso previo a «Configurar CMake») elige, entre los SDK instalados que
     proveen rex::runtime, la variante -fsr (la que ReForge compila con los parches → la que trae el fix).
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from reforge import sdk_patch, sdkcompat  # noqa: E402
from reforge import toolchain  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


def _sdk_src_with_utf8():
    src = tempfile.mkdtemp(prefix="reforge-gen-")
    dst = os.path.join(src, "src", "core")
    os.makedirs(dst)
    shutil.copyfile(os.path.join(ROOT, "tests", "fixtures_utf8.cpp"), os.path.join(dst, "utf8.cpp"))
    return src


# ----------------------------------------------------------------------------- A) generación
print("A) El pipeline que genera el runtime (apply_all) incluye el fix utf8")
src = _sdk_src_with_utf8()
changed, aplicados, saltados = sdk_patch.apply_all(src)
check(changed, "apply_all cambia el árbol del SDK")
check("nombres de contenido UTF-8 inválidos no tumban el runtime" in aplicados,
      "el parche utf8 está entre los aplicados al generar el runtime")
u8 = open(os.path.join(src, "src", "core", "utf8.cpp"), encoding="utf-8").read()
check("class utf8_citer" in u8 and "utfcpp::replace_invalid(source.begin()" in u8,
      "el utf8.cpp generado lleva el iterador tolerante y to_utf16 tolerante")

print("A2) El fix es imprescindible: un ancla rota detiene la generación (no envía un runtime que casca)")
src_roto = _sdk_src_with_utf8()
p = os.path.join(src_roto, "src", "core", "utf8.cpp")
txt = open(p, encoding="utf-8").read().replace("return utfcpp::utf8to16(source);",
                                               "return utfcpp::utf8to16(source);  // reorganizado")
open(p, "w", encoding="utf-8").write(txt)
try:
    sdk_patch.apply_all(src_roto)
    raise AssertionError("apply_all debió propagar el error del parche imprescindible")
except sdk_patch.PatchError:
    check(True, "ancla utf8 rota → apply_all se detiene (parche imprescindible)")


# ----------------------------------------------------------------------------- B) selección
def _sdk_prefix(*targets):
    p = tempfile.mkdtemp(prefix="reforge-sdk-")
    d = os.path.join(p, "lib", "cmake", "rexglue")
    os.makedirs(d)
    with open(os.path.join(d, "rexglueTargets.cmake"), "w", encoding="utf-8") as f:
        f.write("\n".join(f"add_library({t} SHARED IMPORTED)" for t in targets))
    return p


def _project(target="rex::runtime"):
    root = tempfile.mkdtemp(prefix="reforge-proj-")
    os.makedirs(os.path.join(root, "generated"))
    with open(os.path.join(root, "generated", "rexglue.cmake"), "w", encoding="utf-8") as f:
        f.write(f"target_link_libraries(juego PRIVATE {target})\n")
    return root


class FakeCfg:
    def __init__(self, prefix):
        self._prefix = prefix
        self.rexglue = ""
        self.rexglue_sdk = ""

    def sdk_prefix(self):
        return self._prefix

    def path(self):
        return os.path.join(tempfile.mkdtemp(), "config.json")  # no existe → no intenta respaldar

    def save(self):
        pass

    def environment(self):
        return {"CMAKE_PREFIX_PATH": self._prefix}


class FakeCtx:
    def __init__(self):
        self.msgs = []

    def log(self, msg, *a, **k):
        self.msgs.append(msg)


print("B) ensure_compatible elige la variante -fsr (la que ReForge compila con los parches → con el fix)")
# SDK seleccionado ahora: 0.11, que renombró el target (ya no provee rex::runtime) → incompatible.
sdk011 = _sdk_prefix("rexglue::runtime")
# Instalados que SÍ proveen rex::runtime: uno normal y la variante -fsr.
pfx_plain = _sdk_prefix("rex::runtime")
pfx_fsr = _sdk_prefix("rex::runtime")
exe_plain = os.path.join(pfx_plain, "bin", "rexglue")
exe_fsr = os.path.join(pfx_fsr, "bin", "rexglue")

orig_installed = toolchain.installed_sdks
toolchain.installed_sdks = lambda: [
    ("0.10.0.24-dev.gbd833a2", pfx_plain, exe_plain),
    ("0.10.0.24-dev.gbd833a2-fsr", pfx_fsr, exe_fsr),
]
try:
    cfg = FakeCfg(sdk011)
    root = _project("rex::runtime")
    build = tempfile.mkdtemp(prefix="reforge-build-")
    open(os.path.join(build, "CMakeCache.txt"), "w").write("stale\n")
    env = {}
    ctx = FakeCtx()
    sdkcompat.ensure_compatible(cfg, root, build, env, ctx)
    check(cfg.rexglue_sdk == pfx_fsr, "cambia a la variante -fsr (prefiere FSR a igualdad de versión)")
    check(cfg.rexglue == exe_fsr, "apunta al rexglue de la variante -fsr")
    check(not os.path.isfile(os.path.join(build, "CMakeCache.txt")),
          "limpia la caché de CMake para que la recompilación use el runtime nuevo")
finally:
    toolchain.installed_sdks = orig_installed

print("B2) Si el SDK ya es compatible, no toca nada (no fuerza cambios)")
cfg_ok = FakeCfg(_sdk_prefix("rex::runtime"))
ok_flag, needed, prefix = sdkcompat.check(cfg_ok, _project("rex::runtime"))
check(ok_flag is True and needed == {"rex::runtime"}, "SDK que provee rex::runtime pasa sin cambios")


# ----------------------------------------------------------------------------- C) SDK -fsr en caché
# El agujero de "instalación con un -fsr anterior": ReForge solo compila el runtime con los parches cuando
# construye el -fsr. Si ya hay uno instalado (compilado antes del fix), hay que detectarlo para ofrecer
# recompilarlo; si no, seguiría copiando un rexruntime.dll sin las correcciones.
from reforge import fidelityfx, sdk_patch  # noqa: E402

print("C) Un -fsr instalado con parches anteriores se detecta como desfasado")
pfx = tempfile.mkdtemp(prefix="reforge-fsr-")
check(fidelityfx.patchset_of(pfx) == 0, "sin marca → patchset 0 (desconocido)")
check(fidelityfx.fsr_outdated("0.10.0.24-dev.gbd833a2-fsr", pfx) is True,
      "-fsr sin marca → desfasado (hay que recompilarlo para traer el fix)")
with open(os.path.join(pfx, fidelityfx.PATCHSET_MARKER), "w", encoding="utf-8") as f:
    f.write("1")
check(fidelityfx.fsr_outdated("0.10.0.24-dev.gbd833a2-fsr", pfx) is True,
      "-fsr con patchset 1 < actual → desfasado")
with open(os.path.join(pfx, fidelityfx.PATCHSET_MARKER), "w", encoding="utf-8") as f:
    f.write(str(sdk_patch.PATCHSET_VERSION))
check(fidelityfx.patchset_of(pfx) == sdk_patch.PATCHSET_VERSION, "lee la marca de patchset grabada")
check(fidelityfx.fsr_outdated("0.10.0.24-dev.gbd833a2-fsr", pfx) is False,
      "-fsr al día (patchset == actual) → NO desfasado")
check(fidelityfx.fsr_outdated("0.10.0.24-dev.gbd833a2", pfx) is False,
      "un SDK que no es -fsr nunca se marca como desfasado por esto")

print(f"\nTodas las pruebas pasaron ({ok}).")
