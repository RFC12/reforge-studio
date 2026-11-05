"""Perfil, Xbox Live simulado, notificación de logros y extensión C++.   python tests/test_profile.py"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-profile-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)

from reforge.ext_cpp import APP_BEGIN, EXT_SOURCE, ensure_reforge_ext, remove_reforge_ext  # noqa: E402
from reforge.game_options import GameOptions, write_runtime_config  # noqa: E402
from reforge.profile import Profile, clean_gamertag, ext_ini_path, valid_gamertag, write_ext_ini  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


print("Gamertag y perfil")
check(clean_gamertag("Rogér_Flórez 2020!!") == "Roger Florez 20", "quita tildes y símbolos y recorta a 15")
check(valid_gamertag("Roger 2020") and not valid_gamertag("x" * 16) and not valid_gamertag(""), "valida como Xbox 360")
p = Profile.load()
check(p.gamertag == "Player" and not p.live and p.toast_position == "bottom_right", "valores por defecto")
p.gamertag, p.live, p.toast_position, p.toast_seconds = "RogerReForge", True, "top_left", 7.5
p.save()
q = Profile.load()
check((q.gamertag, q.live, q.toast_position, q.toast_seconds) == ("RogerReForge", True, "top_left", 7.5),
      "se guarda y se recupera")

print("Configuración por juego (reforge_ext.ini)")
exe = os.path.join(TMP, "game", "build", "angrybirdstrilogy.exe")
os.makedirs(os.path.dirname(exe))
open(exe, "w").write("")
o = GameOptions()
o.language = 5
write_runtime_config(exe, o)
ini = open(ext_ini_path(exe), encoding="utf-8").read()
check("gamertag = RogerReForge" in ini and "live = 1" in ini and "language = 5" in ini
      and "toast_position = top_left" in ini and "toast_seconds = 7.5" in ini,
      "al preparar el juego se escriben perfil, Live, idioma y posición")
q.live = False
write_ext_ini(exe, None, q)
check("live = 0" in open(ext_ini_path(exe), encoding="utf-8").read(), "desactivar Live se refleja")

print("Extensión C++ en el proyecto")
proj = os.path.join(TMP, "proj")
os.makedirs(os.path.join(proj, "src"))
app_h = ("#pragma once\n\n#include <rex/rex_app.h>\n\nclass A : public rex::ReXApp {\n public:\n"
         "  using rex::ReXApp::ReXApp;\n  static int x();\n};\n")
cml = "set(A_SOURCES\n    src/main.cpp\n)\n"
open(os.path.join(proj, "src", "a_app.h"), "w").write(app_h)
open(os.path.join(proj, "CMakeLists.txt"), "w").write(cml)
ch = ensure_reforge_ext(proj)
check(set(ch) == {"src/reforge_ext.h", "src/reforge_ext.cpp", "CMakeLists.txt", os.path.join("src", "a_app.h")},
      "añade la extensión, la fuente a CMake y el bloque a la app")
check(ensure_reforge_ext(proj) == [], "es idempotente")
t = open(os.path.join(proj, "src", "a_app.h")).read()
check(t.count(APP_BEGIN) == 1 and '#include "reforge_ext.h"' in t, "un solo bloque y una sola inclusión")
check("src/reforge_ext.cpp" in open(os.path.join(proj, "CMakeLists.txt")).read(), "CMake compila la extensión")
for sym in ("__imp__XGetLanguage", "__imp__XamUserGetSigninState", "__imp__XamUserGetSigninInfo",
            "__imp__XamUserGetName", "__imp__XamUserCheckPrivilege", "__imp__NetDll_XNetGetEthernetLinkStatus"):
    assert f"REX_HOOK({sym}," in EXT_SOURCE, sym
check(True, "sustituye idioma, sesión, nombre, privilegios y red")
check("0xB13EBABEBABEBABE" in EXT_SOURCE, "conserva el XUID de rexglue (partidas guardadas válidas)")
remove_reforge_ext(proj)
check(open(os.path.join(proj, "src", "a_app.h")).read() == app_h and open(os.path.join(proj, "CMakeLists.txt")).read() == cml
      and not os.path.exists(os.path.join(proj, "src", "reforge_ext.cpp")), "desactivarla deja el proyecto como estaba")
own = os.path.join(TMP, "own")
os.makedirs(os.path.join(own, "src"))
open(os.path.join(own, "src", "b_app.h"), "w").write(
    app_h.replace("  static int x();", "  std::unique_ptr<rex::ui::AchievementNotificationDialog> "
                                       "CreateAchievementNotificationDialog() override { return nullptr; }"))
open(os.path.join(own, "CMakeLists.txt"), "w").write(cml)
ensure_reforge_ext(own)
check(APP_BEGIN not in open(os.path.join(own, "src", "b_app.h")).read(), "respeta una notificación propia del usuario")

print("Compatibilidad con Windows")
import re  # noqa: E402
# Nombres que los encabezados de Windows definen como macros (rpcndr.h, windef.h, winuser.h…).
WIN_MACROS = {"small", "hyper", "near", "far", "NEAR", "FAR", "interface", "IN", "OUT", "OPTIONAL", "CONST",
              "TRUE", "FALSE", "ERROR", "DELETE", "VOID", "ABSOLUTE", "RELATIVE", "TRANSPARENT", "OPAQUE",
              "IGNORE", "INFINITE", "PASCAL", "CALLBACK", "WINAPI", "CreateWindow", "DrawText", "LoadImage",
              "GetObject", "SendMessage", "PostMessage", "GetMessage", "min", "max", "rad1", "rad2", "cmb1",
              "chx1", "pascal", "cdecl", "ExitWindows", "Yield"}
code = re.sub(r'//[^\n]*|"(?:\\.|[^"\\])*"', '', EXT_SOURCE)
used = set(re.findall(r'\b[A-Za-z_]\w*\b', code)) - {'std'}
bad = sorted(used & WIN_MACROS - {"min", "max", "WINAPI"})   # NOMINMAX definido; WINAPI usado a propósito (PlaySoundW)
check(not bad, "la extensión no usa nombres que Windows define como macros " + ",".join(bad))
old = "const float big = 22.0f * s, small = 15.0f * s;"   # línea de la 1.5.0 que falló en Windows
check("small" in set(re.findall(r'\b[A-Za-z_]\w*\b', old)) & WIN_MACROS, "detectaría el fallo real de la 1.5.0 («small»)")

print("Si la extensión no compila, el juego se compila sin ella")
from reforge import game  # noqa: E402
from reforge.core import AppConfig  # noqa: E402
fb = os.path.join(TMP, "fallback")
os.makedirs(os.path.join(fb, "src"))
open(os.path.join(fb, "src", "c_app.h"), "w").write(app_h)
open(os.path.join(fb, "CMakeLists.txt"), "w").write(cml)
ensure_reforge_ext(fb)
fake = os.path.join(TMP, "fakecmake.py")
open(fake, "w").write(
    "import os, sys\n"
    "if '--build' in sys.argv and os.path.exists(os.path.join(os.getcwd(), 'src', 'reforge_ext.cpp')):\n"
    "    print('FAILED: [code=1] CMakeFiles/c.dir/src/reforge_ext.cpp.obj')\n"
    "    print(\"src/reforge_ext.cpp:228:34: error: expected unqualified-id\")\n"
    "    sys.exit(1)\n"
    "print('ok', ' '.join(sys.argv[1:]))\n")
cfg = AppConfig()
cfg.cmake = sys.executable
import reforge.core as core_mod  # noqa: E402
orig_b, orig_c = core_mod.cmake_build_cmd, core_mod.cmake_configure_cmd
core_mod.cmake_build_cmd = lambda c, b: [sys.executable, fake, "--build", b]
core_mod.cmake_configure_cmd = lambda c, r, b: [sys.executable, fake, "-S", r, "-B", b]


class Ctx:
    msgs = []

    def log(self, t, level="info"):
        self.msgs.append(t)

    def progress(self, *a):
        pass

    def cancelled(self):
        return False


cx = Ctx()
game.build_with_ext_fallback(cfg, fb, os.path.join(fb, "build"), dict(os.environ), cx)
check(not os.path.exists(os.path.join(fb, "src", "reforge_ext.cpp"))
      and open(os.path.join(fb, "src", "c_app.h")).read() == app_h, "quita la extensión y deja la app intacta")
check(GameOptions.load(fb).reforge_ext is False and any("sin la extensión" in m for m in cx.msgs),
      "compila sin ella, la deja desactivada y lo explica")
try:
    open(os.path.join(fb, "src", "reforge_ext.cpp"), "w").write("x")
    core_mod.cmake_build_cmd = lambda c, b: [sys.executable, "-c", "print('error: otra cosa'); raise SystemExit(2)"]
    game.build_with_ext_fallback(cfg, fb, os.path.join(fb, "build"), dict(os.environ), Ctx())
    raise AssertionError("debió fallar")
except RuntimeError:
    check(True, "otros errores de compilación se siguen informando")
core_mod.cmake_build_cmd, core_mod.cmake_configure_cmd = orig_b, orig_c

print("Página Perfil")
from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication.instance() or QApplication([])
from reforge.profile_page import ProfileChip, ProfilePage  # noqa: E402


class FakeWin:
    def cfg_accent_hex(self):
        return "FF9F1C"


pg = ProfilePage(FakeWin())
pg.tag.setText("Roger 2020")
pg._tag_edited("Roger 2020")
pg._pick_generated(3)
b = [x for x in pg.pos_group.buttons() if x.property("toastpos") == "bottom_center"][0]
b.setChecked(True)
pg._pos_changed()
pg.live.setChecked(True)
r = Profile.load()
check((r.gamertag, r.avatar, r.toast_position, r.live, r.accent) == ("Roger 2020", "gen:3", "bottom_center", True, "FF9F1C"),
      "la página guarda Gamertag, imagen, posición, Live y color")
chip = ProfileChip()
check(chip.name.text() == "Roger 2020" and "Live" in chip.state.text(), "la barra lateral muestra el perfil")

print(f"\nTodas las pruebas pasaron ({ok}).")
