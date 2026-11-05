"""Pruebas 1.4.0: reparación del arranque, opciones del juego y gancho de rutas.

    python tests/test_runtime_repair.py
"""
import os
import stat
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-rt-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)

from reforge import game  # noqa: E402
from reforge.core import AppConfig  # noqa: E402
from reforge.game_options import (BEGIN, END, GameOptions, ensure_paths_hook, runtime_config_path,  # noqa: E402
                                  write_runtime_config)

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


# Texto real de los logs del usuario (angrybirdstrilogy_011.log)
REAL_LOG = """[2026-10-14 13:58:02.117] [rex] [info] GPU: Direct3D 12 (rexgpu-xenos)
[2026-10-14 13:58:02.341] [rex] [info] Input: SDL controller 0 connected
[2026-10-14 13:58:03.902] [rex] [critical] Call to invalid or unregistered function at guest address 0x8263E990
[2026-10-14 13:58:03.902] [rex] [error] Guest thread terminated
"""

print("Análisis del log del juego")
logs = os.path.join(TMP, "game", "logs")
os.makedirs(logs)
lp = os.path.join(logs, "angrybirdstrilogy_011.log")
open(lp, "w", encoding="utf-8").write(REAL_LOG)
r = game.analyze_runtime_log(lp)
check(r["kind"] == "unregistered" and r["address"] == 0x8263E990, "detecta 0x8263E990 del log real")
check(game.newest_log(os.path.join(TMP, "game", "x.exe")) == lp, "encuentra el log más reciente")
open(lp, "w", encoding="utf-8").write("[info] ok\n[error] D3D12 device removed\n")
check(game.analyze_runtime_log(lp)["kind"] == "fatal", "otros errores se informan como 'fatal'")
check(game.analyze_runtime_log("")["kind"] == "nolog", "sin log → 'nolog'")

print("Declarar funciones descubiertas al ejecutar")
proj = os.path.join(TMP, "proj")
os.makedirs(os.path.join(proj, "src"))
with open(os.path.join(proj, "angrybirdstrilogy_manifest.toml"), "w", encoding="utf-8") as f:
    f.write('[project]\nname = "angrybirdstrilogy"\n\n[entrypoint]\nfile_path = "assets/default.xex"\n')
check(game.declare_runtime_function(proj, 0x8262E8B8), "declara 0x8262E8B8")
check(not game.declare_runtime_function(proj, 0x8262E8B8), "no la duplica")
check(game.declare_runtime_function(proj, 0x8263E990), "declara 0x8263E990")
check(game.declared_functions(proj) == {0x8262E8B8, 0x8263E990}, "ambas quedan en reforge_functions.toml")
check("reforge_functions.toml" in open(os.path.join(proj, "angrybirdstrilogy_manifest.toml"), encoding="utf-8").read(),
      "el manifiesto incluye el archivo de funciones")

print("Gancho de carpeta del juego (doble clic)")
hdr = os.path.join(proj, "src", "angrybirdstrilogy_app.h")
open(hdr, "w", encoding="utf-8").write("#pragma once\n#include <rex/rex_app.h>\n\nclass AngrybirdstrilogyApp : public rex::ReXApp {\n"
                     " public:\n  using rex::ReXApp::ReXApp;\n};\n")
check(ensure_paths_hook(proj), "añade OnConfigurePaths")
t1 = open(hdr, encoding="utf-8").read()
check(not ensure_paths_hook(proj) and open(hdr, encoding="utf-8").read() == t1, "es idempotente")
check(t1.count("OnConfigurePaths") == 1 and "#include <rex/filesystem.h>" in t1 and "#include <filesystem>" in t1,
      "incluye cabeceras una sola vez")
own = os.path.join(TMP, "own")
os.makedirs(os.path.join(own, "src"))
open(os.path.join(own, "src", "x_app.h"), "w", encoding="utf-8").write(
    "using rex::ReXApp::ReXApp;\n  void OnConfigurePaths(rex::PathConfig& p) override {}\n")
check(not ensure_paths_hook(own), "respeta un OnConfigurePaths propio del usuario")

print("Opciones del juego → <exe>.toml")
exe_dir = os.path.join(TMP, "game")
fake_exe = os.path.join(exe_dir, "angrybirdstrilogy.exe")
open(fake_exe, "w", encoding="utf-8").write("")
cfgp = runtime_config_path(fake_exe)
open(cfgp, "w", encoding="utf-8").write("# mío\nvsync = false\nmi_cvar = 7\n")
o = GameOptions()
o.fullscreen, o.resolution_scale, o.mnk_mode = True, 2, True
o.keybinds["keybind_a"] = "Space"
o.save(proj)
o2 = GameOptions.load(proj)
check(o2.fullscreen and o2.resolution_scale == 2 and o2.keybinds["keybind_a"] == "Space"
      and o2.keybinds["keybind_start"] == "X,Return", "se guardan y cargan (con teclas por defecto)")
