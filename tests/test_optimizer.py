"""Optimizador de rendimiento y asistente de modo de imagen.   python tests/test_optimizer.py"""
import os
import stat
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-optim-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)

from reforge import optimizer as opt  # noqa: E402
from reforge.game_options import GameOptions, runtime_config_path, write_runtime_config  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


print("Ajustes según el equipo")
rtx = {"gpu": "NVIDIA GeForce RTX 5060 Ti", "vram_mb": 16311, "cpu_threads": 12, "avx2": True}
v = opt.tuned_values(rtx, "fluido")
check((v["texture_cache_memory_limit_soft"], v["texture_cache_memory_limit_hard"]) == (2048, 4096),
      "16 GB de VRAM → caché de texturas 2048/4096 MB")
check(v["d3d12_pipeline_creation_threads"] == 6 and v["async_shader_compilation"] is True,
      "12 hilos → 6 para shaders (el resto para el juego y el audio), compilación en segundo plano")
check(v["audio_maxqframes"] == 32, "32 fotogramas de audio en cola (sin sonido estático al cargar)")
check(opt.tuned_values(rtx, "sin_parpadeo")["async_shader_compilation"] is False, "«Sin parpadeo» espera a los shaders")
check(opt.tuned_values({"vram_mb": 0, "cpu_threads": 4}, "fluido")["texture_cache_memory_limit_soft"] == 384,
      "VRAM desconocida → valores de rexglue")
check(opt.tuned_values(rtx, "off") == {}, "desactivado → no toca nada")

print("Detección")
log = os.path.join(TMP, "g.log")
open(log, "w").write("[info] [gpu] [t1] DXGI adapter: NVIDIA GeForce RTX 5060 Ti (vendor 0x10DE, device 0x2D04)\n")
hw = opt.detect_hardware(log)
check(hw["cpu_threads"] >= 1 and (hw["gpu"] == "NVIDIA GeForce RTX 5060 Ti" or sys.platform == "win32"),
      "lee la GPU del log del juego si el registro no la da")
check(opt.cached_hardware() == hw, "guarda la detección para no repetirla en cada arranque")

print("Se aplica al juego")
exe = os.path.join(TMP, "game", "build", "angrybirdstrilogy.exe")
os.makedirs(os.path.dirname(exe))
open(exe, "w").write("")
opt.detect_hardware.__globals__["_gpu_from_registry"] = lambda: [("NVIDIA GeForce RTX 5060 Ti", 16311)]
opt.detect_hardware.__globals__["_system_ram"] = lambda: (32768, 20000)   # PC de referencia: 32 GB
opt.detect_hardware()
o = GameOptions()
write_runtime_config(exe, o)
t = open(runtime_config_path(exe), encoding="utf-8").read()
check("texture_cache_memory_limit_soft = 2048" in t and "async_shader_compilation = true" in t
      and "d3d12_queue_priority = 1" in t, "escribe la caché de texturas, los shaders y la prioridad")
check(opt._texture_budget(16311, 8192)[1] == 1024 and opt._texture_budget(16311, 32768)[1] == 4096,
      "con poca RAM la caché de texturas se limita aunque sobre VRAM")
check(opt._texture_budget(16311, 0)[1] == 4096, "sin dato de RAM manda la VRAM")
open(os.path.join(os.path.dirname(exe), "rexgpu-xenos.dll"), "wb").write(
    b"MZ texture_cache_memory_limit_soft\0texture_cache_memory_limit_hard\0async_shader_compilation\0")
write_runtime_config(exe, o)
t = open(runtime_config_path(exe), encoding="utf-8").read()
check("texture_cache_memory_limit_soft" in t and "d3d12_pipeline_creation_threads" not in t,
      "omite lo que el plugin del juego no trae")
os.remove(os.path.join(os.path.dirname(exe), "rexgpu-xenos.dll"))
o.perf_mode = "off"
write_runtime_config(exe, o)
check("texture_cache_memory_limit" not in open(runtime_config_path(exe), encoding="utf-8").read(),
      "desactivarlo vuelve a los valores de rexglue")
check(opt.launch_flags(GameOptions()) == (0x8000 if sys.platform == "win32" else 0),
      "en Windows el juego arranca con prioridad «por encima de lo normal»")

print("Modos de imagen")
for key, _t, path, rb, inv in opt.RENDER_LADDER:
    g = GameOptions()
    g.apply_preset(key)
    check((g.render_path, g.readback_resolve, g.allow_invalid_fetch) == (path, rb, inv) and g.preset() == key,
          f"modo «{key}»")

print("Modo conocido por juego")
hp = os.path.join(TMP, "ben10")
os.makedirs(hp)
real_hint = opt.title_hint
opt.title_hint = lambda root: ("rov_inv", "Ben 10 Omniverse") if root == hp else None
msg = opt.apply_title_hint(hp)
check(GameOptions.load(hp).preset() == "rov_inv" and "Preciso" in msg, "Ben 10 Omniverse arranca en ROV + datos no válidos")
g = GameOptions.load(hp)
g.apply_preset("rtv")
g.save(hp)
check(opt.apply_title_hint(hp) == "" and GameOptions.load(hp).preset() == "rtv", "no pisa un modo elegido por el usuario")
opt.title_hint = real_hint
check(opt.RENDER_HINTS["44500802"][0] == "rov_inv", "perfil registrado por Title ID")

if sys.platform == "win32":
    print(f"\nTodas las pruebas pasaron ({ok}).  (asistente con juego simulado omitido en Windows)")
    sys.exit(0)

print("Asistente con un juego simulado")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
app = QApplication.instance() or QApplication([])
from reforge.core import AppConfig  # noqa: E402
from reforge.optimizer_ui import AssistantDialog  # noqa: E402
QMessageBox.information = staticmethod(lambda *a, **k: None)
proj = os.path.join(TMP, "proj")
os.makedirs(os.path.join(proj, "assets"))
os.makedirs(os.path.join(proj, "build"))
open(os.path.join(proj, "assets", "default.xex"), "wb").write(b"XEX2")
sim = os.path.join(proj, "build", "angrybirdstrilogy")
open(sim, "w").write(f"#!{sys.executable}\nimport time\ntime.sleep(120)\n")
os.chmod(sim, os.stat(sim).st_mode | stat.S_IEXEC)
start = GameOptions()
start.apply_preset("compat")
start.save(proj)
d = AssistantDialog(None, AppConfig(), proj, sim)
app.processEvents()
time.sleep(0.3)
app.processEvents()
first = d.proc
check(d.i == 0 and first is not None and first.poll() is None and "Rápido (RTV)" in d.title.text(),
      "empieza por el modo más rápido y abre el juego")
check('render_target_path_d3d12 = "rtv"' in open(runtime_config_path(sim), encoding="utf-8").read(),
      "el juego se abre con ese modo")
d.next_mode()
time.sleep(0.3)
app.processEvents()
check(first.poll() is not None and d.i == 1 and d.proc.poll() is None, "«Negra o rota» cierra el juego y prueba el siguiente")
d.accept_mode()
g = GameOptions.load(proj)
check(g.preset() == "rtv_inv" and d.proc.poll() is None, "«Se ve bien» guarda ese modo y deja el juego abierto")
d.proc.kill()
start.save(proj)
d2 = AssistantDialog(None, AppConfig(), proj, sim)
app.processEvents()
time.sleep(0.3)
d2.reject()
check(GameOptions.load(proj).preset() == "compat" and d2.proc is None, "cancelar devuelve la configuración anterior")

print(f"\nTodas las pruebas pasaron ({ok}).")
