"""Calidad de imagen (escala interna, efectos que trae el runtime, IA de NVIDIA) y protección contra DXVK.
   python tests/test_quality.py"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-quality-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from reforge import optimizer  # noqa: E402
from reforge.core import config_dir  # noqa: E402
from reforge.game_options import GameOptions, runtime_config_path, write_runtime_config  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


print("Escala interna recomendada")
rtx5060 = {"gpu": "NVIDIA GeForce RTX 5060 Ti", "vram_mb": 8151, "cpu_threads": 12}
check(optimizer.recommended_scale(rtx5060) == 2, "RTX 5060 Ti 8 GB → 2× (1440p interno)")
check(optimizer.recommended_scale({"gpu": "NVIDIA GeForce RTX 4080", "vram_mb": 16376}) == 3, "16 GB → 3×")
check(optimizer.recommended_scale({"gpu": "Intel(R) UHD Graphics 620", "vram_mb": 128}) == 1, "integrada → 1×")
check(optimizer.recommended_scale({"gpu": "desconocida", "vram_mb": 0}) == 1, "GPU desconocida → 1×")
tips = optimizer.nvidia_ai_tips(rtx5060)
check("DLDSR" in tips and "Smooth Motion" in tips, "RTX 50: DLDSR y Smooth Motion")
check("Smooth Motion" not in optimizer.nvidia_ai_tips({"gpu": "NVIDIA GeForce RTX 3070"}) and
      "DLDSR" in optimizer.nvidia_ai_tips({"gpu": "NVIDIA GeForce RTX 3070"}), "RTX 30: solo DLDSR")
check(optimizer.nvidia_ai_tips({"gpu": "AMD Radeon RX 7800 XT"}) == "", "otras GPU: sin consejos de NVIDIA")

print("Efectos que trae el runtime")
exe = os.path.join(TMP, "g", "build", "juego.exe")
os.makedirs(os.path.dirname(exe))
open(exe, "wb").write(b"")
open(os.path.join(os.path.dirname(exe), "rexruntime.dll"), "wb").write(b"\0Guest output effect: bilinear\0")
o = GameOptions()
o.present_effect = "fsr"
o.resolution_scale = 2
write_runtime_config(exe, o)
toml = open(runtime_config_path(exe), encoding="utf-8").read()
check('present_effect = "bilinear"' in toml, "FSR no viene en tu runtime: se escribe bilineal")
check("draw_resolution_scale_x = 2" in toml and "draw_resolution_scale_y = 2" in toml, "escala interna 2×")
open(os.path.join(os.path.dirname(exe), "rexruntime.dll"), "wb").write(
    b"\0Guest output effect: bilinear, cas, fsr, fsr2, fsr3\0")
write_runtime_config(exe, o)
check('present_effect = "fsr"' in open(runtime_config_path(exe), encoding="utf-8").read(),
      "con un runtime con FidelityFX se respeta FSR")

print("Licencia de los Arcade (license_mask)")
from reforge.game_options import is_arcade_title, license_value  # noqa: E402
check(is_arcade_title("584108B7") and not is_arcade_title("4D5307E6"), "reconoce los Title ID de Arcade (5841…)")
o2 = GameOptions()
check(license_value(o2, "584108B7") == 1 and license_value(o2, "4D5307E6") is None,
      "automática: juego completo en Arcade, sin tocar los demás")
o2.license = "all"
check(license_value(o2, "4D5307E6") == 0xFFFFFFFF, "«todas las licencias» = 0xFFFFFFFF")
arc = os.path.join(TMP, "arcade")
os.makedirs(os.path.join(arc, "assets"))
os.makedirs(os.path.join(arc, "build"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_xiso import fake_xex  # noqa: E402
x = bytearray(fake_xex())
x[0x4C:0x50] = bytes.fromhex("584108B7")
open(os.path.join(arc, "assets", "default.xex"), "wb").write(bytes(x))
aexe = os.path.join(arc, "build", "castlecrashers.exe")
open(aexe, "wb").write(b"")
open(runtime_config_path(aexe), "w").write("license_mask = 0\n")
write_runtime_config(aexe, GameOptions())
t = open(runtime_config_path(aexe), encoding="utf-8").read()
check(t.count("license_mask") == 1 and "license_mask = 1" in t, "Castle Crashers arranca con la licencia completa")
o3 = GameOptions()
o3.license = "trial"
write_runtime_config(aexe, o3)
check("license_mask = 0" in open(runtime_config_path(aexe), encoding="utf-8").read(), "o como prueba, si lo eliges")

print("Ventana Optimizar")
os.makedirs(config_dir(), exist_ok=True)
json.dump(rtx5060, open(optimizer.hardware_path(), "w"))
from reforge.core import AppConfig  # noqa: E402
from reforge.optimizer_ui import OptimizeDialog  # noqa: E402
proj = os.path.join(TMP, "proj")
os.makedirs(proj)
d = OptimizeDialog(None, AppConfig(), proj, "Ben 10", exe)
rec = [b for b in d.quality.buttons() if "recomendada" in b.text()]
check(len(rec) == 1 and rec[0].property("scale") == 2, "marca 2× como recomendada")
rec[0].setChecked(True)
d.aniso16.setChecked(True)
d.save()
saved = GameOptions.load(proj)
check(saved.resolution_scale == 2 and saved.anisotropic_override == 5, "guarda 2× y anisotrópico 16×")
check("anisotropic_override = 5" in open(runtime_config_path(exe), encoding="utf-8").read(),
      "y lo aplica al juego")

print("Protección contra DXVK")
gdir = os.path.dirname(exe)
open(os.path.join(gdir, "dxgi.dll"), "wb").write(b"MZ...dxvk-3.1.1...DXVK_HUD")
open(os.path.join(gdir, "d3d11.dll"), "wb").write(b"MZ...DXVK...")
open(os.path.join(gdir, "d3d9.dll"), "wb").write(b"MZ...un d3d9 propio de otro programa...")
moved = optimizer.quarantine_dxvk(exe)
check(sorted(moved) == ["d3d11.dll", "dxgi.dll"], "aparta dxgi.dll y d3d11.dll de DXVK")
check(os.path.isfile(os.path.join(gdir, "_dxvk_desactivado", "dxgi.dll")) and
      os.path.isfile(os.path.join(gdir, "_dxvk_desactivado", "LEEME.txt")), "las guarda en _dxvk_desactivado")
check(os.path.isfile(os.path.join(gdir, "d3d9.dll")), "no toca DLL que no son de DXVK")
check(optimizer.quarantine_dxvk(exe) == [], "no hace nada si ya está limpio")
print(f"\nTodas las pruebas pasaron ({ok}).")
