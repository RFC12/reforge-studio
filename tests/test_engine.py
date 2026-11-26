"""Perfil por motor (Unreal Engine 3…), idioma automático y compilación para tu CPU.
   python tests/test_engine.py"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-engine-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)

from reforge import engine, game_options as go  # noqa: E402
from reforge.core import AppConfig, cmake_configure_cmd  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


def gears(root):
    """Estructura real de Gears of War 2 (Unreal Engine 3), sin contenido."""
    for rel in ["default.xex", "Coalesced.pad", "GearGame/Xbox360TOC.txt", "GearGame/Xbox360TOC_ESM.txt",
                "GearGame/Xbox360TOC_FRA.txt", "GearGame/CookedXenon/Coalesced_esm.bin",
                "GearGame/CookedXenon/Coalesced_esn.bin", "GearGame/CookedXenon/Coalesced_int.bin",
                "GearGame/CookedXenon/Coalesced_deu.bin", "GearGame/CookedXenon/Core.xxx",
                "GearGame/CookedXenon/Engine.xxx", "GearGame/Movies/EpicLogo.bik"]:
        p = os.path.join(root, "assets", *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(b"x")


print("Motor del juego")
gow = os.path.join(TMP, "gow")
gears(gow)
check(engine.detect_engine(gow) == "ue3", "Gears of War 2 → Unreal Engine 3")
other = os.path.join(TMP, "otro")
os.makedirs(os.path.join(other, "assets", "data"))
open(os.path.join(other, "assets", "data", "level1.bin"), "wb").write(b"x")
check(engine.detect_engine(other) == "generic", "un juego sin pistas → genérico (sin cambios)")
cod = os.path.join(TMP, "cod")
os.makedirs(os.path.join(cod, "assets", "zone", "english"))
for n in ("common_mp.ff", "code_post_gfx.ff", "patch.ff"):
    open(os.path.join(cod, "assets", "zone", "english", n), "wb").write(b"x")
check(engine.detect_engine(cod) == "iw", "archivos .ff → IW Engine (Call of Duty)")

key = engine.apply_engine_profile(gow)
o = go.GameOptions.load(gow)
check(key == "ue3" and o.engine == "ue3" and o.allow_invalid_fetch, "aplica el perfil UE3 y lo recuerda")
check(engine.profile_values(o) == {"occlusion_query_enable": False}, "UE3: consultas de oclusión simuladas")
o.occlusion = "real"
check(engine.profile_values(o) == {"occlusion_query_enable": True}, "la elección manual manda")
o.occlusion = "auto"
o2 = go.GameOptions()
check(engine.profile_values(o2) == {}, "sin motor detectado no se toca nada")
exe = os.path.join(gow, "build", "gearsofwar2latino.exe")
os.makedirs(os.path.dirname(exe))
open(exe, "wb").write(b"")
open(os.path.join(gow, "build", "rexgpu-xenos.dll"), "wb").write(b"\0occlusion_query_enable\0")
go.write_runtime_config(exe, o)
check("occlusion_query_enable = false" in open(go.runtime_config_path(exe), encoding="utf-8").read(),
      "se escribe en el .toml del juego (el runtime la trae)")

print("Idioma: español de México en Unreal Engine 3")
check(5 in go.detect_languages(gow) and 1 in go.detect_languages(gow),
      "reconoce ESM/ESN/INT (códigos de Unreal) como español e inglés")
check("5:71" in go.detect_language_choices(gow) and "5:31" in go.detect_language_choices(gow),
      "ofrece Español (México / Latinoamérica) y de España")
os.environ["LANG"] = "es_CO.UTF-8"
if sys.platform != "win32":
    check(go.windows_language() == (5, 71), "Windows/sistema en español de América → español latino (México)")
    os.environ["LANG"] = "es_ES.UTF-8"
    check(go.windows_language() == (5, 31), "en español de España → España")
    os.environ["LANG"] = "es_CO.UTF-8"
n = go.GameOptions()
check(n.language == -1 and go.language_key(n) == "auto", "los juegos nuevos usan el idioma de Windows")
vals = n.runtime_values()
if sys.platform != "win32":
    check(vals.get("user_language") == 5 and vals.get("user_country") == 71, "y el juego recibe español + México")
go.set_language_key(n, "")
check(n.language == 0 and "user_language" not in n.runtime_values(), "«El que elija el juego» sigue disponible")
go.set_language_key(n, "5:71")
check(n.effective_language() == (5, 71), "elegir Español (México) a mano")

print("Compilar para tu CPU")
cfg = AppConfig()
cmd = cmake_configure_cmd(cfg, gow, os.path.join(gow, "build"))
check(any(a == "-DCMAKE_CXX_FLAGS=-ffp-contract=off" for a in cmd),
      "por defecto pasa -ffp-contract=off (precisión FP como el Xbox 360) y nada más")
o.cpu_native = True
o.save(gow)
check(any(a.startswith("-DCMAKE_CXX_FLAGS=") and "-march=native" in a and "-ffp-contract=off" in a
          for a in cmake_configure_cmd(cfg, gow, os.path.join(gow, "build"))),
      "activada: -march=native junto con la precisión FP")
cfg.extra_cmake_args = '-DCMAKE_CXX_FLAGS="-O2"'
check(sum(a.startswith("-DCMAKE_CXX_FLAGS") for a in cmake_configure_cmd(cfg, gow, os.path.join(gow, "build"))) == 1,
      "respeta las banderas que pongas tú en Ajustes")
print(f"\nTodas las pruebas pasaron ({ok}).")
