"""Cierre intermitente «Invalid UTF-8»: se reconoce como bug del SDK y NO se confunde con la optimización.

Antes, el diagnóstico veía un [FATAL] cualquiera, lo atribuía a la optimización del código «aún sin probar» y
la bajaba de nivel (max → safe → off), perdiendo rendimiento por un fallo que vive en el runtime precompilado y
que solo aparece en parte de los arranques. Ahora se reconoce, se reintenta el arranque y no se toca nada.

Se prueba el manejador real con un doble ligero del panel (sin ventana): así la prueba no depende de Qt Widgets.

   python tests/test_runtime_race.py
"""
import os
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)

from PySide6.QtCore import QCoreApplication      # noqa: E402

app = QCoreApplication.instance() or QCoreApplication([])
from reforge import game                        # noqa: E402
from reforge.game_options import GameOptions    # noqa: E402
from reforge.pages import WorkshopPage          # noqa: E402

TMP = tempfile.mkdtemp(prefix="reforge-race-")
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


LOG = ("[2026-11-23 17:10:21.115] [debug] [sys] [t15720] Deferred overlapped 41F0E450: running completion\n"
       "[2026-11-23 17:10:21.116] [critical] [core] [t15720] [FATAL] Dispatch thread: deferred completion "
       "threw 'Invalid UTF-8'\n")
OTRO = ("[2026-11-23 17:10:21.116] [critical] [core] [t1] [FATAL] Call to invalid or unregistered function "
        "at guest address 0x88050388\n")

print("Reconocer el cierre intermitente del SDK")
check(game.known_runtime_race(LOG), "reconoce «Invalid UTF-8» en una completion diferida")
check(not game.known_runtime_race(OTRO), "una función no registrada NO es el cierre intermitente")
check(not game.known_runtime_race(""), "sin log no se concluye nada")

print("No degradar la optimización por ese cierre")
logp = os.path.join(TMP, "build", "logs", "juego_001.log")
os.makedirs(os.path.dirname(logp), exist_ok=True)
open(logp, "w", encoding="utf-8").write(LOG)
o = GameOptions()
o.codegen_opt, o.codegen_opt_level, o.codegen_opt_verified = "auto", "safe", False
o.auto_repair = True

mensajes, plays = [], []
page = SimpleNamespace(
    current=None,
    _utf8_retries=0,
    log=SimpleNamespace(write=lambda text, kind="": mensajes.append(text)),
    status_lbl=SimpleNamespace(setText=lambda text: mensajes.append(text)),
    play=lambda auto=False: plays.append(auto),
)
WorkshopPage._handle_crash(page, {"kind": "fatal", "path": logp, "lines": []}, o)
for _ in range(60):
    app.processEvents()
    time.sleep(0.02)
check(o.codegen_opt_level == "safe", "el cierre intermitente deja la optimización en «Segura» (no la apaga)")
check(plays == [True], "vuelve a abrir el juego solo, sin recompilar")
check(any("bug conocido del SDK" in m for m in mensajes), "el log explica que es un bug del SDK")

print("Tres seguidos: se detiene sin tocar nada")
plays.clear()
page._utf8_retries = 2
WorkshopPage._handle_crash(page, {"kind": "fatal", "path": logp, "lines": []}, o)
for _ in range(20):
    app.processEvents()
    time.sleep(0.02)
check(plays == [] and o.codegen_opt_level == "safe",
      "tras 3 arranques seguidos no reabre en bucle ni degrada la optimización")

print(f"\nTodas las pruebas pasaron ({ok}).")
