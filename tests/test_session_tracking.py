"""Seguimiento de la sesión del juego: nada de falso éxito.

Un proceso que supera el umbral de vigilancia (queda «En ejecución») y falla DESPUÉS debe actualizar esa misma
sesión como fallida, con su primer error, código de salida y la intervención del supervisor por separado. Cubre
también cierre limpio y un segundo arranque que genera otro log.
"""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import game  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


def live_proc():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])


d = tempfile.mkdtemp()
exe = os.path.join(d, "asuraswrath.exe")
open(exe, "wb").write(b"\0")
logs = game.game_log_dir(exe)
os.makedirs(logs, exist_ok=True)
log = os.path.join(logs, "asuraswrath_121.log")

print("Supera el umbral: sigue en ejecución, sin falso éxito")
with open(log, "w", encoding="utf-8") as f:
    f.write("[info] rexglue runtime initialized\n[info] present frame 1\n")
p = live_proc()
res = {"kind": "running", "proc": p, "before": {}, "path": log, "pid": p.pid}
out = game.check_running_game(exe, res)
check(out is None, "con el juego abierto y sin [FATAL], la sesión sigue viva (no se declara éxito)")

print("Falla DESPUÉS (fatal tardío al enumerar contenido): misma sesión → fallida")
with open(log, "a", encoding="utf-8") as f:
    f.write("[debug] XamContentCreateEnumerator: added 5 items to enumerator\n"
            "[critical] [core] [FATAL] Dispatch thread: deferred completion threw 'Invalid UTF-8'\n")
out = game.check_running_game(exe, res)
check(out is not None and out["kind"] == "fatal", "el fatal tardío se detecta y clasifica como fallo")
check(out.get("killed") is True, "queda registrado que el supervisor cerró el proceso")
cls = game.attempt_result(out)
check(cls["ok"] is False and cls["case"] == "supervisor_killed" and cls["cause"] == "utf8_deferred",
      "caso: el supervisor cerró el proceso; causa: UTF-8 diferido")
check("Invalid UTF-8" in cls["first_error"], "conserva el primer error de la sesión")
check(p.poll() is not None, "el proceso quedó cerrado")

print("Cierre limpio: el juego se cerró solo, sin error → éxito")
d2 = tempfile.mkdtemp()
exe2 = os.path.join(d2, "g.exe")
open(exe2, "wb").write(b"\0")
os.makedirs(game.game_log_dir(exe2), exist_ok=True)
log2 = os.path.join(game.game_log_dir(exe2), "g_001.log")
open(log2, "w", encoding="utf-8").write("[info] runtime initialized\nWindow closing, shutting down\n")
p2 = subprocess.Popen([sys.executable, "-c", "pass"])
p2.wait()
res2 = {"kind": "running", "proc": p2, "before": {}, "path": log2}
out2 = game.check_running_game(exe2, res2)
check(out2 is not None and game.attempt_result(out2)["ok"] is True, "cierre limpio cuenta como terminado bien")

print("Segundo arranque: genera otro log y se toma el más reciente")
time.sleep(0.02)
log3 = os.path.join(logs, "asuraswrath_122.log")
open(log3, "w", encoding="utf-8").write("[info] runtime initialized\n[info] present frame 1\n")
os.utime(log3)
fresh = game._fresh_log(exe, {})
check(fresh.endswith("asuraswrath_122.log"), "un lanzamiento posterior usa su propio log (el más nuevo)")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
