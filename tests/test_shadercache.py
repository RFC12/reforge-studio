"""Pruebas de la caché de shaders y del ajuste por RAM.  python tests/test_shadercache.py"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-cache-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)

from reforge import shadercache as sc  # noqa: E402
from reforge.optimizer import _texture_budget, tuned_values  # noqa: E402

TID = "4D53082D"
HOME = os.path.join(TMP, "home")
sc.documents_dir = lambda: os.path.join(HOME, "Documents")


def make_game(name, sizes):
    """Crea la caché de un juego: sizes = {'xsh': n, 'rtv': n, 'rov': n}."""
    exe = os.path.join(TMP, name, f"{name}.exe")
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    open(exe, "wb").close()
    folder = sc.cache_dir(exe)
    os.makedirs(folder, exist_ok=True)
    for kind, size in sizes.items():
        fn = f"{TID}.xsh" if kind == "xsh" else f"{TID}.{kind}.d3d12.xpso"
        with open(os.path.join(folder, fn), "wb") as f:
            f.write(b"\0" * size)
    return exe


def check(cond, msg):
    print(("  ok  " if cond else "FALLA ") + msg)
    assert cond, msg


print("== estado de la caché")
exe_a = make_game("juegoA", {"xsh": 4000, "rtv": 2000})
st = sc.status(exe_a, TID, "rtv")
check(st["exists"] and st["total"] == 6000, "cuenta los archivos del juego")
check(st["paths"] == {"rtv": 2000}, "ve los pipelines de RTV")
check(not st["cold"], "con RTV elegido, la caché no está fría")
check(sc.status(exe_a, TID, "rov")["cold"], "al cambiar a ROV avisa de que esa ruta está vacía")
check("MB" in sc.describe(st), "describe la caché")

print("== no se mezclan juegos distintos")
folder = sc.cache_dir(exe_a)
open(os.path.join(folder, "11111111.xsh"), "wb").write(b"\0" * 99)
check(sc.status(exe_a, TID)["total"] == 6000, "ignora la caché de otro juego en la misma carpeta")

print("== reaprovechar otro proyecto del mismo juego")
exe_b = make_game("juegoB", {})
check(sc.status(exe_b, TID)["exists"] is False, "el proyecto nuevo empieza sin caché")
others = sc.other_caches(exe_b, TID)
check(len(others) == 1, "encuentra la caché del otro proyecto")
msg = sc.reuse_existing(exe_b, TID)
check(msg and sc.status(exe_b, TID)["total"] == 6000, "la copia entera: " + msg[:60])
check(not os.path.exists(os.path.join(sc.cache_dir(exe_b), "11111111.xsh")), "sin colarse la de otro juego")

print("== no pisa una caché más completa")
exe_c = make_game("juegoC", {"xsh": 9000})
sc.reuse_existing(exe_c, TID)
check(sc.status(exe_c, TID)["shaders_bytes"] == 9000, "conserva la suya si es mayor")

print("== copia dentro del proyecto")
proj = os.path.join(TMP, "proyecto")
os.makedirs(proj, exist_ok=True)
check(sc.backup(proj, exe_a, TID) == 6000, "guarda la caché en el proyecto")
sc.clear(exe_a, TID)
check(not sc.status(exe_a, TID)["exists"], "se borra la caché del juego")
check(sc.restore(proj, exe_a, TID), "se restaura desde el proyecto")
check(sc.status(exe_a, TID)["total"] == 6000, "y vuelve completa")

print("== exportar e importar")
zp = os.path.join(TMP, "cache.zip")
check(sc.export_zip(exe_a, TID, zp) == zp, "exporta a .zip")
exe_d = make_game("juegoD", {})
check(sc.import_zip(exe_d, TID, zp) == 2, "importa los 2 archivos")
check(sc.import_zip(exe_d, "99999999", zp) == 0, "no importa la caché de otro juego")

print("== presupuesto de texturas según VRAM y RAM")
check(_texture_budget(16000, 32768) == (2048, 4096, 128), "16 GB de VRAM y 32 de RAM: el máximo")
check(_texture_budget(16000, 8192)[1] == 1024, "con 8 GB de RAM se limita aunque sobre VRAM")
check(_texture_budget(16000, 0) == (2048, 4096, 128), "sin dato de RAM, manda la VRAM")
check(_texture_budget(2000, 32768) == (384, 768, 24), "GPU pequeña: valores de rexglue")
v = tuned_values({"vram_mb": 16000, "ram_mb": 32768, "cpu_threads": 24}, "fluido")
check(v["gpu_debug_markers"] is False, "apaga las marcas de depuración de la GPU")
check(tuned_values({}, "off") == {}, "desactivado no escribe nada")

print("\nTodo correcto.")
