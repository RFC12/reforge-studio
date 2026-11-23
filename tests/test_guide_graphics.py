"""30 FPS con VSync (NVIDIA Smooth Motion) y menú Gráficos dentro del juego.

python tests/test_guide_graphics.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-gfx-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)

from reforge import ext_cpp, game_options as go, pc_enhance as pe, profile  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


print("30 FPS con VSync")
v = pe.frame_values("30")
check(v.get("vsync") is True and v.get("video_mode_refresh_rate") == 60.0,
      "el vblank se queda en 60 (un juego de 30 no cae a 15)")
check(v.get("d3d12_allow_variable_refresh_rate_and_tearing") is False, "presentación con VSync, sin desgarros")
check(pe.frame_cap("30") == 30.0 and pe.frame_cap("auto") == 0.0, "el tope real de 30 lo aplica la extensión")
o = go.GameOptions(fps_mode="30")
check(o.frame_mode() == "30", "se puede elegir en Opciones del juego")
check([k for k, _t in pe.FPS_MODES][0] == "30", "es la primera opción de Fotogramas")
check(o.runtime_values().get("video_mode_refresh_rate") == 60.0, "el .toml lleva el ritmo correcto")

print("Menú Guía → Gráficos")
src = ext_cpp.EXT_SOURCE
check('"Gráficos"' in src and "kGraphics" in src, "pestaña Gráficos en el menú del mando")
check("ApplyGraphics" in src, "cambia los ajustes sin salir del juego")
check('SetCvar("draw_resolution_scale_x"' in src and 'SetCvar("video_mode_refresh_rate"' in src
      and "rex::cvar::SetFlagByName" in src, "usa las cvars del runtime en caliente")
check("g_frame_cap.store(" in src and "WaitFrameCap" in src and "sleep_until" in src,
      "el tope de 30 FPS se aplica en VdSwap")
check("fps_mode" in src and "resolution_scale" in src and "reforge_menu.ini" in src,
      "lo elegido jugando se guarda junto al .exe")
check("se aplica al reiniciar" in src, "avisa cuando el runtime no lo cambia en caliente")

print("Lo elegido jugando pasa al próximo arranque")
exe = os.path.join(TMP, "asura_s_wrath", "build", "asuraswrath.exe")
os.makedirs(os.path.dirname(exe))
open(exe, "wb").write(b"")
profile.write_ext_ini(exe, go.GameOptions(fps_mode="30"))
check("frame_cap = 30.0" in open(profile.ext_ini_path(exe), encoding="utf-8").read(),
      "reforge_ext.ini lleva el tope de 30")
profile.write_ext_ini(exe, go.GameOptions())
check("frame_cap = 0.0" in open(profile.ext_ini_path(exe), encoding="utf-8").read(), "sin tope por defecto")

menu = go.menu_ini_path(exe)
with open(menu, "w", encoding="utf-8") as f:
    f.write("show_fps = 1\nfps_mode = 30\nresolution_scale = 2\n")
go.write_runtime_config(exe, go.GameOptions())
toml = open(go.runtime_config_path(exe), encoding="utf-8").read()
check("draw_resolution_scale_x = 2" in toml and "video_mode_refresh_rate = 60.000" in toml,
      "el .toml del juego recibe la escala y el ritmo elegidos en el menú")
check("frame_cap = 30.0" in open(profile.ext_ini_path(exe), encoding="utf-8").read(),
      "y el tope de 30 FPS")
left = open(menu, encoding="utf-8").read()
check("show_fps = 1" in left and "fps_mode" not in left and "resolution_scale" not in left,
      "el .ini del menú conserva el resto y quita lo ya aplicado")
check(go.menu_graphics(exe) == {}, "no se vuelve a aplicar en el siguiente arranque")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
