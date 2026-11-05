"""Mejoras para PC: FPS desbloqueados, correcciones gráficas y ritmo de fotogramas.
   python tests/test_pc_enhance.py"""
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-pc-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)

from reforge import cheats, game_options as go, pc_enhance as pe  # noqa: E402
from reforge.cheats import Patch  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


# Lo que trae la base de datos para Gears of War 2 (hash BDB97753374D520A, el de tu juego).
GOW2 = """title_name = "Gears of War 2"
title_id = "4D53082D"
hash = "BDB97753374D520A"

[[patch]]
    name = "Unlock FPS"
    is_enabled = false
    [[patch.be32]]
        address = 0x82000010
        value = 0x60000000
[[patch]]
    name = "Black Shading Fix"
    is_enabled = false
    [[patch.be32]]
        address = 0x82000020
        value = 0x39600000
[[patch]]
    name = "Ambient Occlusion - Option A: Upscaling Fix"
    is_enabled = false
    [[patch.be32]]
        address = 0x82000030
        value = 0x39400001
[[patch]]
    name = "Ambient Occlusion - Option B: Disable"
    is_enabled = false
    [[patch.be32]]
        address = 0x82000040
        value = 0x39600000
[[patch]]
    name = "Disable Motion Blur"
    is_enabled = false
    [[patch.be32]]
        address = 0x82000050
        value = 0x39600000
[[patch]]
    name = "Texture Streaming Fix"
    is_enabled = false
    [[patch.be32]]
        address = 0x82000060
        value = 0x39600000
[[patch]]
    name = "Disable Coalesced Hash Check"
    is_enabled = false
    [[patch.be32]]
        address = 0x82000070
        value = 0x39600000
[[patch]]
    name = "Show FPS"
    is_enabled = false
    [[patch.be32]]
        address = 0x82000080
        value = 0x39600000
[[patch]]
    name = "Disable Bloom"
    is_enabled = false
    [[patch.be32]]
        address = 0x82000090
        value = 0x39600000
"""

print("Clasificación de parches")
check(pe.classify("Unlock FPS") == "fps" and pe.classify("60 FPS") == "fps", "Unlock FPS / 60 FPS → FPS")
check(pe.classify("Show FPS") == "" and pe.classify("On-screen FPS counter") == "", "contadores de FPS no")
check(pe.classify("Black Shading Fix") == "fix", "Black Shading Fix → corrección gráfica")
check(pe.classify("Disable Coalesced Hash Check") == "", "quitar comprobaciones no es una mejora")
check(pe.classify("Havok physics FPS fix") == "fps_fix", "correcciones que acompañan al FPS")
check(pe.classify("Upscaling Fix (Choose One), Option C: Disable Gaussian Blur") == "",
      "de las opciones «elige una» solo la A")

d = os.path.join(TMP, "cfg", "ReForgeStudio", "game-patches", "patches")
os.makedirs(d)
open(os.path.join(d, "4D53082D - Gears of War 2.patch.toml"), "w").write(GOW2)
pf = cheats.parse_patch_file(os.path.join(d, "4D53082D - Gears of War 2.patch.toml"))
rec = [p.name for p in pe.recommended(pf.patches)]
check(rec == ["Unlock FPS", "Black Shading Fix", "Disable Motion Blur", "Texture Streaming Fix"],
      "Gears of War 2: FPS desbloqueados + sombreado negro + estelas + streaming de texturas")
check("Ambient Occlusion - Option A: Upscaling Fix" in [p.name for p in pe.recommended(pf.patches, scale=2)],
      "con escala de resolución 2× añade la corrección de escalado")
two = [Patch("Unlock FPS"), Patch("60 FPS")]
check(pe.recommended(two, fps_mode="60")[0].name == "60 FPS" and len(pe.recommended(two)) == 1,
      "un solo parche de FPS (60 FPS si el ritmo es 60)")
check(pe.recommended(two, fps_mode="unlimited")[0].name == "Unlock FPS", "sin límite → Unlock FPS")

print("Aplicar al proyecto")
root = os.path.join(TMP, "gow2")
os.makedirs(os.path.join(root, "assets"))
os.makedirs(os.path.join(root, "build"))
sec = 0x200
x = bytearray(0x1000)
struct.pack_into(">4sIIII", x, 0, b"XEX2", 0, 0x1000, 0, sec)
struct.pack_into(">II", x, sec + 0x10C, 0, 0x82000000)
struct.pack_into(">I", x, sec + 0x180, 1)
struct.pack_into(">I", x, sec + 0x184, (16 << 4) | 1)
open(os.path.join(root, "assets", "default.xex"), "wb").write(bytes(x))
exe = os.path.join(root, "build", "gearsofwar2latino.exe")
open(exe, "wb").write(b"")
check(pe.available_for_exe(exe, "4D53082D") == [], "sin versión identificada no ofrece nada")
open(os.path.join(root, "build", "reforge_module.txt"), "w").write("title_id=4D53082D\nhash=BDB97753374D520A\n")
check(len(pe.available_for_exe(exe, "")) == 9, "usa el Title ID que anota el juego")

