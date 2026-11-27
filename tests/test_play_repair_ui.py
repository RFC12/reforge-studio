"""Flujo real del Taller: ▶ Jugar → el juego se cierra → reparación automática → arranca.

python tests/test_play_repair_ui.py   (usa Qt offscreen; en Windows se omite el juego simulado)
"""
import os
import stat
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-ui-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)

if sys.platform == "win32":
    print("Juego simulado solo en Linux/macOS: omitido.")
    sys.exit(0)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication([])
from reforge import app as appmod  # noqa: E402
from reforge import game  # noqa: E402
from reforge.core import Project  # noqa: E402
from reforge.game_options import GameOptions  # noqa: E402

QMessageBox.information = QMessageBox.question = QMessageBox.warning = staticmethod(lambda *a, **k: None)

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


# --- proyecto falso con la estructura real de rexglue
proj = os.path.join(TMP, "angry_birds_trilogy")
for d in ("assets", "build", "src"):
    os.makedirs(os.path.join(proj, d))
open(os.path.join(proj, "assets", "default.xex"), "wb").write(b"XEX2")
open(os.path.join(proj, "CMakeLists.txt"), "w").write("")
open(os.path.join(proj, "angrybirdstrilogy_manifest.toml"), "w").write(
    '[project]\nname = "angrybirdstrilogy"\n\n[entrypoint]\nfile_path = "assets/default.xex"\n'
    'includes = ["reforge_functions.toml"]\n')
open(os.path.join(proj, "src", "angrybirdstrilogy_app.h"), "w").write(
    "#include <rex/rex_app.h>\nclass A : public rex::ReXApp {\n public:\n  using rex::ReXApp::ReXApp;\n};\n")
funcs = os.path.join(proj, "reforge_functions.toml")
exe = os.path.join(proj, "build", "angrybirdstrilogy")
with open(exe, "w") as f:   # falla como el juego real hasta que sus funciones estén declaradas
    f.write(f"""#!{sys.executable}
import os, sys, time
need = [0x8263E990, 0x8264AA00, 0x8229A1A8]   # la última falla tarde, ya «arrancado»
txt = open({funcs!r}).read() if os.path.exists({funcs!r}) else ""
d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"); os.makedirs(d, exist_ok=True)
log = open(os.path.join(d, "angrybirdstrilogy_%d.log" % time.time_ns()), "w")
log.write("[info] [gpu] Direct3D 12\\n")
for i, a in enumerate(need):
    if ("0x%08X" % a) not in txt:
        if i == 2:
            log.write("[info] audio endpoint\\n"); log.flush(); time.sleep(6)
        log.write("[critical] [core] [FATAL] Call to invalid or unregistered function at guest address 0x%08X\\n" % a)
        log.flush()
        time.sleep(600)   # como en Windows: abort() deja el proceso colgado en el cuadro de error
log.write("[info] running\\n"); log.flush(); time.sleep(60)
""")
os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)
fake = os.path.join(TMP, "fakecmake")
open(fake, "w").write("#!/bin/sh\necho fake cmake \"$@\"\n")
os.chmod(fake, 0o755)

o = GameOptions()
o.repair_watch_seconds = 3
o.ask_engine_on_play = False
o.codegen_opt = "off"          # este proyecto falso no se puede recompilar de verdad
o.auto_relaunch = True         # esta prueba cubre los caminos de reapertura (cuenta atrás / recompilar y jugar)
o.save(proj)

w = appmod.MainWindow()
w.cfg.cmake = fake
calls = []
game.codegen_with_autofix = lambda *a, **k: calls.append("codegen")
p = w.lib.upsert(Project(name="angry_birds_trilogy", root=proj))
w.open_project(p)
ws = w.workshop
check(ws.btn_play.isEnabled(), "▶ Jugar habilitado con el .exe compilado")
t_start = time.time()

ws.play()
deadline = time.time() + 120
while time.time() < deadline:
    app.processEvents()
    time.sleep(0.02)
    res = ws._watch_result
    if (not ws.runner.running and res and res.get("kind") == "running" and ws._mode == "build"
            and 0x8229A1A8 in game.declared_functions(proj)):
        break