write_runtime_config(fake_exe, o2)
write_runtime_config(fake_exe, o2)
t = open(cfgp, encoding="utf-8").read()
check(t.count(BEGIN) == 1 and t.count(END) == 1, "un solo bloque gestionado aunque se escriba dos veces")
check("mi_cvar = 7" in t and "# mío" in t, "conserva las líneas del usuario")
check(t.count("vsync =") == 1 and "vsync = true" in t, "sin claves duplicadas")
check("fullscreen = true" in t and "draw_resolution_scale_x = 2" in t and "mnk_mode = true" in t
      and 'keybind_a = "Space"' in t, "escribe gráficos, escala y teclado/ratón")

print("Compatibilidad gráfica (pantalla negra) y menú de motor")
o3 = GameOptions()
check(o3.preset() == "auto" and "render_target_path_d3d12" not in o3.runtime_values(), "por defecto: automático")
o3.apply_preset("compat")
v3 = o3.runtime_values()
check(v3["render_target_path_d3d12"] == "rov" and v3["d3d12_readback_resolve"] is True
      and v3["gpu_allow_invalid_fetch_constants"] is True and o3.preset() == "compat", "compatibilidad máxima")
write_runtime_config(fake_exe, o3)
t3 = open(cfgp, encoding="utf-8").read()
check('render_target_path_d3d12 = "rov"' in t3, "sin DLL que revisar: escribe las opciones avanzadas")
open(os.path.join(exe_dir, "rexgpu-xenos.dll"), "wb").write(b"MZ..render_target_path_d3d12\0..vsync\0")
write_runtime_config(fake_exe, o3)
t4 = open(cfgp, encoding="utf-8").read()
check('render_target_path_d3d12 = "rov"' in t4 and "d3d12_readback_resolve" not in t4
      and "gpu_allow_invalid_fetch_constants" not in t4, "omite las que el plugin del juego no trae")
o3.apply_preset("auto")
write_runtime_config(fake_exe, o3)
check("render_target_path_d3d12" not in open(cfgp, encoding="utf-8").read(), "volver a automático las quita")
os.remove(os.path.join(exe_dir, "rexgpu-xenos.dll"))

if sys.platform != "win32":
    print("Bucle de reparación con un juego simulado")
    # Juego falso: falla en cada dirección no declarada, en orden, y arranca cuando todas lo están.
    gdir = os.path.join(TMP, "sim")
    os.makedirs(gdir)
    sim = os.path.join(gdir, "sim.exe")
    funcs = os.path.join(proj, "reforge_functions.toml")
    with open(sim, "w", encoding="utf-8") as f:
        f.write(f"""#!{sys.executable}
import os, sys, time
need = [0x8262E8B8, 0x8263E990, 0x82640000, 0x82650010]
txt = open({funcs!r}).read() if os.path.exists({funcs!r}) else ""
os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)
log = open(os.path.join(os.path.dirname(__file__), "logs", "sim_%d.log" % time.time_ns()), "w")
for a in need:
    if ("0x%08X" % a) not in txt:
        log.write("[critical] Call to invalid or unregistered function at guest address 0x%08X\\n" % a)
        sys.exit(3)
log.write("[info] running\\n"); log.flush()
time.sleep(30)
""")
    os.chmod(sim, os.stat(sim).st_mode | stat.S_IEXEC)

    class Ctx:
        def log(self, *a):
            pass

        def progress(self, *a):
            pass

        def cancelled(self):
            return False

    os.makedirs(os.path.join(proj, "assets"), exist_ok=True)
    open(os.path.join(proj, "assets", "default.xex"), "wb").write(b"XEX2")
    cfg = AppConfig()
    rounds, res = 0, None
    while rounds < 10:
        res = game.launch_and_watch(cfg, sim, proj, 3, Ctx())
        if res["kind"] != "unregistered":
            break
        check(game.declare_runtime_function(proj, res["address"]), f"ronda {rounds + 1}: declara 0x{res['address']:08X}")
        rounds += 1
        time.sleep(0.05)
    check(res["kind"] == "running", f"el juego arranca tras {rounds} rondas de reparación")
    os.kill(res["pid"], 9)

print(f"\nTodas las pruebas pasaron ({ok}).")
