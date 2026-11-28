"""Parche utf8 tolerante: nombres de contenido (DLC/TU/partida) con bytes UTF-8 inválidos o truncados
no tumban ni cuelgan el runtime al enumerar contenido.   python tests/test_utf8_tolerant.py

Dos partes:
  1) El parche sdk_patch.apply_utf8_tolerant aplica sobre el fixture (anclas vigentes), es idempotente
     y deja los marcadores del fix. Si una versión nueva del SDK cambia esas líneas, esto avisa.
  2) Comportamiento real: compila y corre tests/utf8_tolerant_selftest.cpp (el iterador tolerante)
     contra secuencias inválidas/truncadas. Si no hay compilador C++, se omite esa parte con aviso.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from reforge import sdk_patch  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


def _tree_with_fixture():
    """Árbol de SDK falso con src/core/utf8.cpp = el fixture reducido."""
    src = tempfile.mkdtemp(prefix="reforge-utf8-")
    dst = os.path.join(src, "src", "core")
    os.makedirs(dst)
    shutil.copyfile(os.path.join(ROOT, "tests", "fixtures_utf8.cpp"), os.path.join(dst, "utf8.cpp"))
    return src, os.path.join(dst, "utf8.cpp")


print("1) El parche aplica sobre las anclas vigentes del SDK")
src, u8 = _tree_with_fixture()
changed = sdk_patch.apply_utf8_tolerant(src)
txt = open(u8, encoding="utf-8").read()
check(changed is True, "apply_utf8_tolerant cambia el archivo")
for marker in ("#include <iterator>", "class utf8_citer", "rf_detail::rf_seq_len",
               "utfcpp::replace_invalid(source.begin()", "ReForge: tolerante. Nunca lanzar por UTF-16"):
    check(marker in txt, f"marcador presente: {marker!r}")
check("using utf8_citer = utfcpp::iterator<" not in txt, "el iterador checked viejo fue reemplazado")

print("2) Es idempotente (volver a aplicar no cambia nada)")
check(sdk_patch.apply_utf8_tolerant(src) is False, "segunda aplicación no cambia nada")

print("3) Está en el pipeline de recompilación y es imprescindible")
nombres = [p[1].__name__ for p in sdk_patch.PATCHES]
check("apply_utf8_tolerant" in nombres, "apply_utf8_tolerant está en PATCHES (lo aplica apply_all al generar el runtime)")
imprescindible = next(p[2] for p in sdk_patch.PATCHES if p[1] is sdk_patch.apply_utf8_tolerant)
check(imprescindible is True, "está marcado imprescindible: un ancla rota detiene la generación en vez de enviar un runtime que casca")

print("4) Si una versión nueva moviera la línea del iterador, el parche NO se aplica a ciegas")
src2, u8_2 = _tree_with_fixture()
roto = open(u8_2, encoding="utf-8").read().replace(
    "using utf8_citer = utfcpp::iterator<std::string_view::const_iterator>;",
    "using utf8_citer = utfcpp::iterator<std::string_view::const_iterator>;  // movido")
# dup del ancla -> el conteo deja de ser 1 -> PatchError (no aplica medio parche)
roto = roto.replace("std::u16string to_utf16(const std::string_view source) {\n  return utfcpp::utf8to16(source);\n}\n",
                    "std::u16string to_utf16(const std::string_view source) {\n  return utfcpp::utf8to16(source);\n}\n"
                    "std::u16string to_utf16(const std::string_view source) {\n  return utfcpp::utf8to16(source);\n}\n")
open(u8_2, "w", encoding="utf-8").write(roto)
try:
    sdk_patch.apply_utf8_tolerant(src2)
    raise AssertionError("debió fallar con el ancla duplicada")
except sdk_patch.PatchError:
    check(True, "ancla ambigua/ausente → PatchError (no aplica a ciegas)")

print("5) Comportamiento: el iterador tolerante decodifica inválido/truncado sin lanzar ni pasar de end")
selftest = os.path.join(ROOT, "tests", "utf8_tolerant_selftest.cpp")
compiler = next((c for c in ("c++", "clang++", "g++", "cl") if shutil.which(c)), None)
if not compiler:
    print("  … sin compilador C++ en el PATH; se omite la parte de comportamiento (el .cpp está en el repo).")
else:
    exe = os.path.join(tempfile.mkdtemp(prefix="reforge-utf8sel-"), "sel.exe" if sys.platform == "win32" else "sel")
    if compiler == "cl":
        cc = subprocess.run(["cl", "/nologo", "/std:c++20", "/EHsc", selftest, f"/Fe:{exe}"],
                            capture_output=True, text=True)
    else:
        cc = subprocess.run([compiler, "-std=c++20", "-O2", selftest, "-o", exe], capture_output=True, text=True)
    check(cc.returncode == 0, f"el selftest compila ({compiler})")
    run = subprocess.run([exe], capture_output=True, text=True)
    for line in run.stdout.splitlines():
        print("    " + line)
    check(run.returncode == 0, "el selftest de comportamiento pasa (inválido/truncado → U+FFFD, sin cuelgue)")

print(f"\nTodas las pruebas pasaron ({ok}).")
