"""Animación y logo de las notificaciones de logros.   python tests/test_toast_anim.py"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-toast-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from reforge import toast_anim  # noqa: E402
from reforge.ext_cpp import EXT_SOURCE  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


print("Línea de tiempo")
T = 5.0
f0, f_open, f_hold, f_end = (toast_anim.compute(t, T, True) for t in (0.0, 0.6, 2.4, T - 0.01))
check(f0.alpha == 0 and abs(f0.circle) < 1e-6, "empieza invisible")
check(max(toast_anim.compute(t / 100, T, True).circle for t in range(0, 40)) > 1.05,
      "el círculo aparece con rebote")
check(0.5 < f_open.open < 1 and f_hold.open == 1 and f_hold.title_a == 1, "la cápsula se despliega y muestra el texto")
check(toast_anim.compute(0.9, T, True).count < 1 and f_hold.count == 1, "los G cuentan hasta el valor")
faces = {toast_anim.compute(t / 30, T, True).face for t in range(int(1.5 * 30), int(3.9 * 30))}
check(faces == {0, 1}, "con logo, la insignia alterna logo ↔ icono")
check(min(toast_anim.compute(t / 100, T, True).squash for t in range(140, 400)) < 0.1, "el cambio es un giro")
check({toast_anim.compute(t / 30, T, False).face for t in range(0, 150)} == {1}, "sin logo, solo icono/trofeo")
for total in (3.0, 4.6, 5.0, 7.3, 15.0):
    ends = [toast_anim.compute(total - d, total, True) for d in (0.5, 0.3, 0.1)]
    check(all(e.face == 0 and e.squash > 0.99 for e in ends), f"se despide con el logo ({total:g} s)")
check(f_end.alpha < 0.2 and f_end.circle < 0.2, "termina desapareciendo")
check(toast_anim.compute(3.0, 3.0, True).alpha == 0, "duración mínima respetada")

print("Igual en el juego (C++) que en la vista previa (Python)")
cxx = shutil.which("g++") or shutil.which("clang++")
if not cxx:
    print("  · sin compilador de C++: comparación omitida")
else:
    a = EXT_SOURCE.index("struct ToastFrame")
    b = EXT_SOURCE.index("static ImU32 Rgba")
    src = os.path.join(TMP, "anim.cpp")
    with open(src, "w") as fh:
        fh.write("#include <algorithm>\n#include <cmath>\n#include <cstdio>\n" + EXT_SOURCE[a:b] + r'''
int main() {
  const float totals[] = {3.0f, 5.0f, 7.3f};
  for (float total : totals)
    for (int badge = 0; badge < 2; ++badge)
      for (int i = 0; i <= 300; ++i) {
        const float age = total * i / 300.0f;
        ToastFrame f = ComputeToastFrame(age, total, badge != 0);
        std::printf("%.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %d\n", f.alpha, f.circle,
                    f.open, f.title_a, f.label_a, f.title_in, f.label_in, f.count, f.shine, f.wave, f.wave2,
                    f.sparks, f.ring, f.squash, f.face);
      }
}
''')
    exe = os.path.join(TMP, "anim.exe" if os.name == "nt" else "anim")
    try:
        subprocess.run([cxx, "-std=c++17", "-O1", src, "-o", exe], check=True, capture_output=True)
        rows = subprocess.run([exe], capture_output=True, text=True, check=True).stdout.split("\n")
    except (OSError, subprocess.CalledProcessError):
        rows = None
        print("  · el compilador de C++ no está listo en este entorno: comparación omitida")
if cxx and rows:
    worst, k, face_bad = 0.0, 0, 0
    for total in (3.0, 5.0, 7.3):
        for badge in (False, True):
            for i in range(301):
                age = float(struct.unpack("f", struct.pack("f", total * i / 300.0))[0])
                py = toast_anim.compute(age, total, badge)
                vals = rows[k].split()
                k += 1
                for name, v in zip(toast_anim.FIELDS, vals):
                    if name == "face":
                        face_bad += int(v) != py.face
                    else:
                        worst = max(worst, abs(float(v) - getattr(py, name)))
    check(worst < 2e-3 and face_bad == 0, f"misma animación fotograma a fotograma (dif. máx. {worst:.1e})")

print("Logo del perfil")
from reforge.badge import badge_path, export_for_game, import_badge  # noqa: E402
from reforge.profile import Profile, ext_ini_path, write_ext_ini  # noqa: E402

# un logo redondo sobre un fondo de cuadros blancos/grises (el típico PNG «transparente» pintado)
img = QImage(600, 400, QImage.Format.Format_RGBA8888)
p = QPainter(img)
for yy in range(0, 400, 20):
    for xx in range(0, 600, 20):
        p.fillRect(xx, yy, 20, 20, QColor(255, 255, 255) if (xx + yy) // 20 % 2 == 0 else QColor(230, 230, 230))
p.setRenderHint(QPainter.RenderHint.Antialiasing)
p.setPen(Qt.PenStyle.NoPen)
p.setBrush(QColor(40, 160, 60))
p.drawEllipse(250, 80, 240, 240)
p.end()
src = os.path.join(TMP, "logo.png")
img.save(src)
out = QImage(import_badge(src))
check(out.width() == out.height() == 256, "se guarda cuadrado de 256 px")
check(out.pixelColor(2, 2).alpha() == 0 and out.pixelColor(128, 128).green() > 140,
      "quita el fondo de cuadros y centra el logo")
check(out.pixelColor(128, 6).alpha() > 0 and out.pixelColor(6, 128).alpha() > 0, "el logo llena el círculo")

exe = os.path.join(TMP, "g", "build", "juego.exe")
os.makedirs(os.path.dirname(exe))
open(exe, "w").write("")
prof = Profile()
prof.toast_badge = "custom"
write_ext_ini(exe, None, prof)
raw = os.path.join(os.path.dirname(exe), "reforge_badge.rgba")
ini = open(ext_ini_path(exe), encoding="utf-8").read()
data = open(raw, "rb").read()
check("badge = reforge_badge.rgba" in ini and data[:4] == b"RFBG" and struct.unpack("<II", data[4:12]) == (256, 256)
      and len(data) == 12 + 256 * 256 * 4, "se copia junto al juego en formato que lee la extensión")
prof.toast_badge = "none"
write_ext_ini(exe, None, prof)
check("badge = \n" in open(ext_ini_path(exe), encoding="utf-8").read() and not os.path.exists(raw),
      "«Sin logo» lo quita")
check(os.path.isfile(badge_path()), "el logo queda guardado en el perfil")
check("LoadBadge" in EXT_SOURCE and 'std::memcmp(magic, "RFBG", 4)' in EXT_SOURCE and "wh[0] > 1024" in EXT_SOURCE,
      "la extensión valida el archivo antes de crear la textura")
check(export_for_game(prof, os.path.dirname(exe)) == "", "sin logo no exporta nada")

print("Vista previa")
from reforge.profile_page import ProfilePage  # noqa: E402


class _Win:
    def cfg_accent_hex(self):
        return "19D3A2"


page = ProfilePage(_Win())
page.profile.toast_badge = "custom"
page.profile.save()
page.refresh()
check(not page.preview.badge.isNull() and any(b.isChecked() and b.property("badge") == "custom"
                                              for b in page.badge_group.buttons()), "muestra tu logo en la vista previa")
page.preview.resize(800, 460)
for t in (0.2, 0.9, 2.0, 3.3, 4.7):
    page.preview.t = t
    page.preview.grab()
check(True, "dibuja todas las fases sin errores")
print(f"\nTodas las pruebas pasaron ({ok}).")
