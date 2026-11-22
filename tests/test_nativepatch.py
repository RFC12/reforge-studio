"""Parches nativos a nivel de codegen: generación de C++ mid-asm, guarda de versión y apply/remove reversible."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import nativepatch as np  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


print("Genera el C++ mid-asm correcto (salta la instrucción del tope)")
cpp = np.hook_cpp([{"kind": "skip_to", "address": 0x824d7130, "target": 0x824d7134}])
check("REX_MIDASM_BRANCH" in cpp and "return true" in cpp, "usa un cuerpo branch que salta")
check("REX_MIDASM_AT(ReforgeHook_824d7130, 0x824d7130, before, 0x824d7134);" in cpp, "ataca la dirección correcta")
check("#include <rex/ppc/midasm.h>" in cpp, "incluye la cabecera del SDK")

print("skip sin target salta a la instrucción siguiente (address+4)")
cpp2 = np.hook_cpp([{"kind": "skip", "address": 0x82000100}])
check("0x82000104" in cpp2, "destino = address+4")

print("Valida direcciones (múltiplo de 4, no nulas)")
check(np.validate_ops([{"kind": "skip", "address": 0x824d7131}]), "rechaza dirección no alineada")
check(not np.validate_ops([{"kind": "skip", "address": 0x824d7130}]), "acepta dirección alineada")

print("Guarda de versión: un parche BASE no se aplica si hay title update")
tmp = tempfile.mkdtemp()
with open(os.path.join(tmp, "reforge_functions.toml"), "w", encoding="utf-8") as f:
    f.write("# ReForge Studio: funciones declaradas automáticamente (tu-0.0.1.5).\n[functions]\n")
# sin XEX real, project_version devuelve "" pero has_title_update lee el marcador tu-
ok, motivo = np.version_ok(tmp, "base")
check(ok is False and "title update" in motivo, "rechaza parche base en proyecto con TU")

tmp2 = tempfile.mkdtemp()
with open(os.path.join(tmp2, "reforge_functions.toml"), "w", encoding="utf-8") as f:
    f.write("# base, sin TU\n[functions]\n")
ok2, _ = np.version_ok(tmp2, "base")
check(ok2 is True, "acepta parche base en proyecto base")

print("apply escribe el hook y lo engancha; remove lo revierte")
proj = tempfile.mkdtemp()
os.makedirs(os.path.join(proj, "src"), exist_ok=True)
with open(os.path.join(proj, "juego_manifest.toml"), "w", encoding="utf-8") as f:
    f.write('[project]\nname = "juego"\n\n[entrypoint]\nincludes = ["reforge_functions.toml"]\n')
ok3, msg3 = np.apply(proj, [{"kind": "skip_to", "address": 0x824d7130, "target": 0x824d7134}], applies_to_version="")
check(ok3 and np.is_applied(proj), "escribe src/reforge_hooks.cpp")
man = open(os.path.join(proj, "juego_manifest.toml"), encoding="utf-8").read()
check(np.HOOK_INCLUDE in man, "añade el include al manifest")
check(os.path.isfile(os.path.join(proj, np.HOOK_INCLUDE)), "crea reforge_hooks.toml con hook_sources")
inc = open(os.path.join(proj, np.HOOK_INCLUDE), encoding="utf-8").read()
check('hook_sources = ["src"]' in inc, "el include declara hook_sources")
np.remove(proj)
check(not np.is_applied(proj), "remove borra el hook")
man2 = open(os.path.join(proj, "juego_manifest.toml"), encoding="utf-8").read()
check(np.HOOK_INCLUDE not in man2, "remove quita el include del manifest")

print("apply respeta la guarda de versión (no escribe si no toca)")
projtu = tempfile.mkdtemp()
with open(os.path.join(projtu, "reforge_functions.toml"), "w", encoding="utf-8") as f:
    f.write("# tu-0.0.1.5\n[functions]\n")
with open(os.path.join(projtu, "j_manifest.toml"), "w", encoding="utf-8") as f:
    f.write('[entrypoint]\nincludes = []\n')
ok4, msg4 = np.apply(projtu, [{"kind": "skip", "address": 0x824d7130}], applies_to_version="base")
check(ok4 is False and not np.is_applied(projtu), "no aplica un parche base a un proyecto con TU")

print("gamedb expone el desbloqueo nativo de Asura con guarda base")
from reforge import gamedb  # noqa: E402
nu = gamedb.native_unlock("43430817")
check(nu is not None and nu.get("applies_to_version") == "base", "Asura: desbloqueo nativo marcado como base")
check(nu and nu["ops"][0]["address"] == 0x824d7130, "con la dirección portada de boma")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
