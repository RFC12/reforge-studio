"""Hitos del juego recompilado: escalera, registro/lectura e inferencia desde el log."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import milestones as ms  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


print("La escalera va del binario a una escena jugable")
check(ms.KEY_LEVEL["EXE_BUILT"] < ms.KEY_LEVEL["FIRST_FRAME"] < ms.KEY_LEVEL["PLAYABLE_SCENE"],
      "exe generado < primer fotograma < escena jugable")
check(ms.describe(ms.KEY_LEVEL["FIRST_FRAME"]) == "primer fotograma presentado", "describe el hito")

d = tempfile.mkdtemp()
exe = os.path.join(d, "asuraswrath.exe")
open(exe, "wb").write(b"\0" * 10)

print("Registrar y leer hitos junto al .exe")
check(ms.level_for(d, exe) == ms.KEY_LEVEL["EXE_BUILT"], "con el .exe hay al menos 'ejecutable generado'")
ms.record(exe, "FIRST_FRAME")
check("FIRST_FRAME" in ms.read(exe), "el hito queda anotado en reforge_milestones.txt")
check(ms.level_for(d, exe) >= ms.KEY_LEVEL["FIRST_FRAME"], "level_for recoge el hito anotado")

print("Inferencia desde el log (conservadora)")
check(ms.infer_from_log("") == 0, "sin log, nada")
check(ms.infer_from_log("[info] rexglue runtime init") >= ms.KEY_LEVEL["RUNTIME_INIT"], "detecta runtime iniciado")
check(ms.infer_from_log("D3D12 present swapchain frame 1") >= ms.KEY_LEVEL["FIRST_FRAME"], "detecta presentación")
check(ms.infer_from_log("frame time 16ms tirón detectado") >= ms.KEY_LEVEL["PLAYABLE_SCENE"], "detecta juego en marcha")

print("record_from_run anota el hito que demuestra el resultado")
# un log con presentación + cierre limpio => al menos escena jugable
log_dir = os.path.join(d, "logs")
os.makedirs(log_dir, exist_ok=True)
import time
open(os.path.join(log_dir, f"g_{time.time_ns()}.log"), "w").write("vulkan present frame 1\nframe time 16ms\n")
lvl = ms.record_from_run(exe, {"kind": "clean"})
check(lvl >= ms.KEY_LEVEL["FIRST_FRAME"], "tras una partida con frames, anota al menos el primer fotograma")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
