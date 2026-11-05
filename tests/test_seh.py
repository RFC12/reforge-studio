"""Encabezado SEH para juegos con manejadores de excepciones.   python tests/test_seh.py"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-seh-")
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
pch_dir = os.path.join(root, "build", "CMakeFiles", "codaw_recomp.dir")
os.makedirs(pch_dir)
cml = os.path.join(root, "CMakeLists.txt")
base = "cmake_minimum_required(VERSION 3.25)\nproject(codaw LANGUAGES CXX)\ninclude(generated/rexglue.cmake)\n" \
       "rexglue_setup_target(codaw)\n"
open(cml, "w").write(base)
open(os.path.join(pch_dir, "cmake_pch.hxx.pch"), "w").write("x")
check(game.ensure_seh_header(root), "añade el bloque SEH")
txt = open(cml).read()
check("target_precompile_headers(codaw_recomp PRIVATE <rex/platform/exceptions.h>)" in txt and "<excpt.h>" in txt,
      "exceptions.h y excpt.h en el precompilado del código recompilado")
check(txt.index("<excpt.h>") < txt.index("<rex/platform/exceptions.h>"), "excpt.h primero (GetExceptionCode)")
check(not os.path.exists(os.path.join(pch_dir, "cmake_pch.hxx.pch")), "precompilado viejo borrado")
check(not game.ensure_seh_header(root) and open(cml).read() == txt, "segunda vez no cambia nada")
check(txt.isascii(), "CMakeLists sigue en ASCII")
old = base + "\n" + game.SEH_MARK + " (x)\nif(TARGET codaw_recomp)\n    target_precompile_headers(codaw_recomp PRIVATE " \
                                    "<rex/platform/exceptions.h>)\nendif()\n"
open(cml, "w").write(old)
check(game.ensure_seh_header(root) and open(cml).read().count(game.SEH_MARK) == 1, "rehace el bloque de 1.27.0")
check(game.SEH_UNDECLARED_RE.search("x.cpp:1:2: error: use of undeclared identifier 'SEH_TRY'") is not None and
      game.SEH_UNDECLARED_RE.search("error: use of undeclared identifier 'GetExceptionCode'; did you mean") is not None,
      "reconoce el error en el log de compilación")
print(f"\nTodas las pruebas pasaron ({ok}).")
