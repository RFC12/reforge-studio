"""Hitos con evidencia: sin falsos positivos, separación por intentos, última vs mejor, y triaje."""
import os
import sys
import tempfile
import time

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

print("Falsos positivos: una línea de FALLO no confirma un fotograma ni una escena")
check(ms.analyze_text("Vulkan initialization failed")["level"] < ms.KEY_LEVEL["FIRST_FRAME"],
      "«Vulkan initialization failed» NO confirma primer fotograma")
check(ms.analyze_text("swapchain creation failed")["level"] < ms.KEY_LEVEL["FIRST_FRAME"],
      "«swapchain creation failed» NO confirma primer fotograma")
check(ms.analyze_text("stutter monitoring enabled")["level"] < ms.KEY_LEVEL["PLAYABLE_SCENE"],
      "«stutter monitoring enabled» NO confirma escena jugable")
check(ms.analyze_text("Vulkan initialization failed")["first_error"] != "",
      "conserva el primer error del intento")

print("Positivos reales (con evidencia)")
a = ms.analyze_text("rexglue runtime initialized\npresented frame 1 ok\nframe time: 16 ms  fps: 60")
check(a["level"] == ms.KEY_LEVEL["FIRST_FRAME"],
      "init + present + 30/60 FPS → PRIMER FOTOGRAMA (no escena jugable sin entrada)")
check(a["confirmed"].get("FIRST_FRAME", "").startswith("log:"), "guarda la evidencia del fotograma")
check(ms.analyze_text("presented frame 1\ngameplay frame rendered")["level"] == ms.KEY_LEVEL["PLAYABLE_SCENE"],
      "escena jugable solo con señal específica (gameplay), no con FPS del menú")
check(ms.analyze_text("[milestone] INTERACTIVE_MENU")["level"] == ms.KEY_LEVEL["INTERACTIVE_MENU"],
      "el menú interactivo requiere marcador explícito (entrada reconocida)")

print("Separación por intentos, con el primer error de cada uno")
d = tempfile.mkdtemp()
exe = os.path.join(d, "asuraswrath.exe")
open(exe, "wb").write(b"\0" * 10)
logs = os.path.join(d, "logs")
os.makedirs(logs)
# intento 1 (viejo): falla al preparar el renderer
open(os.path.join(logs, "g_1.log"), "w").write("runtime initialized\nVulkan initialization failed\n")
time.sleep(0.02)
# intento 2 (nuevo): presenta y juega
open(os.path.join(logs, "g_2.log"), "w").write("runtime initialized\npresented frame 1\nframe time 16 ms fps 60\n")
ats = ms.attempts(exe)
check(len(ats) == 2, "dos intentos, uno por log")
check(ats[0]["first_error"] and "failed" in ats[0]["first_error"].lower(), "el 1er intento conserva su error")
check(ms.last_session(exe)["level"] == ms.KEY_LEVEL["FIRST_FRAME"], "la última sesión presentó fotogramas (30/60 FPS = primer fotograma, no escena)")

print("Mejor histórico combina exe + marcadores + intentos")
b = ms.best(exe)
check(b["level"] == ms.KEY_LEVEL["FIRST_FRAME"] and "EXE_BUILT" in b["evidence"], "mejor histórico con evidencia")

print("record/read del archivo del runtime (y validación manual)")
ms.record(exe, "INTERACTIVE_MENU", "manual: probé el menú con mando")
check(ms.read(exe).get("INTERACTIVE_MENU", "").startswith("manual:"), "guarda la validación manual identificada")
check(ms.best(exe)["level"] >= ms.KEY_LEVEL["INTERACTIVE_MENU"], "el marcador sube el mejor histórico")

print("Triaje de pantalla negra")
d2 = tempfile.mkdtemp()
exe2 = os.path.join(d2, "g.exe")
open(exe2, "wb").write(b"\0")
os.makedirs(os.path.join(d2, "logs"))
check(ms.triage(exe2) == "antes del código del juego", "exe sin runtime → antes del código del juego")
open(os.path.join(d2, "logs", "a.log"), "w").write("runtime initialized\nswapchain creation failed\n")
check(ms.triage(exe2) == "al preparar el renderer", "runtime sí, fotograma no → al preparar el renderer")
open(os.path.join(d2, "logs", "b.log"), "w").write("runtime initialized\npresented frame 1\n")
time.sleep(0.02)
os.utime(os.path.join(d2, "logs", "b.log"))
check(ms.triage(exe2) == "después de presentar una imagen", "tras presentar → después de presentar una imagen")

print("Dimensiones presentadas que escribe el runtime ([render] presented WxH)")
open(os.path.join(logs, "g_3.log"), "w").write("runtime initialized\n[render] presented 1920x1080\npresented frame 1\n")
check(ms.presented_dims(exe) == (1920, 1080), "lee las dimensiones realmente presentadas del log")

print("summary para el launcher")
s = ms.summary(exe)
check(s["attempts"] == 3 and s["best_desc"] and s["triage"], "resumen con intentos, mejor hito y triaje")
check(s["presented"] == (1920, 1080), "el resumen incluye las dimensiones presentadas")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
