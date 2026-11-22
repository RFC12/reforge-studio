"""Precompilado de shaders al cargar (AOT): parche de SDK + opción/cvar."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import sdk_patch as P                        # noqa: E402
from reforge.game_options import GameOptions, ADVANCED_CVARS   # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


# Fuente sintética con las mismas anclas que el rexglue real (no depende del clon del SDK).
SETTINGS = '''namespace rex::gpu {
class XenosSettings : public SettingOwner {
  REX_SETTING(bool, store_shaders, true,
              "Keep compiled shaders on disk and load them on later runs to avoid stutter");
  REX_SETTING(bool, mrt_edram_used_range_clamp_to_min, true, "x");
};
}
'''
DRIVER = '''Result<void> XenosGraphicsDriverBase::AttachTitle() {
  if (const std::filesystem::path cache_root = REX_PATHS().cache_root.Get(); !cache_root.empty()) {
    REX_TRY_VOID(InitializeShaderStorage(cache_root, title_info_.title_id, false));
  }
  return Ok();
}
'''

print("Parche apply_shader_prewarm")
d = tempfile.mkdtemp()
for rel, txt in (("src/gpu/xenos/xenos_settings.h", SETTINGS),
                 ("src/gpu/xenos/xenos_graphics_driver_base.cpp", DRIVER)):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(txt)

check(P.apply_shader_prewarm(d) is True, "aplica la primera vez")
check(P.apply_shader_prewarm(d) is False, "es idempotente (no reaplica)")
s = open(os.path.join(d, "src/gpu/xenos/xenos_settings.h"), encoding="utf-8").read()
c = open(os.path.join(d, "src/gpu/xenos/xenos_graphics_driver_base.cpp"), encoding="utf-8").read()
check("REX_SETTING(bool, shader_storage_blocking, false" in s, "añade el cvar shader_storage_blocking")
check("InitializeShaderStorage(cache_root, title_info_.title_id, shader_storage_blocking.Get())" in c,
      "la llamada de arranque pasa a usar el cvar")
check("title_info_.title_id, false))" not in c, "ya no queda el 'false' fijo")

print("Parche se salta limpio si el SDK no tiene esos archivos")
vacio = tempfile.mkdtemp()
try:
    P.apply_shader_prewarm(vacio)
    check(False, "debería lanzar PatchFileMissing")
except P.PatchFileMissing:
    check(True, "lanza PatchFileMissing (apply_all lo saltará sin abortar)")

print("Opción → cvar en runtime_values")
o = GameOptions()
o.shader_prewarm = True
check(o.runtime_values().get("shader_storage_blocking") is True, "shader_prewarm=True escribe el cvar")
check(GameOptions().runtime_values().get("shader_storage_blocking") is True, "por defecto (AOT activado) escribe el cvar")
off = GameOptions()
off.shader_prewarm = False
check("shader_storage_blocking" not in off.runtime_values(), "desactivado no lo escribe")
check("shader_storage_blocking" in ADVANCED_CVARS, "está en ADVANCED_CVARS (solo si el SDK lo soporta)")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
