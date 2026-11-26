"""Actualización reversible: plan, respaldo/reversión y prueba de arranque (detección de cierre)."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import migrate, toolchain  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


print("Plan de actualización: detecta si hay un SDK más nuevo instalado")
toolchain.installed_sdks = lambda: [("0.10.0.24-dev-fsr", "/sdk/0.10", "/sdk/0.10/rexglue.exe"),
                                    ("0.11.0.13-dev", "/sdk/0.11", "/sdk/0.11/rexglue.exe")]


class Cfg:
    rexglue_sdk = "/sdk/0.10/win-amd64"
    rexglue = ""

    def path(self):
        return "/tmp/x"


# project_sdk lee de cfg.rexglue_sdk → basename(dirname) = '0.10' en este montaje de prueba; forzamos uno real:
migrate.project_sdk = lambda cfg: "0.10.0.24-dev-fsr"
p = migrate.plan(Cfg(), "/tmp")
check(p["available"] is True and p["to"].startswith("0.11"), "ve que 0.11 es más nuevo que 0.10")
check(p["same_family"] is False, "0.10→0.11 se marca como cambio de familia (mayor riesgo)")

migrate.project_sdk = lambda cfg: "0.11.0.13-dev"
p2 = migrate.plan(Cfg(), "/tmp")
check(p2["available"] is False, "si ya está en la más nueva, no hay actualización")

print("Respaldo y reversión reconstruyen el proyecto anterior")
root = tempfile.mkdtemp()
os.makedirs(os.path.join(root, "src"), exist_ok=True)
os.makedirs(os.path.join(root, "generated"), exist_ok=True)
open(os.path.join(root, "reforge_game.json"), "w").write('{"v":10}')
open(os.path.join(root, "src", "a.cpp"), "w").write("// SDK 0.10")
open(os.path.join(root, "juego_manifest.toml"), "w").write('sdk_version = "0.10.0"')
check(migrate.backup(root, "antes de 0.11") and migrate.has_backup(root), "respalda el proyecto")

# simular la actualización: se cambia el código y el manifest a 0.11
open(os.path.join(root, "src", "a.cpp"), "w").write("// SDK 0.11 (roto)")
open(os.path.join(root, "juego_manifest.toml"), "w").write('sdk_version = "0.11.0"')
open(os.path.join(root, "reforge_game.json"), "w").write('{"v":11}')

check(migrate.restore(root), "revierte desde el respaldo")
check(open(os.path.join(root, "src", "a.cpp")).read() == "// SDK 0.10", "el código vuelve al de 0.10")
check('sdk_version = "0.10.0"' in open(os.path.join(root, "juego_manifest.toml")).read(), "el manifest vuelve a 0.10")
check('"v":10' in open(os.path.join(root, "reforge_game.json")).read(), "la config del juego vuelve a 0.10")

print("Prueba de arranque: detecta un cierre tras actualizar")
build = os.path.join(root, "build")
logs = os.path.join(build, "logs")
os.makedirs(logs, exist_ok=True)
exe = os.path.join(build, "juego.exe")
open(exe, "wb").write(b"MZ")
t0 = time.time()
open(os.path.join(logs, "run_01.log"), "w").write("iniciando\n[FATAL] Dispatch thread: deferred completion threw 'x'\n")
sign = migrate.crashed_after(exe, t0)
check(sign != "", f"detecta el cierre en el log nuevo ({sign})")

open(os.path.join(logs, "run_02.log"), "w").write("arrancó y sigue jugando, todo bien\n")
os.utime(os.path.join(logs, "run_02.log"), (time.time() + 5, time.time() + 5))
check(migrate.crashed_after(exe, time.time() + 4) == "", "un arranque limpio no se marca como cierre")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
