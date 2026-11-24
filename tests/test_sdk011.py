"""Ajustes del .toml según el SDK: 0.10 usa nombres sueltos y 0.11 exige el grupo (kernel.user_language).

Sin esto el idioma (y el resto de opciones) se descartaba en los proyectos 0.11 con
«unknown setting 'user_language' from Config» y el juego seguía en inglés.

python tests/test_sdk011.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from reforge import game_options as go, profile  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


def proyecto(main_cpp=""):
    root = tempfile.mkdtemp(prefix="reforge-sdk-")
    os.makedirs(os.path.join(root, "src"))
    os.makedirs(os.path.join(root, "build"))
    os.makedirs(os.path.join(root, "assets"))
    open(os.path.join(root, "assets", "default.xex"), "wb").close()
    open(os.path.join(root, "src", "main.cpp"), "w", encoding="utf-8").write(main_cpp)
    exe = os.path.join(root, "build", "juego.exe")
    open(exe, "wb").close()
    return root, exe


MAIN11 = '#include <rex/app/title_app.h>\nclass X : public rex::app::TitleApp {};\nREX_TITLE_APP(X)\n'

print("Detección del SDK")
root11, exe11 = proyecto(MAIN11)
root10, exe10 = proyecto("int main() { return 0; }\n")
check(go.sdk_is_011(root11) is True, "un proyecto con REX_TITLE_APP es del SDK 0.11")
check(go.sdk_is_011(root10) is False, "uno normal sigue siendo 0.10")

print("Idioma en el .toml")
o = go.GameOptions()
o.language, o.country = 5, 71        # Español (México / Latinoamérica)
go.write_runtime_config(exe11, o)
txt = open(go.runtime_config_path(exe11), encoding="utf-8").read()
check("kernel.user_language = 5" in txt, "0.11: el idioma va como kernel.user_language (lo que lee el runtime)")
check("kernel.user_country = 71" in txt, "0.11: y el país como kernel.user_country")
check("user_language = 5" not in txt.replace("kernel.user_language = 5", ""),
      "0.11: no queda el nombre suelto de 0.10 (el runtime lo tiraba)")
check("draw_resolution_scale_x" not in txt and "gpu_plugin" not in txt,
      "0.11: no se escriben ajustes que ese SDK ya no tiene")

print("0.10 se queda como estaba")
go.write_runtime_config(exe10, go.GameOptions(language=5, country=71))
txt10 = open(go.runtime_config_path(exe10), encoding="utf-8").read()
check("user_language = 5" in txt10 and "kernel.user_language" not in txt10,
      "0.10: nombres sueltos de siempre")
check("gpu_plugin" in txt10, "0.10: sigue llevando gpu_plugin")

print("reforge_ext.ini (lo que devuelve el juego)")
ini = open(profile.ext_ini_path(exe11), encoding="utf-8").read()
check("language = 5" in ini, "el perfil guarda el idioma para el propio juego")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
