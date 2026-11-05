"""Funciones cortadas por el análisis de rexglue («use of undeclared label», Castle Crashers).
   python tests/test_truncated.py"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-trunc-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)

from reforge import game  # noqa: E402
from reforge.core import AppConfig  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


# Lo que generó rexglue para Castle Crashers (sub_82112BC0 cortada en 0x82112F6C).
BAD = """DEFINE_REX_FUNC(sub_82112BC0) {
\tREX_FUNC_PROLOGUE();
\tswitch (ctx.r11.u32) {
\tcase 4:
\t\tsub_82112D10(ctx, base);
\t\treturn;
\t}
loc_82112D44:
\tgoto loc_82112F90;
\tgoto loc_82112F78;
loc_82112F5C:
\tgoto loc_82112F70;
\tgoto loc_82112F5C;
}

DEFINE_REX_FUNC(sub_82119950) {
loc_82119958:
\tgoto loc_82119958;
}
"""
GOOD = BAD.replace("\tgoto loc_82112F70;\n\tgoto loc_82112F5C;\n}",
                   "\tgoto loc_82112F70;\nloc_82112F70:\nloc_82112F78:\nloc_82112F90:\n\treturn;\n}")
REGISTER = """  registrar->SetFunction(0x82112BC0, sub_82112BC0);
  registrar->SetFunction(0x82112D10, sub_82112D10);
  registrar->SetFunction(0x82112FA0, sub_82112FA0);
  registrar->SetFunction(0x82119950, sub_82119950);
