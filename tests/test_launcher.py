"""Lanzador propio del juego, idioma y argumentos --launcher/--repair.   python tests/test_launcher.py"""
import os
import stat
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-launcher-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication([])
from reforge import launcher as L  # noqa: E402
from reforge.app import parse_args  # noqa: E402
from reforge.game_options import GameOptions, detect_languages, runtime_config_path  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


print("Argumentos")
a = parse_args(["x", "--launcher", "C:/p/juego"])
check(a["launcher"] == "C:/p/juego", "--launcher <proyecto>")
a = parse_args(["x", "--repair", "C:/p/juego", "0x825B64B0"])
check(a["repair"] == ["C:/p/juego", 0x825B64B0], "--repair <proyecto> <dirección>")
a = parse_args(["x", "--repair", "C:/p/juego", "basura"])
check(a["repair"] is None and a["open_project"] == "C:/p/juego", "--repair con dirección inválida solo abre el proyecto")

print("Idiomas del juego (estructura real de Angry Birds Trilogy)")
proj = os.path.join(TMP, "angry_birds_trilogy")
for f in ("speech/de.cfg", "speech/en.cfg", "speech/es.cfg", "speech/fr.cfg", "speech/it.cfg",
          "videos/cutscenes/original/chapter_01.bik", "nuisp1031", "audio.pck", "default.xex"):
    p = os.path.join(proj, "assets", f)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(b"x")
check(detect_languages(proj) == [1, 3, 4, 5, 6], "detecta inglés, alemán, francés, español e italiano")
o = GameOptions()
o.language = 5
check(o.runtime_values()["user_language"] == 5 and o.runtime_values()["user_country"] == 31,
      "español → user_language = 5 y región España por defecto")
from reforge.game_options import set_language_key, language_key  # noqa: E402
set_language_key(o, "5:71")
check(o.runtime_values()["user_language"] == 5 and o.runtime_values()["user_country"] == 71
      and language_key(o) == "5:71", "Español (México) → idioma 5 + país 71 (región MX en rexglue)")
check("user_language" not in GameOptions(language=0).runtime_values(), "«el que elija el juego» no fuerza idioma")

if sys.platform == "win32":
    print(f"\nTodas las pruebas pasaron ({ok}).  (juego simulado omitido en Windows)")
    sys.exit(0)

print("Lanzador con un juego simulado que se cierra al pulsar Start")
os.makedirs(os.path.join(proj, "build"))
open(os.path.join(proj, "angrybirdstrilogy_manifest.toml"), "w").write('[project]\nname = "angrybirdstrilogy"\n')
exe = os.path.join(proj, "build", "angrybirdstrilogy")
with open(exe, "w") as f:
    f.write(f"""#!{sys.executable}
import os, time
d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"); os.makedirs(d, exist_ok=True)
log = open(os.path.join(d, "g_%d.log" % time.time_ns()), "w")
log.write("[info] audio\\n"); log.flush(); time.sleep(1.5)
log.write("[critical] [core] [FATAL] Call to invalid or unregistered function at guest address 0x825B64B0\\n")
log.flush(); time.sleep(600)
""")
os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)

asked = []


def fake_exec(box):
    asked.append(box.text())
    return 0


QMessageBox.exec = fake_exec
QMessageBox.clickedButton = lambda self: None

w = L.GameLauncher(proj)
w.show()
check(w.exe == exe and w.play_btn.isEnabled(), "encuentra el ejecutable y habilita ▶ JUGAR")
check([w.lang.itemData(i) for i in range(w.lang.count())] == ["auto", "", "1:103", "3:24", "4:34", "5:31", "5:71", "6:50"],
      "ofrece los idiomas del juego, con español de España y de México")
check(not w.engine.model().item(w.engine.findData("vulkan")).isEnabled(), "Vulkan aparece desactivado (no está en el SDK)")
w.engine.setCurrentIndex(w.engine.findData("compat"))
w.lang.setCurrentIndex(w.lang.findData("5:71"))
w.full.setChecked(True)
w.play()
cfg_txt = open(runtime_config_path(exe), encoding="utf-8").read()
check('render_target_path_d3d12 = "rov"' in cfg_txt and "user_language = 5" in cfg_txt and "user_country = 71" in cfg_txt
      and "fullscreen = true" in cfg_txt, "escribe motor, idioma y pantalla antes de arrancar")
check((GameOptions.load(proj).language, GameOptions.load(proj).country) == (5, 71), "recuerda la elección para la próxima vez")
pid = w.proc.pid
deadline = time.time() + 20
while time.time() < deadline and not asked:
    app.processEvents()
    time.sleep(0.05)
check(asked and "0x825B64B0" in asked[0], "detecta el cierre al pulsar Start y ofrece repararlo")
try:
    os.kill(pid, 0)
    alive = True
except OSError:
    alive = False
check(not alive or os.waitpid(pid, os.WNOHANG) != (0, 0), "cierra el juego colgado en el error")
check(w.play_btn.isEnabled() and "0x825B64B0" in w.status.text(), "vuelve a quedar listo y lo explica")
prog, args = L.reforge_command("--repair", proj, "0x825B64B0")
check(args[-3:] == ["--repair", proj, "0x825B64B0"], "«Reparar ahora» abre ReForge Studio con --repair")


print("ReForge Studio recibe la reparación pedida por el lanzador")
from reforge import app as appmod  # noqa: E402
got = []
mw = appmod.MainWindow({"safe_mode": False, "install_patch": "", "launcher": "", "open_project": "",
                        "repair": [proj, 0x825B64B0]})
mw.workshop.repair_round = lambda addr: got.append(addr)
deadline = time.time() + 5
while time.time() < deadline and not got:
    app.processEvents()
    time.sleep(0.02)
check(got == [0x825B64B0], "abre el proyecto en el Taller y empieza la ronda de reparación")
check(mw.workshop.current and os.path.abspath(mw.workshop.current.root) == os.path.abspath(proj),
      "el proyecto queda abierto (se añade a la Biblioteca si no estaba)")

from reforge.runner import wait_threads  # noqa: E402
wait_threads()
print(f"\nTodas las pruebas pasaron ({ok}).")
