"""Base de datos de problemas conocidos y guardarraíl de funciones fuera del módulo."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import game, knownissues        # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


def proyecto_con_rango(lo=0x82000000, code_lo=0x823E0000, code_hi=0x831F0000, hi=0x83620000):
    """Un proyecto falso cuyo module_range está fijado, sin necesitar un XEX real."""
    root = tempfile.mkdtemp(prefix="reforge-ki-")
    os.makedirs(os.path.join(root, "assets"))
    # un manifest mínimo para que ensure_include/declare tengan dónde escribir el include
    with open(os.path.join(root, "proy_manifest.toml"), "w", encoding="utf-8") as f:
        f.write('[entrypoint]\nfile_path = "assets/default.xex"\nincludes = ["reforge_functions.toml"]\n')
    game.module_range = lambda r, _c=(code_lo, code_hi, lo, hi): _c   # noqa: E731
    return root


print("Reconocer el fallo de Forza (función fuera del módulo)")
LOG_FORZA = ("[error] [core] SetFunction: address 88050388 outside all registered module ranges\n"
             "[error] [sys] PPCImageInfo registration: 1 func_mappings entries rejected\n"
             "[error] [core] Runtime setup failed: C0000001\n")
issue = knownissues.diagnose(LOG_FORZA, {})
check(issue is not None and issue.id == "funcs_fuera_del_modulo", "se identifica por su huella en el log")
check(issue.remedio is not None and issue.recompila, "trae remedio automático y pide recompilar")

print("El guardarraíl no declara direcciones fuera del módulo")
root = proyecto_con_rango()
check(game.in_module(root, 0x82500000) is True, "una dirección dentro del módulo se acepta")
check(game.in_module(root, 0x88050388) is False, "la de Forza (0x88050388) se reconoce como fuera")
check(game.declare_runtime_function(root, 0x88050388) is False, "no se declara una función fuera del módulo")
check(0x88050388 in game.rejected_functions(root), "y queda anotada como «no es función» para no reintentarla")
dentro = 0x82500000
check(game.declare_runtime_function(root, dentro) is True, "una dirección válida sí se declara")
check(dentro in game.declared_functions(root), "y aparece en reforge_functions.toml")

print("La poda limpia un proyecto ya roto")
root2 = proyecto_con_rango()
os.makedirs(os.path.join(root2), exist_ok=True)
with open(os.path.join(root2, game.FUNCTIONS_FILE), "w", encoding="utf-8") as f:
    f.write("# prueba\n\n[functions]\n")
    f.write("0x823F1234 = {}  # salto desde 0x823F0000\n")      # dentro
    f.write("0x88050388 = {}  # llamada indirecta detectada al ejecutar el juego\n")  # fuera
    f.write("0x8305ABCC = {}  # entrada encontrada por el análisis profundo\n")        # dentro
quitadas = game.prune_bad_functions(root2)
check(quitadas == [0x88050388], "quita solo la que está fuera del módulo")
quedan = game.declared_functions(root2)
check(0x823F1234 in quedan and 0x8305ABCC in quedan and 0x88050388 not in quedan,
      "las buenas se conservan y la mala desaparece")

print("auto_heal aplica el remedio y pide recompilar")
root3 = proyecto_con_rango()
with open(os.path.join(root3, game.FUNCTIONS_FILE), "w", encoding="utf-8") as f:
    f.write("[functions]\n0x88050388 = {}  # llamada indirecta\n0x82410000 = {}  # salto\n")
msgs, recompila = knownissues.auto_heal(root3, "", LOG_FORZA, {})
check(recompila is True, "señala que hay que recompilar")
check(any("0x88050388" in m for m in msgs), "y explica qué quitó")
check(game.prune_bad_functions(root3) == [], "después ya no queda nada fuera del módulo")

print("El salto a un puntero sin resolver se diagnostica (sin arreglo falso)")
LOG_EXEC = ("[error] [cpu] Execute(88050800): function not in function table\n"
            "[critical] [core] [FATAL] Call to invalid or unregistered function at guest address 0x88050388\n")
root_e = proyecto_con_rango()
iss = knownissues.diagnose(LOG_EXEC, {"root": root_e})
check(iss is not None and iss.id == "ejecuta_fuera_del_modulo", "se reconoce el Execute() fuera del módulo")
check(iss.remedio is None and iss.consejo, "no finge un arreglo automático: da un consejo honesto")
msgs, rec = knownissues.auto_heal(root_e, "", LOG_EXEC, {"root": root_e})
check(rec is False, "auto_heal no recompila por esto (no hay nada que tocar)")

print("Otros problemas conocidos están en la tabla")
ids = {i.id for i in knownissues.ISSUES}
for esperado in ("heap_agotado", "cache_shaders_danada", "mando_reconectado", "llamada_fuera_rango"):
    check(esperado in ids, f"está «{esperado}»")
check(knownissues.diagnose("todo bien, nada que ver aquí", {}) is None, "un log limpio no inventa un problema")

print()
print(f"{len(fallos)} fallos" if fallos else "0 fallos")
sys.exit(1 if fallos else 0)