"""


def project(path, generated=BAD):
    os.makedirs(os.path.join(path, "generated", "default"), exist_ok=True)
    open(os.path.join(path, "castlecrashers_manifest.toml"), "w").write(
        '[project]\nname = "castlecrashers"\n\n[entrypoint]\nfile_path = "assets/default.xex"\n'
        'out_directory_path = "generated/default"\nincludes = ["reforge_functions.toml"]\n')
    open(os.path.join(path, "reforge_functions.toml"), "w").write(
        "[functions]\n0x820E15E8 = {}  # salto desde 0x820E0D04\n")
    open(os.path.join(path, "generated", "default", "castlecrashers_recomp.16.cpp"), "w").write(generated)
    open(os.path.join(path, "generated", "default", "castlecrashers_register.cpp"), "w").write(REGISTER)


print("Detección y corrección")
p1 = os.path.join(TMP, "p1")
project(p1)
gen = game.generated_dir(p1)
check(game.find_missing_labels(gen) == {0x82112BC0: {0x82112F70, 0x82112F78, 0x82112F90}},
      "encuentra las 3 etiquetas que faltaban en sub_82112BC0 (las del log)")
fixed = game.fix_truncated_functions(p1)
toml = open(os.path.join(p1, "reforge_functions.toml")).read()
check(fixed == [(0x82112BC0, 0x82112FA0)] and "0x82112BC0 = { end = 0x82112FA0 }" in toml,
      "declara que termina en la siguiente función registrada (0x82112FA0)")
check("0x820E15E8 = {}" in toml, "conserva las funciones ya declaradas")
check(game.fix_truncated_functions(p1) == [], "no repite una corrección ya hecha")
check(game.find_missing_labels(os.path.join(TMP, "nada")) == {}, "sin código generado no hace nada")

print("Durante la compilación")
FAKE = r'''
import os, re, sys
root = os.getcwd()
gen = os.path.join(root, "generated", "default", "castlecrashers_recomp.16.cpp")
if "--target" in sys.argv:                       # codegen: respeta el final declarado
    fixed = "end = 0x82112FA0" in open(os.path.join(root, "reforge_functions.toml")).read()
    open(gen, "w").write(GOOD if fixed else BAD)
    open(os.path.join(root, "codegen_runs"), "a").write("x")
    print("Codegen summary: 41 written"); sys.exit(0)
txt = open(gen).read()
if "loc_82112F90:" not in txt:
    print("castlecrashers_recomp.16.cpp:27609:7: error: use of undeclared label 'loc_82112F90'")
    print("ninja: build stopped: subcommand failed."); sys.exit(1)
print("[26/26] Linking CXX executable castlecrashers.exe")
'''
fake = os.path.join(TMP, "fakecmake.py")
open(fake, "w").write(f"BAD = {BAD!r}\nGOOD = {GOOD!r}\n" + FAKE)
import reforge.core as core_mod  # noqa: E402
import reforge.game_profiles as gp  # noqa: E402
core_mod.cmake_build_cmd = lambda c, b: [sys.executable, fake, "--build", b]
game.cmake_codegen_cmd = lambda c, b, n: [sys.executable, fake, "--build", b, "--target", f"{n}_codegen"]
gp.apply_game_profile = lambda *a, **k: None


class Ctx:
    def __init__(self):
        self.msgs = []

    def log(self, t, level="info"):
        self.msgs.append(t)

    def progress(self, *a):
        pass

    def cancelled(self):
        return False


p2 = os.path.join(TMP, "p2")
project(p2)
cx = Ctx()
game.codegen_with_autofix(AppConfig(), p2, os.path.join(p2, "build"), "castlecrashers", dict(os.environ), cx)
check(game.find_missing_labels(game.generated_dir(p2)) == {} and
      open(os.path.join(p2, "codegen_runs")).read() == "xx", "el codegen lo detecta, lo corrige y regenera")
check(any("cortadas por el análisis" in m for m in cx.msgs), "lo explica en el log")

p3 = os.path.join(TMP, "p3")                      # proyecto generado con una versión anterior
project(p3)
cx = Ctx()
game.build_with_ext_fallback(AppConfig(), p3, os.path.join(p3, "build"), dict(os.environ), cx)
check(any("Linking" in m for m in cx.msgs) and "end = 0x82112FA0" in
      open(os.path.join(p3, "reforge_functions.toml")).read(),
      "si el error aparece al compilar, corrige, regenera y compila (el error del log de Castle Crashers)")
print("Saltos a código sin función (Gears of War 2)")
warn = ["Unresolved b target 0x82B3EB88 from 0x82B3EAC0",
        "Unresolved function 0x82B3EB88 from 0x82B3EAC0 (no CallTarget in FunctionNode)",
        "Unresolved b target 0x82B64C9C from 0x82B64BD4"]
check(game.parse_unresolved_warnings(warn) == [(0x82B3EB88, 0x82B3EAC0), (0x82B64C9C, 0x82B64BD4)],
      "lee los avisos «Unresolved b target» sin duplicados")
p4 = os.path.join(TMP, "p4")
project(p4, GOOD)
runs = []


def fake_stream(cmd, cwd, env, ctx):
    runs.append(1)
    return 0, (warn if len(runs) == 1 else ["Codegen summary: 449 written"])


orig = game.run_streaming
game.run_streaming = fake_stream
game.codegen_with_autofix(AppConfig(), p4, os.path.join(p4, "build"), "castlecrashers", {}, Ctx())
game.run_streaming = orig
check(len(runs) == 2 and {0x82B3EB88, 0x82B64C9C} <= game.declared_functions(p4),
      "los declara y regenera (el juego no se cerrará al llegar ahí)")
print("Saltos convertidos en REX_FATAL y entradas que chocan")
gen5 = os.path.join(TMP, "p5", "generated", "default")
project(os.path.join(TMP, "p5"), GOOD + """
DEFINE_REX_FUNC(sub_82B6D304) {
\tif (ctx.cr6.eq) REX_FATAL("Unresolved branch from 0x82B6D314 to 0x82B6D490");
\tREX_FATAL("Unresolved call from 0x82B3EAC0 to 0x82B3EB88");
}
""")
check(sorted(game.fatal_branches_in_code(gen5)) == [(0x82B3EB88, 0x82B3EAC0), (0x82B6D490, 0x82B6D314)],
      "encuentra en el código generado los saltos que cerrarían el juego")
p6 = os.path.join(TMP, "p6")
project(p6)
open(os.path.join(p6, "reforge_functions.toml"), "a").write(
    "0x82112BC0 = { end = 0x82112FA0 }  # cortada\n0x82112C40 = {}  # llamada indirecta\n0x82200000 = {}\n")
check(game.normalize_function_overlaps(p6) == 1, "detecta la entrada que choca con un final declarado")
t6 = open(os.path.join(p6, "reforge_functions.toml")).read()
check("0x82112C40 = { parent = 0x82112BC0 }  # llamada indirecta" in t6 and "0x82200000 = {}" in t6,
      "la declara como fragmento (sigue siendo entrada; rexglue ya no rechaza el manifiesto)")
check(game.normalize_function_overlaps(p6) == 0, "y no la vuelve a tocar")
print(f"\nTodas las pruebas pasaron ({ok}).")
