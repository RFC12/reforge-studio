"""Autoreinicio de ReForge tras actualizar: update.install añade --relaunch."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reforge.update as upd  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


# Simular Windows y capturar los argumentos que recibiría el instalador.
capturado = {}


class FakePopen:
    def __init__(self, args, **kw):
        capturado["args"] = args
        capturado["kw"] = kw


upd.sys.platform = "win32"
upd.subprocess.Popen = FakePopen
upd.os.path.isfile = lambda p: True   # fingir que el instalador descargado existe

print("install(relaunch=True) pasa --relaunch para que ReForge se reabra solo")
upd.install("C:/tmp/Setup.exe", silent=True, relaunch=True)
check("--relaunch" in capturado["args"] and "--silent" in capturado["args"],
      "la instalación silenciosa con autoreinicio incluye --silent y --relaunch")

print("install(relaunch=False) no añade --relaunch")
capturado.clear()
upd.install("C:/tmp/Setup.exe", silent=True, relaunch=False)
check("--relaunch" not in capturado["args"], "sin autoreinicio, no se pasa --relaunch")

print("install detached (no bloquea la app)")
check(capturado["kw"].get("close_fds") is True, "lanza el instalador separado del proceso de ReForge")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
