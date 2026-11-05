"""Actualizaciones de título (TU / default.xexp).   python tests/test_title_update.py"""
import hashlib
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-tu-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from xcontent_fixtures import make_stfs  # noqa: E402
from reforge import title_update as tu  # noqa: E402
from reforge.game_options import app_header, ensure_paths_hook  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


TID = 0x584108B7


def base_xex(sig):
    h = b"XEX2" + struct.pack(">IIIII", 0, 0x2000, 0, 0x100, 1)
    h += struct.pack(">II", 0x00040006, 0x40)
    h = h.ljust(0x40, b"\0")
    h += struct.pack(">IIII", 0x1DF2F0B2, 0x00000103, 0, TID) + bytes([0, 0, 1, 1]) + b"\0" * 4
    h = h.ljust(0x100, b"\0")
    h += struct.pack(">II", 0x200, 0x10000) + sig
    return h.ljust(4096, b"\0")


def xexp(digest, tid=TID, target=0x00000203, source=0x00000103):
    h = b"XEX2" + struct.pack(">IIIII", 0x20, 0x1000, 0, 0x300, 2)
    h += struct.pack(">II", 0x000005FF, 0x40) + struct.pack(">II", 0x00040006, 0x100)
    h = h.ljust(0x40, b"\0")
    h += struct.pack(">III", 0x60, target, source) + digest + bytes(0x10)
    h = h.ljust(0x100, b"\0")
    h += struct.pack(">IIII", 0, target, source, tid) + b"\0" * 8
    return h.ljust(2048, b"\0")


sig = bytes(range(256))
good_digest = hashlib.sha1(sig).digest()


def project(name):
    root = os.path.join(TMP, name)
    os.makedirs(os.path.join(root, "assets"))
    os.makedirs(os.path.join(root, "src"))
    open(os.path.join(root, "assets", "default.xex"), "wb").write(base_xex(sig))
    open(os.path.join(root, "src", "cc_app.h"), "w").write(
        "#include <rex/rex_app.h>\nclass A : public rex::ReXApp {\n public:\n  using rex::ReXApp::ReXApp;\n};\n")
    ensure_paths_hook(root)
    open(os.path.join(root, "CMakeLists.txt"), "w").write("project(cc)\n")
    return root


print("Lectura y comprobación del parche")
info = tu.read_patch_info(xexp(good_digest))
check(info["version"] == "0.0.2.3" and info["source_version"] == "0.0.1.3" and info["title_id"] == "584108B7",
      "lee versión destino/origen y Title ID del default.xexp")
check(tu.base_digest(base_xex(sig)) == good_digest, "calcula la huella del default.xex como el runtime")

tu_dir = os.path.join(TMP, "pkgs", "584108B7", "000B0000")
os.makedirs(tu_dir)
pkg = os.path.join(tu_dir, "TU_10Q41FC_0000014000000.00000000000O2")
make_stfs(pkg, [("default.xexp", xexp(good_digest)), ("media/patch.pak", b"P" * 5000)],
          magic=b"LIVE", content_type=0x000B0000, tid=TID, name="Title Update 2")
root = project("cc")
s = tu.check_update(root, pkg)
check(s["version"] == "0.0.2.3" and s["files"] == 2, "acepta la TU de su juego y versión")
tu.install_update(root, pkg)
check(open(os.path.join(root, "assets", "default.xexp"), "rb").read() == xexp(good_digest),
      "default.xexp queda junto a default.xex (el codegen y el runtime lo aplican)")
check(open(os.path.join(root, "update", "media", "patch.pak"), "rb").read() == b"P" * 5000,
      "el resto de archivos va a «update» (update:)")
check(tu.installed_update(root)["version"] == "0.0.2.3", "recuerda la versión instalada")
hook = open(app_header(root)).read()
check("update_data_root" in hook and 'parent_path() / "update"' in hook, "el .exe monta «update» solo")
check(not any(ln.rstrip().endswith("\\") for ln in hook.splitlines() if "//" in ln),
      "ningún comentario del gancho termina en «\\» (en C++ se comería la línea siguiente)")
check(tu.remove_update(root) and not os.path.exists(os.path.join(root, "assets", "default.xexp"))
      and tu.installed_update(root) is None, "quitarla vuelve al juego base")

print("Rechaza actualizaciones que no corresponden")
other = os.path.join(TMP, "otra.xexp")
open(other, "wb").write(xexp(hashlib.sha1(b"otra version").digest()))
try:
    tu.check_update(root, other)
    check(False, "versión distinta")
except tu.TitleUpdateError as e:
    check("0.0.1.3" in str(e), "otra versión del juego: lo explica (pide la 0.0.1.3)")
wrong = os.path.join(TMP, "otro_juego.xexp")
open(wrong, "wb").write(xexp(good_digest, tid=0x4D5307E6))
try:
    tu.check_update(root, wrong)
    check(False, "otro juego")
except tu.TitleUpdateError as e:
    check("4D5307E6" in str(e), "otro juego (Title ID distinto)")
dlc = os.path.join(TMP, "pkgs", "dlc")
make_stfs(dlc, [("levels/x.pak", b"x" * 100)], content_type=0x00000002, tid=TID)
try:
    tu.check_update(root, dlc)
    check(False, "DLC")
except tu.TitleUpdateError as e:
    check("default.xexp" in str(e), "un DLC no es una actualización")
check(tu.check_update(root, os.path.join(TMP, "pkgs", "584108B7"))["version"] == "0.0.2.3",
      "también acepta la carpeta que contiene el paquete")

print("Ventana ⬆ Actualización")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication([])
from reforge.title_update_ui import UpdateDialog  # noqa: E402
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
warned = []
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
d = UpdateDialog(None, root, "castle_crashers")
check("Sin actualización" in d.state.text() and not d.btn_remove.isEnabled(), "muestra el estado")
d.install(pkg)
check(d.changed and "0.0.2.3" in d.state.text() and d.btn_remove.isEnabled(), "instala y lo muestra")
d.install(other)
check(warned and "0.0.1.3" in warned[-1], "avisa si no corresponde, sin tocar lo instalado")
check(tu.installed_update(root)["version"] == "0.0.2.3", "la instalada sigue intacta")
d.remove()
check(tu.installed_update(root) is None and "Sin actualización" in d.state.text(), "la quita")
print(f"\nTodas las pruebas pasaron ({ok}).")
