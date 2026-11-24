"""El .exe de un proyecto del SDK 0.11 tiene que arrancar sin el .bat (sin --game_data_root).

Sin ese ajuste, al abrir el ejecutable sale «title failed: --game_data_root was not provided».
python tests/test_paths011.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from reforge import game_options as go  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


def proyecto011():
    root = tempfile.mkdtemp(prefix="reforge-paths011-")
    os.makedirs(os.path.join(root, "src"))
    os.makedirs(os.path.join(root, "assets"))
    open(os.path.join(root, "CMakeLists.txt"), "w").write("project(x LANGUAGES CXX)\n")
    main = os.path.join(root, "src", "main.cpp")
    open(main, "w", encoding="utf-8").write(
        "#include <rex/app/title_app.h>\n\n"
        "class DemoApp : public rex::app::TitleApp {\n"
        " public:\n"
        "  DemoApp() : TitleApp(\"demo\", kPPCImageConfig) {}\n"
        "};\nREX_TITLE_APP(DemoApp)\n")
    return root, main


print("Gancho de rutas del SDK 0.11")
root, main = proyecto011()
check(go.ensure_paths_hook(root) is True, "añade OnConfigure a src/main.cpp")
txt = open(main, encoding="utf-8").read()
check("OnConfigure(rex::SettingsRegistry& settings) override" in txt, "usa el gancho OnConfigure del SDK")
check("title.game_root" in txt and "title.update_root" in txt,
      "da por defecto la carpeta assets y la de actualizaciones")
check("GetModuleFileNameW" in txt, "busca assets junto al .exe (doble clic)")
check("SettingLayer::kTitle" in txt, "lo pone en la capa del título: la línea de comandos manda si viene")
check("#include <filesystem>" in txt and "#include <windows.h>" in txt, "con sus includes")
check(go.ensure_paths_hook(root) is False, "es idempotente")
check(txt.count("OnConfigure") == 2, "una sola vez (declaración y llamada a la base)")

print("Respeta un OnConfigure propio")
root2, main2 = proyecto011()
open(main2, "w", encoding="utf-8").write(
    "#include <rex/app/title_app.h>\nclass D : public rex::app::TitleApp {\n public:\n"
    "  rex::Result<void> OnConfigure(rex::SettingsRegistry& s) override { return {}; }\n};\n")
check(go.ensure_paths_hook(root2) is False, "no toca el que ya escribió el usuario")

print("No se mete en los proyectos del SDK 0.10")
root3 = tempfile.mkdtemp(prefix="reforge-paths10-")
os.makedirs(os.path.join(root3, "src"))
open(os.path.join(root3, "src", "demo_app.h"), "w", encoding="utf-8").write(
    "#include <rex/rex_app.h>\nclass DemoApp : public rex::ReXApp {\n  using rex::ReXApp::ReXApp;\n};\n")
check(go.ensure_paths_hook(root3) is True, "0.10 sigue usando OnConfigurePaths")
check("OnConfigurePaths" in open(os.path.join(root3, "src", "demo_app.h"), encoding="utf-8").read(),
      "y no el de 0.11")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
