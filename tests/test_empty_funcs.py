"""Inferencia automática del final de las «líneas vacías» (0xADDR = {}) del reforge_functions.toml.

Antes, cuando rexglue no podía acotar una función, dejaba «0xADDR = {}» y había que poner «end»/«parent» a
mano. Aquí se comprueba que infer_empty_function_ends deduce el final (= el inicio de la siguiente función
conocida) sin tocar las que ya lo tienen, y que no inventa un tamaño enorme cuando la siguiente está lejos.
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


def _proj(functions_body):
    d = tempfile.mkdtemp()
    # ensure_include / set_function_end exigen un *_manifest.toml del proyecto.
    with open(os.path.join(d, "juego_manifest.toml"), "w", encoding="utf-8") as f:
        f.write('[project]\nname = "juego"\n\n[entrypoint]\nincludes = []\n')
    with open(os.path.join(d, game.FUNCTIONS_FILE), "w", encoding="utf-8") as f:
        f.write(functions_body)
    return d


# infer_empty_function_ends se apoya en los inicios de funciones conocidas; en el test fijamos que todo cae en
# el módulo y que no hay funciones generadas registradas (solo las declaradas en el toml).
_orig_in_module = game.in_module
_orig_registered = game.registered_functions
game.in_module = lambda root, a: True
game.registered_functions = lambda gen: {}

try:
    print("Detección de líneas vacías (0xADDR = {})")
    d = _proj(
        "[functions]\n"
        "0x82001000 = {}  # llamada indirecta\n"
        "0x82001100 = {}  # llamada indirecta\n"
        "0x82001200 = { end = 0x82001260 }  # ya tenía fin\n"
    )
    vacias = game.empty_function_entries(d)
    check(vacias == {0x82001000, 0x82001100}, "detecta solo las entradas {} vacías")

    print("Inferencia del final")
    inf = dict(game.infer_empty_function_ends(d, [0x82001000, 0x82001100, 0x82001200], ctx=None))
    check(inf == {0x82001000: 0x82001100, 0x82001100: 0x82001200}, "fin = inicio de la siguiente función")
    ends = game.function_ends(d)
    check(ends.get(0x82001000) == 0x82001100, "escribe end de 0x82001000")
    check(ends.get(0x82001100) == 0x82001200, "escribe end de 0x82001100")
    check(ends.get(0x82001200) == 0x82001260, "no toca la que ya tenía end")

    print("No inventa tamaños enormes")
    d2 = _proj("[functions]\n0x82000000 = {}\n0x82900000 = {}\n")  # separadas por > MAX_INFERRED_FUNC_SIZE
    inf2 = game.infer_empty_function_ends(d2, [0x82000000], ctx=None)
    check(inf2 == [], "si la siguiente función está demasiado lejos, no infiere")

    print("Entrada fuera del módulo")
    game.in_module = lambda root, a: False
    d3 = _proj("[functions]\n0x82001000 = {}\n0x82001100 = {}\n")
    inf3 = game.infer_empty_function_ends(d3, [0x82001000], ctx=None)
    check(inf3 == [], "no infiere para direcciones fuera del módulo")
finally:
    game.in_module = _orig_in_module
    game.registered_functions = _orig_registered

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
