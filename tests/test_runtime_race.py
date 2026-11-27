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
check(game.known_runtime_race(LOG.replace("'Invalid UTF-8'", "'Not enough space'")),
      "reconoce el mismo cierre con otro mensaje del SDK («Not enough space»)")
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
WorkshopPage._handle_crash(page, {"kind": "fatal", "path": logp, "lines": [], "utf8": True}, o)
for _ in range(60):
    app.processEvents()
    time.sleep(0.02)
check(o.codegen_opt_level == "safe", "el cierre por UTF-8 deja la optimización en «Segura» (no la apaga)")
check(plays == [True], "vuelve a abrir el juego solo (para ver si es constante), sin recompilar")
check(any("runtime/SDK" in m for m in mensajes),
      "el log atribuye la causa al runtime/SDK (no al código recompilado), sin venderlo como carrera benigna")

print("El aborto del runtime sin línea en el log tampoco baja la optimización")
logp2 = os.path.join(TMP, "build", "logs", "juego_002.log")
open(logp2, "w", encoding="utf-8").write("[2026-11-23 18:19:56.626] [info] [core] [t1] [ReForge] FPS 30 · peor 35 ms\n"
                                          "[2026-11-23 18:20:01.324] [warning] [krnl] [t2] __imp__XNetLogonGetTitleID STUB\n")
ABORTO = {"kind": "crash", "path": logp2, "crash": "comprobación de seguridad (0xC0000409)",
          "hotplug": False, "lines": []}
check(game.runtime_abort(ABORTO), "0xC0000409 sin nada en el log que señale al juego recompilado")
logp3 = os.path.join(TMP, "build", "logs", "juego_003.log")
open(logp3, "w", encoding="utf-8").write("Unhandled guest access violation: read of guest 0x00000000\n")
check(not game.runtime_abort({**ABORTO, "path": logp3}), "un acceso inválido del juego no es el aborto del runtime")
check(not game.runtime_abort({**ABORTO, "kind": "fatal", "crash": ""}), "sin 0xC0000409 no se da por bueno")
plays.clear()
page._utf8_retries = 0
WorkshopPage._handle_crash(page, ABORTO, o)
for _ in range(60):
    app.processEvents()
    time.sleep(0.02)
check(o.codegen_opt_level == "safe" and plays == [True],
      "se reabre el juego, sin bajar de nivel ni mantenimiento completo")

print("Tres seguidos: se detiene sin tocar nada")
plays.clear()
page._utf8_retries = 2
WorkshopPage._handle_crash(page, {"kind": "fatal", "path": logp, "lines": []}, o)
for _ in range(20):
    app.processEvents()
    time.sleep(0.02)
check(plays == [] and o.codegen_opt_level == "safe",
      "tras 3 arranques seguidos no reabre en bucle ni degrada la optimización")

print("Con «Desactivada» también se cierra: la optimización no era la causa")
proj = os.path.join(TMP, "proj_off")
os.makedirs(proj, exist_ok=True)
o2 = GameOptions()
o2.codegen_opt, o2.codegen_opt_level, o2.codegen_opt_verified = "auto", "off", False
o2.auto_repair = True
avisos = []
page.current = None
page.log = SimpleNamespace(write=lambda text, kind="": avisos.append(text))
CIERRE = {"kind": "crash", "path": logp3, "hotplug": False, "lines": []}
destino = SimpleNamespace(root=proj)
check(not WorkshopPage._codegen_step_down(page, destino, o2, CIERRE) and
      o2.codegen_opt_level == "safe" and o2.codegen_opt_exonerated,
      "se vuelve a «Segura» y se anota que la optimización queda descartada")
check(any("Desactivada" in m and "Segura" in m for m in avisos), "el log lo explica")
o2.codegen_opt_level = "off"
check(not WorkshopPage._codegen_step_down(page, destino, o2, CIERRE) and o2.codegen_opt_level == "off",
      "ya no se vuelve a bajar de nivel en los cierres siguientes")
o3 = GameOptions()
o3.codegen_opt, o3.codegen_opt_level, o3.auto_repair = "auto", "safe", True
check(WorkshopPage._codegen_step_down(page, destino, o3, CIERRE) or o3.codegen_opt_level == "off",
      "desde «Segura» se sigue bajando a «Desactivada» como antes")

print(f"\nTodas las pruebas pasaron ({ok}).")
