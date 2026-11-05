"""Funciones partidas («Unresolved branch»): se quitan solas las entradas culpables.   python tests/test_split.py"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-split-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)
from reforge import game  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


root = os.path.join(TMP, "codaw")
gen = os.path.join(root, "generated", "default")
os.makedirs(gen)
open(os.path.join(root, "codaw_manifest.toml"), "w").write("[entrypoint]\nfile = 'default.xex'\n")
game.ensure_include(root)
with open(os.path.join(root, game.FUNCTIONS_FILE), "w", encoding="utf-8") as f:
    f.write("[functions]\n"
            "0x82450000 = {}  # entrada encontrada por el análisis profundo\n"
            "0x8244FFF0 = {}  # salto desde 0x8245004C\n"
            "0x82300000 = {}  # llamada indirecta detectada al ejecutar el juego\n"
            "0x82600000 = {}  # entrada encontrada por el análisis profundo\n")
open(os.path.join(gen, "codaw_recomp.80.cpp"), "w").write(
    'PPC_FUNC_IMPL(__imp__sub_82450000) {\n\tif (ctx.cr6.lt) REX_FATAL("Unresolved branch from 0x8245004C to '
    '0x8244FFF0");\n}\n')
log = []


class Ctx:
    def log(self, msg, *_a):
        log.append(msg)


removed = game.fix_split_functions(root, Ctx())
check(removed == [0x8244FFF0, 0x82450000], "quita la entrada que partía la función y el destino declarado por el salto")
left = game.declared_functions(root)
check(left == {0x82300000, 0x82600000}, "las demás entradas se conservan")
check(game.rejected_functions(root) == {0x8244FFF0, 0x82450000}, "anotadas como «no es función»")
check(game.declare_functions(root, [0x82450000, 0x82700000], "análisis profundo") == [0x82700000],
      "ningún análisis las vuelve a declarar")
check(game.add_functions(root, [(0x8244FFF0, 0x8245004C)]) == [], "tampoco como destino de salto")
check(game.declare_runtime_function(root, 0x82450000), "pero una llamada real en ejecución sí manda")
check(game.fix_split_functions(root) == [], "sin saltos que corregir entre entradas removibles: nada")

logf = os.path.join(TMP, "codaw_007.log")
open(logf, "w").write("[2026-10-22 10:31:08.132] [critical] [core] [t24896] [FATAL] Unresolved branch from "
                      "0x8245004C to 0x8244FFF0\n")
res = game.analyze_runtime_log(logf, 3221226505)
check(res["kind"] == "split" and res["branch"] == (0x8245004C, 0x8244FFF0), "el log del juego se reconoce como función partida")

print("Una lista de funciones por versión del juego")
base_txt = open(os.path.join(root, game.FUNCTIONS_FILE), encoding="utf-8").read()
man = os.path.join(root, "codaw_manifest.toml")
open(man, "a").write("setjmp_address = 0x826D7240   # ReForge\nlongjmp_address = 0x826E5CA0\n")
game.switch_function_set(root, "base", "tu-0.0.17.16")
check("setjmp_address" not in open(man).read() and "longjmp_address" not in open(man).read(),
      "las direcciones de setjmp/longjmp de la otra versión se quitan (se detectan de nuevo)")
check("[functions]" in open(os.path.join(root, game.FUNCTIONS_FILE), encoding="utf-8").read() and
      not game.declared_functions(root) and not game.rejected_functions(root),
      "con la actualización se empieza una lista limpia (las direcciones del juego base ya no valen)")
game.declare_functions(root, [0x82999990], "análisis profundo")
game.switch_function_set(root, "tu-0.0.17.16", "base")
check(open(os.path.join(root, game.FUNCTIONS_FILE), encoding="utf-8").read() == base_txt and
      game.rejected_functions(root) == {0x8244FFF0, 0x82450000}, "al quitarla vuelve la lista del juego base")
game.switch_function_set(root, "base", "tu-0.0.17.16")
check(game.declared_functions(root) == {0x82999990}, "y al reinstalarla, la de la actualización")
game.switch_function_set(root, "tu-0.0.17.16", "base")

print("Análisis profundo")
from reforge import deepscan  # noqa: E402
import struct  # noqa: E402
base = 0x82000000
code_words = [0] * 0x8000
# lis r11,0x8245 ; addi r11,r11,0  → dirección redonda (se ignora)
code_words[10] = (15 << 26) | (11 << 21) | 0x8245
code_words[11] = (14 << 26) | (11 << 21) | (11 << 16) | 0
# lis r10,0x8200 ; ori r9,r10,0x1230 → 0x82001230 (ori: registro de origen en los bits 21-25)
code_words[20] = (15 << 26) | (10 << 21) | 0x8200
code_words[21] = (24 << 26) | (10 << 21) | (9 << 16) | 0x1230
image = struct.pack(">%dI" % len(code_words), *code_words)
sec = 0x100
xex = bytearray(0x400)
struct.pack_into(">IIII", xex, 4, 0, 0x400, 0, sec)
struct.pack_into(">II", xex, sec + 0x10C, 0x10000000, base)
struct.pack_into(">I", xex, sec + 0x180, 1)
struct.pack_into(">I", xex, sec + 0x184, ((len(image) // 4096) << 4) | 1)
found = deepscan.scan(image, bytes(xex), {base, 0x82001000})
check(0x82450000 not in found, "una dirección redonda de 64 KB no se toma por función")
check(0x82001230 in found, "lis + ori leído con el registro correcto")
print(f"\nTodas las pruebas pasaron ({ok}).")
