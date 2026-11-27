"""Mecanismo de atribución del runtime instrumentado: dos tareas en la MISMA dirección overlapped, una termina
bien y la otra lanza; la traza debe atribuir el fallo a la SEGUNDA (como pidió el usuario)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import deferred_trace as dt  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


# Reproduce el patrón del 121: dos tareas reutilizan overlapped 41F0FF50; la 1 termina 0, la 2 lanza.
LOG = """\
[00:00:00.001] [warning] [sys] [t100] [deferred] enqueue id=1 ra=0x7ffab0001234 thread=0x1A2B overlapped=41F0FF50
[00:00:00.002] [warning] [sys] [t200] [deferred] run id=1 overlapped=41F0FF50
[00:00:00.003] [warning] [sys] [t200] [deferred] done id=1 result=00000000
[00:00:00.060] [warning] [sys] [t100] [deferred] enqueue id=2 ra=0x7ffab0009abc thread=0x1A2B overlapped=41F0FF50
[00:00:00.061] [warning] [sys] [t200] [deferred] run id=2 overlapped=41F0FF50
[00:00:00.160] [critical] [core] [t200] [FATAL] Dispatch thread: deferred completion (task 2 ra=0x7ffab0009abc) threw 'Invalid UTF-8'
"""

print("Detecta que el log viene de un runtime instrumentado")
check(dt.is_instrumented(LOG), "reconoce las líneas [deferred] enqueue id=")

print("Atribuye el fatal a la tarea correcta aunque comparta la dirección overlapped")
a = dt.attribute(LOG)
check(a is not None and a["id"] == 2, "la tarea que falló es la #2, no la #1 que terminó bien")
check(a["ra"] == "0x7ffab0009abc", "da la dirección de retorno del encolador de la #2")
check(a["overlapped"] == "41F0FF50", "y la dirección overlapped reutilizada")
check(a["completed_same_overlapped"] == [1], "identifica que la #1 usó esa misma dirección y terminó bien")
check(a["enqueue"] and a["enqueue"]["ra"] == "0x7ffab0009abc", "enlaza el fatal con su línea de encolado")
check(a["message"] == "Invalid UTF-8", "conserva el texto de la excepción")

print("La línea de resumen explica la atribución")
s = dt.summary(LOG)
check("#2" in s and "0x7ffab0009abc" in s and "no son la causa" in s, "el resumen nombra la tarea y descarta la #1")

print("Sin instrumentar o sin fatal, no inventa nada")
check(dt.attribute("[info] runtime initialized\n") is None, "log normal → sin atribución")
check(dt.summary("") == "", "log vacío → resumen vacío")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