text = ws.log.toPlainText()
check(game.declared_functions(proj) >= {0x8263E990, 0x8264AA00, 0x8229A1A8},
      "declaró también la función que falló minutos después de arrancar")
check(calls.count("codegen") == 3, "regeneró y recompiló una vez por función")
check(ws._watch_result and ws._watch_result["kind"] == "running", "el juego terminó arrancando y sigue abierto")
check("mientras jugabas" in text and "Reparación automática · ronda 3" in text
      and "seguimiento activo" in text, "el Taller lo explica en el log")
check(time.time() - t_start < 60, "no espera a que el proceso colgado termine solo")
import subprocess  # noqa: E402
hung = subprocess.run(["pgrep", "-f", exe], capture_output=True, text=True).stdout.split()
check(len(hung) == 1, "cerró los procesos colgados por el [FATAL] (solo queda el juego que arrancó)")
os.kill(ws._watch_result["pid"], 9)
for _ in range(50):
    app.processEvents()
    time.sleep(0.02)

print("Recompilar solo y volver a abrir el juego")
from reforge.runner import wait_threads  # noqa: E402
ws._session_timer.stop()
ws._session = None
started = []
orig_rebuild = ws.rebuild_current
ws.rebuild_current = lambda: started.append("rebuild") or True
game.rebuild_reason = lambda root, exe, cfg=None: "hay trucos o mejoras para PC sin compilar"
ws.play()
check(started == ["rebuild"] and ws._play_after_build, "▶ Jugar con cambios sin compilar: recompila primero")
game.rebuild_reason = lambda root, exe, cfg=None: ""
plays = []
ws.play = lambda auto=False: plays.append(auto)
ws._mode = "build"
ws._active_keys = ["build"]
ws._on_finished(True)
for _ in range(60):
    app.processEvents()
    time.sleep(0.02)
check(plays == [True] and not ws._play_after_build, "al terminar de compilar abre el juego solo")
shown = []
ws.offer_pc_enhancements = lambda p_, e_: False
ws.relaunch_countdown = lambda p_, why, seconds=10: shown.append(why)
deadline = time.time() + 60
while ws.runner.running and time.time() < deadline:     # el vigilante general puede lanzar un mantenimiento
    app.processEvents()
    time.sleep(0.02)
ws._after_clean_session(ws.current, exe, ["Ahora va a 60 FPS constantes"])
check(shown and "60 FPS" in shown[0], "ajustes nuevos tras la partida → vuelve a abrirlo (cuenta atrás)")
del ws.relaunch_countdown
plays.clear()
ws.relaunch_countdown(ws.current, "prueba", seconds=1)
for _ in range(100):
    app.processEvents()
    time.sleep(0.02)
check(plays == [True], "la cuenta atrás abre el juego si no se cancela")

print("Optimización del código: baja de nivel sola si el juego falla")
rounds = []
ws.repair_round = lambda addr: rounds.append(addr)
oc = GameOptions.load(proj)
oc.codegen_opt, oc.codegen_opt_level, oc.codegen_opt_verified = "auto", "max", False
oc.save(proj)
ws._handle_crash({"kind": "hang", "lines": []}, GameOptions.load(proj))
for _ in range(30):
    app.processEvents()
    time.sleep(0.02)
check(GameOptions.load(proj).codegen_opt_level == "safe" and rounds == [None],
      "colgado con «Máxima» sin comprobar → «Segura», recompila y prueba")
ws._handle_crash({"kind": "guest_av", "lines": [], "address": None}, GameOptions.load(proj))
for _ in range(30):
    app.processEvents()
    time.sleep(0.02)
check(GameOptions.load(proj).codegen_opt_level == "off", "si vuelve a fallar → desactivada")
oc = GameOptions.load(proj)
oc.codegen_opt_level, oc.codegen_opt_verified = "max", True
oc.save(proj)
rounds.clear()
ws._codegen_step_down(ws.current, GameOptions.load(proj), {"kind": "crash"})
check(GameOptions.load(proj).codegen_opt_level == "max", "ya comprobada: un cierre posterior no la quita")

wait_threads()
print(f"\nTodas las pruebas pasaron ({ok}).")
