"""Entradas de función que caen a mitad de otra función (saltos a colas compartidas).

Crash of the Titans saltaba de 0x823E8D70 a 0x823E9C10 (dentro de 0x823E9C04). ReForge declaraba la
dirección como función para resolver el aviso, el código generado empezaba a mitad de la función y el juego
moría en el primer fotograma con «unhandled title read of 0x701A0000». Aquí se comprueba que esas direcciones
se detectan (su valor es el regreso de una llamada), no se declaran, y se quitan si ya estaban.
python tests/test_midfunc.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-midfunc-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)

from reforge import game, knownissues  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


def project():
    root = tempfile.mkdtemp(prefix="reforge-mid-")
    with open(os.path.join(root, "juego_manifest.toml"), "w", encoding="utf-8") as f:
        f.write('[project]\nname = "juego"\n\n[entrypoint]\nout_directory_path = "generated/default"\n')
    gen = os.path.join(root, "generated", "default")
    os.makedirs(gen)
    with open(os.path.join(gen, "juego_recomp.5.cpp"), "w", encoding="utf-8") as f:
        f.write("DEFINE_REX_FUNC(sub_823E9C04) {\n"
                "\t// bl 0x823e8d80\n"
                "\tctx.lr = 0x823E9C08;\n"
                "\tsub_823E8D80(ctx, base);\n"
                "\t// bl 0x8242fbd4\n"
                "\tctx.lr = 0x823E9C10;\n"
                "\t__imp__KeBugCheck(ctx, base);\n}\n")
    return root


print("Se reconoce el regreso de una llamada")
root = project()
gen = game.generated_dir(root)
lrs = game.return_addresses(gen)
check(0x823E9C10 in lrs, "0x823E9C10 es el regreso de la llamada a KeBugCheck")
check(0x823E9C08 in lrs, "0x823E9C08 es el regreso de la llamada anterior")

print("No se declara como función")
game.add_functions(root, [(0x823E9C10, 0x823E8D70), (0x82400000, 0x823E8D70)])
toml = open(os.path.join(root, game.FUNCTIONS_FILE), encoding="utf-8").read()
check("0x82400000" in toml, "el salto a una función de verdad sí se declara")
check("0x823E9C10" not in toml, "el que cae a mitad de otra función no")
check(0x823E9C10 in game.rejected_functions(root), "queda anotado como «no es función»")

print("Y se quita si ya estaba declarado")
root = project()
with open(os.path.join(root, game.FUNCTIONS_FILE), "w", encoding="utf-8") as f:
    f.write("[functions]\n0x823E9C10 = {}  # salto desde 0x823E8D70\n0x82400000 = {}  # salto desde 0x823E8D70\n")
    f.write("0x823E9C08 = {}  # entrada encontrada por el análisis profundo\n")
quitadas = game.prune_mid_function_entries(root)
toml = open(os.path.join(root, game.FUNCTIONS_FILE), encoding="utf-8").read()
check(quitadas == [0x823E9C10], "devuelve la quitada")
check("0x823E9C10" not in toml and "0x82400000" in toml, "solo se va la que partía la función")
check("0x823E9C08" in toml, "las entradas secundarias del análisis profundo se respetan")
check(0x823E9C10 in game.rejected_functions(root), "anotada para que no vuelva")
check(game.prune_mid_function_entries(root) == [], "la segunda vez no hay nada que quitar")

print("La base de problemas lo reconoce")
iss = knownissues.diagnose("C cpu Unresolved call from 0x823E8D70 to 0x823E9C10", {})
check(iss is not None and iss.id == "salto_a_mitad_de_funcion", "por el aviso de rexglue")
iss = knownissues.diagnose("W core SEH exception caught in sub_82264F40\n"
                           "C system unhandled title read of 0x701A0000, guest address 0x701A0000", {})
check(iss is not None and iss.id == "salto_a_mitad_de_funcion", "por el fallo de memoria tras el salto")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
