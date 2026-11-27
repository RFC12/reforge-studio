"""Regresión del cierre de Asura's Wrath: firmas de los intentos 104, 105 y 106.

Antes, un cierre con [FATAL] «deferred completion threw 'Invalid UTF-8'» se clasificaba como `clean` (éxito) y el
Taller lo marcaba ✔/★. Aquí se fija: un [FATAL] nunca es `clean`, el supervisor que lo cierra queda registrado,
el intento 105 (0xC0000409 sin [FATAL]) es un caso APARTE, y se conserva el primer error de cada intento.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import game  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


def write(text):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "asuraswrath_x.log")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


# --- Intento 104: [FATAL] UTF-8, el supervisor cerró el proceso ---------------------------------
log104 = ("[info] rexglue runtime initialized\n"
          "[info] Title terminated\n"                     # el abort deja una línea de cierre…
          "[FATAL] Dispatch thread: deferred completion threw 'Invalid UTF-8'\n")
res104 = game.analyze_runtime_log(write(log104), None)    # exit_code None: lo cerró el supervisor
res104["killed"] = True
print("Intento 104 — [FATAL] deferred 'Invalid UTF-8', cerrado por el supervisor")
check(res104["kind"] == "fatal", "NO es 'clean' aunque el log traiga «Title terminated» (el [FATAL] manda)")
c104 = game.attempt_result(res104)
check(c104["ok"] is False, "la prueba figura como FALLIDA")
check(c104["case"] == "supervisor_killed", "caso: el supervisor cerró el proceso")
check(c104["cause"] == "utf8_deferred", "causa: texto no-UTF-8 en una completion diferida")
check("Invalid UTF-8" in c104["first_error"], "conserva el primer error de la sesión")

# --- Intento 105: 0xC0000409 sin [FATAL], caso aparte -------------------------------------------
log105 = "[info] rexglue runtime initialized\n[info] loading content\n"   # sin [FATAL] ni mensaje fatal
res105 = game.analyze_runtime_log(write(log105), 0xC0000409)
res105["killed"] = False
print("Intento 105 — 0xC0000409 sin [FATAL]")
check(res105["kind"] == "crash", "es un cierre sin firma en el log")
c105 = game.attempt_result(res105)
check(c105["ok"] is False and c105["case"] == "crash_unconfirmed",
      "caso APARTE: causa pendiente de confirmar (no se mezcla con los de UTF-8)")
check(c105["cause"] == "abort_no_fatal", "0xC0000409 sin fatal: aborto por confirmar")

# --- Intento 106: igual que 104 ----------------------------------------------------------------
log106 = ("[info] rexglue runtime initialized\n"
          "[FATAL] Dispatch thread: deferred completion threw 'Invalid UTF-8'\n")
res106 = game.analyze_runtime_log(write(log106), None)
res106["killed"] = True
c106 = game.attempt_result(res106)
print("Intento 106 — mismo fallo que 104")
check(c106["case"] == "supervisor_killed" and c106["cause"] == "utf8_deferred",
      "misma firma que el 104 (supervisor cerró, UTF-8 diferido)")

print("Los tres casos son distinguibles entre sí")
check(c104["case"] == c106["case"] and c105["case"] != c104["case"],
      "104 y 106 comparten caso; el 105 es distinto")

print("La línea [FATAL] no se duplica en el resumen (casa con FATAL y con [critical])")
dup = game.analyze_runtime_log(write("[info] runtime initialized\n"
                                     "[critical] [core] [FATAL] Dispatch thread: deferred completion threw "
                                     "'Invalid UTF-8'\n"), None)
fat = [ln for ln in dup["lines"] if "deferred completion threw" in ln]
check(len(fat) == 1, "la misma línea fatal aparece una sola vez")
check(len(dup["lines"]) == len(set(dup["lines"])), "no hay líneas duplicadas en el resumen")

print("Diagnóstico UNIFICADO: no se atribuye el campo sin traza")
check("pendientes de identificar" in game.UTF8_DEFERRED_MSG, "el mensaje dice que el campo/origen están pendientes")
check("XamContent" not in game.UTF8_DEFERRED_MSG and "contenido" not in game.UTF8_DEFERRED_MSG,
      "no atribuye el fallo a una operación concreta (ni XamContent ni TU) sin la pila")

print("Un cierre LIMPIO sigue siendo éxito (no se rompe lo que funciona)")
clean = game.analyze_runtime_log(write("[info] runtime initialized\nWindow closing, shutting down\n"), 0)
check(game.attempt_result(clean)["ok"] is True, "el juego que se cierra solo sin error cuenta como terminado bien")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
