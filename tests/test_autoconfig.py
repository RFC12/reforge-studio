"""Autoconfiguración al abrir el juego.   python tests/test_autoconfig.py"""
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-auto-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)
from reforge import autoconfig, game_options as go, optimizer, pc_enhance  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


pc_enhance.monitor_hz = lambda: 165
detected = []
optimizer._gpu_from_registry = lambda: [("NVIDIA GeForce RTX 5060 Ti", 8192)]
real_detect = optimizer.detect_hardware


def fake_detect(game_log=""):
    detected.append(1)
    hw = {"gpu": "NVIDIA GeForce RTX 5060 Ti", "vram_mb": 8192, "cpu_threads": os.cpu_count() or 4, "avx2": True}
    os.makedirs(os.path.dirname(optimizer.hardware_path()), exist_ok=True)
    json.dump(hw, open(optimizer.hardware_path(), "w"))
    return hw


optimizer.detect_hardware = fake_detect
root = os.path.join(TMP, "juego")
os.makedirs(os.path.join(root, "build"))
exe = os.path.join(root, "build", "juego.exe")
open(exe, "w").write("")
go.GameOptions(fps_unlocked=True, fps_cap=60.0).save(root)

print("Al abrir el juego")
line = autoconfig.apply(root, exe)
check(detected, "detecta el hardware si no hay datos")
check("RTX 5060 Ti 8 GB" in line and "60 FPS estables" in line and "código Segura" in line, "resumen: " + line)
toml = open(os.path.join(root, "build", "juego.toml"), encoding="utf-8").read()
check("video_mode_refresh_rate = 60" in toml and "d3d12_pipeline_creation_threads" in toml,
      "escribe la configuración del juego antes de abrirlo")
n = len(detected)
autoconfig.apply(root, exe)
check(len(detected) == n, "no repite la detección cada vez (caché de una semana)")
optimizer._gpu_from_registry = lambda: [("AMD Radeon RX 9070", 16384)]
autoconfig.apply(root, exe)
check(len(detected) == n + 1, "si cambiaste de tarjeta gráfica, la vuelve a detectar")
old = time.time() - autoconfig.HW_MAX_AGE - 10
optimizer._gpu_from_registry = lambda: [("NVIDIA GeForce RTX 5060 Ti", 8192)]
os.utime(optimizer.hardware_path(), (old, old))
autoconfig.apply(root, exe)
check(len(detected) == n + 2, "y cada semana")

print("Escalado universal (resolución interna)")
check(go.GameOptions.load(root).resolution_scale == 2, "RTX de 8 GB → 2× (1440p interno) automáticamente")
o = go.GameOptions.load(root)
o.scale_ceiling = 1
o.save(root)
autoconfig.apply(root, exe)
check(go.GameOptions.load(root).resolution_scale == 1, "si el juego no llegó a sus FPS a 2×, se queda en 1×")
o = go.GameOptions.load(root)
o.resolution_auto, o.resolution_scale, o.scale_ceiling = False, 3, 0
o.save(root)
autoconfig.apply(root, exe)
check(go.GameOptions.load(root).resolution_scale == 3, "elegida a mano: se respeta")

print("Sin preguntas al jugar")
json.dump({"ask_engine_on_play": True}, open(os.path.join(root, go.OPTIONS_FILE), "w"))
check(not go.GameOptions.load(root).ask_engine_on_play, "el menú de motor de versiones anteriores ya no sale")
json.dump({"ask_engine_on_play": True, "ask_engine_chosen": True}, open(os.path.join(root, go.OPTIONS_FILE), "w"))
check(go.GameOptions.load(root).ask_engine_on_play, "si lo pediste a mano, se respeta")
print(f"\nTodas las pruebas pasaron ({ok}).")
