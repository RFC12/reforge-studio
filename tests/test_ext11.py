"""Menú Guía para proyectos del SDK 0.11 (rex::app::TitleApp).

python tests/test_ext11.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from reforge import ext11  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


MAIN = """// demo - ReXGlue Recompiled Project

#include <rex/app/title_app.h>

#include "generated/default/demo_init.h"

class DemoApp : public rex::app::TitleApp {
 public:
  DemoApp() : TitleApp("demo", kPPCImageConfig) {}
};

REX_TITLE_APP(DemoApp)
"""

CMAKE = """cmake_minimum_required(VERSION 3.25)
find_package(rexglue 0.11.0 REQUIRED CONFIG)
rexglue_project(demo OUTPUT_DIR generated/default)

set(DEMO_HOST_SOURCES src/demo_hooks.cpp)

add_library(demo_common OBJECT ${DEMO_HOST_SOURCES})
if (WIN32)
  add_executable(demo WIN32 src/main.cpp)
else ()
  add_executable(demo src/main.cpp)
endif ()
"""


def proyecto():
    root = tempfile.mkdtemp(prefix="reforge-11-")
    os.makedirs(os.path.join(root, "src"))
    open(os.path.join(root, "src", "main.cpp"), "w", encoding="utf-8").write(MAIN)
    open(os.path.join(root, "CMakeLists.txt"), "w", encoding="utf-8").write(CMAKE)
    return root


print("Detección y generación")
root = proyecto()
check(ext11.applies(root), "un proyecto 0.11 con REX_TITLE_APP se reconoce")
cambios = ext11.ensure(root)
check("src/reforge_menu.cpp" in cambios, "se crea el menú Guía (src/reforge_menu.cpp)")
check("src/main.cpp" in cambios and "CMakeLists.txt" in cambios, "se engancha en la app y en CMake")
main = open(os.path.join(root, "src", "main.cpp"), encoding="utf-8").read()
check("InstallGuideMenu" in main and "OnTitleLaunch" in main, "la app monta el menú al lanzar el título")
check(main.count("InstallGuideMenu") == 2, "declaración y llamada, sin duplicar")
cm = open(os.path.join(root, "CMakeLists.txt"), encoding="utf-8").read()
check("DEMO_HOST_SOURCES src/demo_hooks.cpp src/reforge_menu.cpp" in cm,
      "va en las fuentes del host (hereda includes de rexglue)")
fuente = open(os.path.join(root, "src", "reforge_menu.cpp"), encoding="utf-8").read()
for pieza, que in (("rex::ui::DialogBase", "usa la ventana ImGui del SDK 0.11"),
                   ("GetState(0)", "lee el mando (botón Guía)"),
                   ("guide_button.Set(true)", "pide el botón Guía, que 0.11 filtra por defecto"),
                   ("ImGuiKey_GamepadDpadUp", "navega con la cruceta por ImGui (el mando del juego va neutral)"),
                   ("ImGuiKey_GamepadFaceDown", "usa A/B del mando"),
                   ("OutCubic(a)", "el panel entra deslizante, como el menú de 0.10"),
                   ("kAccentNames", "mismo color de acento y filas que el menú de 0.10"),
                   ("SetAudioPaused", "silencia al momento"),
                   ("GetAchievementManager", "lista los logros"),
                   ("reforge_menu.ini", "guarda lo elegido para el próximo arranque")):
    check(pieza in fuente, que)

print("Es idempotente y se puede quitar")
check(ext11.ensure(root) == [], "una segunda pasada no toca nada")
quitados = ext11.remove(root)
check(not os.path.isfile(os.path.join(root, "src", "reforge_menu.cpp")), "quitar borra el archivo")
check("InstallGuideMenu" not in open(os.path.join(root, "src", "main.cpp"), encoding="utf-8").read(),
      "y deja main.cpp como estaba")
check("reforge_menu.cpp" not in open(os.path.join(root, "CMakeLists.txt"), encoding="utf-8").read(),
      "y sin referencia en CMake")

print("No se mete en proyectos de 0.10")
root10 = tempfile.mkdtemp(prefix="reforge-10-")
os.makedirs(os.path.join(root10, "src"))
open(os.path.join(root10, "src", "main.cpp"), "w", encoding="utf-8").write("int main() { return 0; }\n")
open(os.path.join(root10, "CMakeLists.txt"), "w", encoding="utf-8").write("project(x)\n")
check(ext11.applies(root10) is False and ext11.ensure(root10) == [], "no toca un proyecto del SDK 0.10")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
