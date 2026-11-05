"""Vigilante de juegos abiertos fuera de ReForge y sonido de logros.   python tests/test_watcher_sound.py"""
import array
import math
import os
import stat
import subprocess
import sys
import tempfile
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-watch-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication([])
from reforge import sound  # noqa: E402
from reforge.profile import Profile, ext_ini_path, write_ext_ini  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


print("Sonido de logros")
src = os.path.join(TMP, "con_silencio.wav")
rate = 44100
data = array.array("h", [0] * (rate * 2 // 2))            # 0,5 s de silencio (estéreo → 0,25 s)
data += array.array("h", (int(3000 * math.sin(i / 8)) for i in range(rate)))   # tono bajo de volumen
with wave.open(src, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(data.tobytes())
out = sound.import_sound(src)
with wave.open(out) as w:
    frames = array.array("h")
    frames.frombytes(w.readframes(w.getnframes()))
    dur = w.getnframes() / w.getframerate()
check(abs(frames[0]) < 2000 and max(abs(x) for x in frames[:2000]) > 3000, "quita el silencio inicial: suena al instante")
check(max(abs(x) for x in frames) > 20000, "normaliza el volumen (de -21 dB a -3 dB)")
check(dur < 1.0, "recorta el silencio final")
chime = sound.generate_reforge_chime()
with wave.open(chime) as w:
    check(w.getnchannels() == 2 and 1.0 < w.getnframes() / w.getframerate() < 1.3, "timbre propio de ReForge (1,15 s)")

exe = os.path.join(TMP, "g", "build", "juego.exe")
os.makedirs(os.path.dirname(exe))
open(exe, "w").write("")
p = Profile()
p.toast_sound, p.toast_volume = "custom", 50
write_ext_ini(exe, None, p)
ini = open(ext_ini_path(exe), encoding="utf-8").read()
wav = os.path.join(os.path.dirname(exe), "reforge_achievement.wav")
check("sound = reforge_achievement.wav" in ini and os.path.isfile(wav), "el sonido elegido se copia junto al juego")
with wave.open(wav) as w:
    half = array.array("h")
    half.frombytes(w.readframes(w.getnframes()))
check(abs(max(abs(x) for x in half) - max(abs(x) for x in frames) // 2) < 50, "aplica el volumen elegido (50 %)")
p.toast_sound = "none"
write_ext_ini(exe, None, p)
check("sound = \n" in open(ext_ini_path(exe), encoding="utf-8").read() and not os.path.exists(wav),
      "«Sin sonido» lo quita")
from reforge.ext_cpp import EXT_SOURCE  # noqa: E402
check("PlaySoundW" in EXT_SOURCE and 'LoadLibraryW(L"winmm.dll")' in EXT_SOURCE and "SDL_LoadWAV" in EXT_SOURCE,
      "el juego lo reproduce con PlaySound (Windows, sin enlazar nada) o SDL")
check('find_first_of("/\\\\:")' in EXT_SOURCE, "solo acepta un nombre de archivo junto al .exe (sin rutas)")

if sys.platform == "win32":
    print(f"\nTodas las pruebas pasaron ({ok}).  (juego simulado omitido en Windows)")
    sys.exit(0)

print("Juego abierto fuera de ReForge (.bat, acceso directo, doble clic)")
from reforge import app as appmod  # noqa: E402
from reforge.core import Project  # noqa: E402
from reforge.runner import wait_threads  # noqa: E402
QMessageBox.warning = QMessageBox.information = staticmethod(lambda *a, **k: None)

proj = os.path.join(TMP, "ben10")
os.makedirs(os.path.join(proj, "build", "logs"))
open(os.path.join(proj, "ben10omniversetm_manifest.toml"), "w").write('[project]\nname = "ben10omniversetm"\n')
gexe = os.path.join(proj, "build", "ben10omniversetm")
open(os.path.join(proj, "build", "logs", "ben10omniversetm_001.log"), "w").write(
    "[critical] [FATAL] Call to invalid or unregistered function at guest address 0x82000001\n")   # partida vieja
os.utime(os.path.join(proj, "build", "logs", "ben10omniversetm_001.log"), (time.time() - 3600,) * 2)


def make_game(fatal):
    with open(gexe, "w") as f:
        f.write(f"""#!{sys.executable}
import os, sys, time
d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
n = len([x for x in os.listdir(d) if x.endswith('.log')]) + 1
log = open(os.path.join(d, "ben10omniversetm_%03d.log" % n), "w")
log.write("[info] [gpu] Direct3D 12\\n"); log.flush(); time.sleep(1.5)
log.write({fatal!r} + "\\n"); log.flush(); time.sleep(600)
""")
    os.chmod(gexe, os.stat(gexe).st_mode | stat.S_IEXEC)


w = appmod.MainWindow()
w.lib.upsert(Project(name="ben_10_omniverse_tm", root=proj))
w.watcher.timer.setInterval(200)
w.watcher._prime()
repairs, detected = [], []
w.workshop.repair_round = lambda addr: repairs.append(addr)
w.watcher.detected.connect(lambda p, e: detected.append(p.name))


def spin(cond, secs=15):
    end = time.time() + secs
    while time.time() < end and not cond():
        app.processEvents()
        time.sleep(0.05)


make_game("[critical] [core] [FATAL] Call to invalid or unregistered function at guest address 0x825B64B0")
proc = subprocess.Popen([gexe])                    # lanzado por fuera, como el .bat
spin(lambda: repairs)
check(detected[:1] == ["ben_10_omniverse_tm"],
      "detecta el juego abierto aunque no lo lanzó ReForge")
check(repairs == [0x825B64B0], "al fallar por una función no registrada lo repara en el Taller")
spin(lambda: proc.poll() is not None, 10)
check(proc.poll() is not None, "cierra el juego colgado en el cuadro de error")
check(0x82000001 not in repairs, "no actúa sobre partidas anteriores a abrir ReForge")

gpu = []
w.watcher.crashed.connect(lambda p, e, info: gpu.append(info["kind"]))
QMessageBox.exec = lambda self: 0
make_game("[critical] [gpu] [FATAL] Graphics device lost (probably due to an internal error)")
proc = subprocess.Popen([gexe])
spin(lambda: gpu)
check(gpu == ["gpu"], "reconoce un error gráfico y ofrece el asistente de imagen")
spin(lambda: proc.poll() is not None, 10)

from reforge.watcher import clear_marker, write_marker  # noqa: E402
before = len(repairs)
make_game("[critical] [core] [FATAL] Call to invalid or unregistered function at guest address 0x82AAAAAA")
proc = subprocess.Popen([gexe])
spin(lambda: len(os.listdir(os.path.join(proj, "build", "logs"))) >= 4, 5)
write_marker(gexe)                                 # el lanzador del juego ya lo vigila
for _ in range(60):
    write_marker(gexe)
    app.processEvents()
    time.sleep(0.05)
check(len(repairs) == before, "si el lanzador ya vigila ese juego, no interviene dos veces")
proc.kill()
spin(lambda: proc.poll() is not None, 5)
clear_marker(gexe)

print("Partida lanzada por fuera que termina: el Taller la analiza y la mantiene solo")
from reforge.watcher import clear_marker as _cm  # noqa: E402,F401
with open(gexe, "w") as f:
    f.write(f"""#!{sys.executable}
import os, time
d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
n = len([x for x in os.listdir(d) if x.endswith('.log')]) + 1
log = open(os.path.join(d, "ben10omniversetm_%03d.log" % n), "w")
log.write("[2026-10-16 18:00:00.000] [info] [gpu] Direct3D 12\\n"); log.flush(); time.sleep(1.0)
log.write("[2026-10-16 18:00:01.000] [warning] [core] [t1] [ReForge] Tirón de 120 ms\\n"); log.flush(); time.sleep(1.0)
log.write("[2026-10-16 18:00:02.000] [error] [sys] [t2] Unhandled guest access violation: read of guest 0x000001A4 (host 0x1) on thread 0xF8000028\\n")
log.flush()
""")
live, ended = [], []
w.watcher.stats.connect(lambda p, e, st, secs: live.append(dict(st)))
w.watcher.ended.connect(lambda p, e, info: ended.append(info["kind"]))
w.workshop.repair_round = lambda addr: repairs.append(("maint", addr))
proc = subprocess.Popen([gexe])
spin(lambda: ended, 40)
check(any(st.get("hitches") == 1 for st in live), "estado en vivo: cuenta los tirones mientras se juega")
check(ended == ["guest_av"], "al terminar, analiza la partida aunque no la lanzó ReForge")
spin(lambda: ("maint", None) in repairs, 5)
check(("maint", None) in repairs and "Jugando" not in w.workshop.status_lbl.text(),
      "y lanza solo el mantenimiento completo en el Taller")
wait_threads()
print(f"\nTodas las pruebas pasaron ({ok}).")