calls = []
cheats.apply_cheats = lambda r, sel: calls.append([p.name for p in sel]) or True
new, changed = pe.apply_recommended(root, exe, "4D53082D")
check(changed and calls[-1] == rec and go.GameOptions.load(root).pc_enhanced,
      "las activa (hay que recompilar) y lo recuerda")
os.makedirs(os.path.join(root, "assets"), exist_ok=True)
open(os.path.join(root, "assets", cheats.CHEATS_MARKER), "w").write('{"patches": ["Disable Bloom"]}')
new, changed = pe.apply_recommended(root, exe, "4D53082D")
check(calls[-1] == ["Disable Bloom"] + rec, "conserva los trucos que ya tenías")

print("Ritmo de fotogramas (micro tirones)")
o = go.GameOptions()
check(o.frame_mode() == "auto", "por defecto: automático")
v = o.runtime_values()
check(v["vsync"] is True and v["video_mode_refresh_rate"] == 60.0 and
      "d3d12_allow_variable_refresh_rate_and_tearing" not in v,
      "60 Hz sin forzar la presentación (G-Sync/FreeSync siguen funcionando)")
check(pe.paced_rate(165, True) == 82.5, "monitor de 165 Hz + FPS desbloqueados → 82,5 (2 refrescos por imagen)")
check(pe.paced_rate(144, True) == 72 and pe.paced_rate(120, True) == 60 and pe.paced_rate(75, True) == 75,
      "144 → 72 · 120 → 60 · 75 → 75")
check(pe.paced_rate(165, False) == 60, "juego sin desbloquear: se queda en 60 (no se acelera)")
check(pe.paced_rate(59.94, False) == 59.94, "monitor de 59,94 Hz: el mismo ritmo exacto")
check(pe.frame_values("auto", True, 165)["video_mode_refresh_rate"] == 82.5, "automático usa el ritmo exacto")
check(pe.unlocks_framerate("Unlock FPS") and not pe.unlocks_framerate("60 FPS"),
      "«60 FPS» no cuenta como desbloqueado (se queda en 60)")
o.fps_mode = "unlimited"
v = o.runtime_values()
check(v["vsync"] is False and "video_mode_refresh_rate" not in v, "sin límite: vblank sin esperas")
o2 = go.GameOptions(vsync=False)
check(o2.frame_mode() == "unlimited", "respeta la casilla VSync de versiones anteriores")
check(pe.frame_values("monitor")["video_mode_refresh_rate"] >= 24, "frecuencia del monitor")

print("Puntero del ratón con mando")
from reforge import ext_cpp, profile  # noqa: E402
src = ext_cpp.EXT_SOURCE
check("class CursorGuard" in src and "XInputGetState" in src and "SetCursorVisibility" in src,
      "la extensión esconde el puntero al usar el mando y lo devuelve al mover el ratón")
check("window()," in ext_cpp.APP_BLOCK and "&achievements()" in ext_cpp.APP_BLOCK, "recibe la ventana del juego y los logros")
ini_exe = os.path.join(root, "build", "gearsofwar2latino.exe")
profile.write_ext_ini(ini_exe, go.GameOptions())
check("hide_cursor = 1" in open(profile.ext_ini_path(ini_exe), encoding="utf-8").read(), "activado por defecto")
profile.write_ext_ini(ini_exe, go.GameOptions(hide_cursor=False))
check("hide_cursor = 0" in open(profile.ext_ini_path(ini_exe), encoding="utf-8").read(), "se puede desactivar")

print("Parche de FPS anotado al aplicar trucos")
import importlib  # noqa: E402
importlib.reload(cheats)
cheats._note_fps_unlock(root, [Patch("Unlock FPS")])
check(go.GameOptions.load(root).fps_unlocked, "Unlock FPS → ritmo automático por encima de 60")
cheats._note_fps_unlock(root, [Patch("Black Shading Fix")])
check(not go.GameOptions.load(root).fps_unlocked, "sin parche de FPS → 60")
print(f"\nTodas las pruebas pasaron ({ok}).")
