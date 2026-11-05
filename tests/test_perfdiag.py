"""Diagnóstico de tirones: cruce de cada tirón con lo que rexglue anotó.   python tests/test_perfdiag.py"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="reforge-perf-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
sys.path.insert(0, ROOT)
from reforge import ext_cpp, game, game_options as go, perfdiag  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise AssertionError(msg)
    ok += 1
    print("  ✔", msg)


LOG = """[2026-10-16 13:37:01.000] [info] [gpu] [t1] Translated 877 shaders from the storage in 36 milliseconds
[2026-10-16 13:37:05.100] [debug] [gpu] [t2] Generated pixel shader (31244b) - hash 1234ABCD12345678:
[2026-10-16 13:37:05.180] [debug] [gpu] [t3] Creating graphics pipeline with VS 0000000000000001, PS 1234ABCD12345678
[2026-10-16 13:37:05.200] [debug] [gpu] [t3] Creating graphics pipeline with VS 0000000000000002, PS 1234ABCD12345678
[2026-10-16 13:37:05.350] [warning] [core] [t9] [ReForge] Tirón de 250 ms
[2026-10-16 13:37:09.000] [debug] [krnl] [t4] [NtReadFile] handle=0x1 event=0x0
[2026-10-16 13:37:09.050] [warning] [core] [t9] [ReForge] Tirón de 70 ms
[2026-10-16 13:37:15.000] [warning] [core] [t9] [ReForge] Tirón de 60 ms
"""
lp = os.path.join(TMP, "g.log")
open(lp, "w", encoding="utf-8").write(LOG)
print("Cruce de tirones")
a = perfdiag.analyze_log(lp)
check(len(a["hitches"]) == 3 and a["debug"], "lee los 3 tirones y ve que el log es detallado")
check(a["hitches"][0][2].get("shaders") == 3, "el de 250 ms coincide con shaders y pipelines nuevos")
check(a["causes"] == {"shaders": 1, "disk": 1, "unknown": 1}, "clasifica cada tirón por su causa")
lines, main = perfdiag.report(lp)
check(main == "shaders" and any("250 ms" in ln for ln in lines) and any("RTV" in ln for ln in lines),
      "informe: causa principal shaders, con consejo")
check(game.analyze_runtime_log(lp)["kind"] == "clean", "los avisos de tirón no cuentan como error del juego")

print("Tiempos de fotograma")
exe = os.path.join(TMP, "g.exe")
open(os.path.join(TMP, perfdiag.FRAMETIMES_FILE), "w").write("frame_ms\n" + "\n".join(["12.1"] * 990 + ["250"] * 10))
st = perfdiag.frame_stats(os.path.join(TMP, perfdiag.FRAMETIMES_FILE))
check(st["frames"] == 1000 and 50 < st["avg_fps"] < 70 and st["low1_fps"] == 4.0 and st["over100"] == 10,
      "media de FPS, 1% más lentos y fotogramas largos")
check(any("1% más lentos" in ln for ln in perfdiag.report(lp, exe)[0]), "el informe los incluye")

print("Activar el diagnóstico")
o = go.GameOptions(diagnostics=True)
check(o.runtime_values().get("log_level") == "debug", "rexglue escribe el log detallado")
check("log_level" not in go.GameOptions().runtime_values(), "desactivado: log normal")
src = ext_cpp.EXT_SOURCE
check("class FramePacer" in src and "[ReForge] Tirón de" in src and "REX_HOOK(__imp__VdSwap, reforge::VdSwap_hook)" in src
      and "GuestPacer().Tick();" in src and "VdSwap_entry(a, b, c, d, e, f, g, h, i, j)" in src,
      "mide los fotogramas que entrega el juego (VdSwap), no los repintados de la ventana")

print("Pantallas de carga")
open(lp, "a", encoding="utf-8").write("[2026-10-16 13:37:20.000] [warning] [core] [t9] [ReForge] Tirón de 2400 ms\n")
a = perfdiag.analyze_log(lp)
check(len(a["hitches"]) == 3 and a["loads"] == 1, "una pausa de 2,4 s es una pantalla de carga, no un tirón")

print("Ajuste automático tras la partida")
root = os.path.join(TMP, "proj")
os.makedirs(root)
go.GameOptions(diagnostics=True).save(root)
LOG2 = "".join(f"[2026-10-16 14:00:0{i}.000] [debug] [apu] [t1] SDLCallback: no frames queued (silence)\n" for i in range(5))
lp2 = os.path.join(TMP, "g2.log")
open(lp2, "w", encoding="utf-8").write(LOG2)
ch = perfdiag.auto_tune(root, exe, lp2)
o = go.GameOptions.load(root)
check(o.audio_queue == 64 and any("audio" in c for c in ch), "audio entrecortado → más audio en cola")
check(not o.diagnostics and any("Diagnóstico completado" in c for c in ch), "diagnóstico hecho → se apaga solo")
check(o.runtime_values()["audio_maxqframes"] == 64, "se escribe audio_maxqframes")
LOG3 = "".join(f"[2026-10-16 14:01:{10+i}.000] [warning] [core] [t9] [ReForge] Tirón de 120 ms\n" for i in range(6))
open(lp2, "w", encoding="utf-8").write(LOG3)
ch = perfdiag.auto_tune(root, exe, lp2)
check(not go.GameOptions.load(root).diagnostics, "el diagnóstico automático no se repite (consume rendimiento)")
root_b = os.path.join(TMP, "proj_b")
os.makedirs(root_b)
go.GameOptions().save(root_b)
ch = perfdiag.auto_tune(root_b, exe, lp2)
check(go.GameOptions.load(root_b).diagnostics and ch, "muchos tirones sin causa conocida → la próxima partida se analiza")
o = go.GameOptions.load(root)
o.auto_tune = False
o.save(root)
check(perfdiag.auto_tune(root, exe, lp2) == [], "se puede desactivar")

print("FPS en vivo cada 5 s")
lp3 = os.path.join(TMP, "g3.log")
open(lp3, "w", encoding="utf-8").write("".join(
    f"[2026-10-16 15:00:{i:02d}.000] [info] [core] [t9] [ReForge] FPS {v} · peor 30 ms\n"
    for i, v in enumerate([80, 82, 81, 50, 80, 82, 81, 80, 81, 82, 80, 81, 79, 80])))
live = perfdiag.LiveLog(lp3)
st = live.feed()
check(st["fps"] == 80, "último valor de FPS")
check(st["fps_min"] == 50 and st["drops"] == 1, "mínimo y bajones (por debajo del 75 %)")
check("FPS" in perfdiag.live_text(st, 65), "se muestra en el estado en vivo")
rep = perfdiag.report(lp3, None)[0]
check(any("mediana 81" in ln and "mínimo 50" in ln and "1 bajón" in ln for ln in rep), "el informe resume los FPS")

print("Ritmo que el juego no aguanta → 60 estables")
from reforge import pc_enhance  # noqa: E402
pc_enhance.monitor_hz = lambda: 165
gdir = os.path.join(TMP, "gbuild")
os.makedirs(gdir)
gexe = os.path.join(gdir, "juego.exe")
open(gexe, "w").write("")
lp4 = os.path.join(gdir, "g4.log")
open(lp4, "w", encoding="utf-8").write("x\n")
frames = [12.1] * 3000 + ([12.1] * 9 + [24.2]) * 600          # 10 % de fotogramas a mitad de ritmo
open(os.path.join(gdir, perfdiag.FRAMETIMES_FILE), "w", encoding="utf-8").write(
    "frame_ms\n" + "\n".join(f"{v:.3f}" for v in frames) + "\n")
miss = perfdiag.pacing_misses(lp4, gexe, 82.5)
check(miss and miss[1] == "frames" and 0.08 < miss[0] < 0.12, "cuenta los fotogramas que fallan el vblank")
root_c = os.path.join(TMP, "proj_c")
os.makedirs(root_c)
go.GameOptions(fps_mode="auto", fps_unlocked=True).save(root_c)
ch = perfdiag.auto_tune(root_c, gexe, lp4)
oc = go.GameOptions.load(root_c)
check(oc.fps_cap == 60 and any("60 FPS constantes" in c for c in ch), "82,5 inestable → tope de 60")
check(oc.runtime_values()["video_mode_refresh_rate"] == 60.0, "se escribe 60 en la configuración")
check(not oc.diagnostics, "no lanza un diagnóstico pesado: la causa ya se sabe")
check(perfdiag.auto_tune(root_c, gexe, lp4) == [], "no se repite")
open(os.path.join(gdir, perfdiag.FRAMETIMES_FILE), "w", encoding="utf-8").write(
    "frame_ms\n" + "\n".join("12.100" for _ in range(9000)) + "\n")
check(perfdiag.pacing_misses(lp4, gexe, 82.5)[0] == 0, "estable: sin fallos")
os.utime(os.path.join(gdir, perfdiag.FRAMETIMES_FILE), (1, 1))
check(perfdiag.pacing_misses(lp4, gexe, 82.5) is None, "no usa los tiempos de un diagnóstico viejo")

print("Arranque, ráfagas y tirones sueltos")
lp5 = os.path.join(TMP, "g5.log")
L = []
for i in range(30):          # logos y menú a 30 FPS: muchos fotogramas de 50 ms
    L.append(f"[2026-10-16 16:00:{i:02d}.100] [warning] [core] [t9] [ReForge] Tirón de 51 ms")
L.append("[2026-10-16 16:00:30.000] [info] [core] [t9] [ReForge] FPS 30 · peor 51 ms")
L.append("[2026-10-16 16:00:40.000] [info] [core] [t9] [ReForge] FPS 60 · peor 20 ms")
for k in range(5):           # una ráfaga (vídeo) dentro del juego
    L.append(f"[2026-10-16 16:01:00.{k * 2}00] [warning] [core] [t9] [ReForge] Tirón de 50 ms")
for m in (2, 3, 4):           # tres tirones sueltos jugando
    L.append(f"[2026-10-16 16:0{m}:10.000] [warning] [core] [t9] [ReForge] Tirón de 140 ms")
L.append("[2026-10-16 16:05:35.000] [info] [core] [t9] [ReForge] FPS 60 · peor 140 ms")
open(lp5, "w", encoding="utf-8").write("\n".join(L) + "\n")
a = perfdiag.analyze_log(lp5)
check(a["startup"] == 30, "el arranque (logos, vídeos, menú) no cuenta como tirones")
check(a["slow"] == 5 and len(a["hitches"]) == 3, "las ráfagas aparte; quedan los tirones sueltos de verdad")
check(4.9 < a["minutes"] < 5.5, "minutos jugados desde que empieza el juego")
rep = "\n".join(perfdiag.report(lp5, None)[0])
check("Arranque" in rep and "mientras jugabas" in rep and "Activa el diagnóstico" not in rep,
      "el informe lo separa y no pide activar nada a mano")
st = perfdiag.LiveLog(lp5).feed()
check(st["hitches"] == 3 and st["fps_min"] == 60, "en vivo: los mismos 3 tirones y el mínimo desde que se juega")
root_d = os.path.join(TMP, "proj_d")
os.makedirs(root_d)
go.GameOptions(diag_cooldown=2).save(root_d)
LOG6 = "".join(f"[2026-10-16 17:0{i}:10.000] [warning] [core] [t9] [ReForge] Tirón de 120 ms\n" for i in range(8))
lp6 = os.path.join(TMP, "g6.log")
open(lp6, "w", encoding="utf-8").write(LOG6)
perfdiag.auto_tune(root_d, exe, lp6)
check(not go.GameOptions.load(root_d).diagnostics and go.GameOptions.load(root_d).diag_cooldown == 1,
      "tras un diagnóstico espera unas partidas")
perfdiag.auto_tune(root_d, exe, lp6)
perfdiag.auto_tune(root_d, exe, lp6)
check(go.GameOptions.load(root_d).diagnostics, "si los tirones siguen, vuelve a diagnosticar solo")

print("Reparar según la causa")
def dbg_log(path, cat_line, n=6):
    L = ["[2026-10-16 19:00:00.000] [debug] [gpu] [t1] inicio"]
    for i in range(n):
        L.append(f"[2026-10-16 19:0{i}:09.900] [debug] [gpu] [t2] {cat_line}")
        L.append(f"[2026-10-16 19:0{i}:10.000] [warning] [core] [t9] [ReForge] Tirón de 150 ms")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")
lp7 = os.path.join(TMP, "g7.log")
root_e = os.path.join(TMP, "proj_e")
os.makedirs(root_e)
go.GameOptions(render_path="rov", diagnostics=True).save(root_e)
dbg_log(lp7, "Creating graphics pipeline with VS 1, PS 2")
ch = perfdiag.auto_tune(root_e, exe, lp7)
oe = go.GameOptions.load(root_e)
check(oe.render_path == "rtv" and oe.allow_invalid_fetch and any("shaders" in c for c in ch),
      "tirones por shaders con la ruta Precisa → ruta Rápida")
go.GameOptions(perf_mode="fluido", resolution_scale=2, diagnostics=True).save(root_e)
dbg_log(lp7, "TextureCache: loading texture with 512x512")
perfdiag.auto_tune(root_e, exe, lp7)
check(go.GameOptions.load(root_e).resolution_scale == 1, "texturas con la caché al máximo → menos resolución interna")
go.GameOptions(readback_resolve=True).save(root_e)
open(lp7, "w", encoding="utf-8").write(LOG3)
ch = perfdiag.auto_tune(root_e, exe, lp7)
check(not go.GameOptions.load(root_e).readback_resolve and any("readback" in c for c in ch),
      "lecturas exactas + tirones → se desactivan solas")
go.GameOptions(resolution_scale=3, fps_mode="60").save(root_e)
open(lp7, "w", encoding="utf-8").write("".join(
    f"[2026-10-16 19:10:{i * 5:02d}.000] [info] [core] [t9] [ReForge] FPS {v} · peor 30 ms\n"
    for i, v in enumerate([60, 44, 45, 46, 44, 45, 47])))
ch = perfdiag.auto_tune(root_e, exe, lp7)
check(go.GameOptions.load(root_e).resolution_scale == 2, "no llega a 60 → baja la resolución interna")

print("Ruta de render según rendimiento")
fps_lines = lambda vals: "".join(f"[2026-10-16 19:10:{i * 5:02d}.000] [info] [core] [t9] [ReForge] FPS {v} · peor 30 ms\n"
                                 for i, v in enumerate(vals))
go.GameOptions(render_path="rov").save(root_e)
open(lp7, "w", encoding="utf-8").write(fps_lines([60, 38, 40, 37, 41, 39, 40]))
ch = perfdiag.auto_tune(root_e, exe, lp7)
oe = go.GameOptions.load(root_e)
check(oe.render_path == "rtv" and oe.path_trial == "rtv" and any("RTV" in c for c in ch), "ROV lento → se prueba RTV")
open(lp7, "w", encoding="utf-8").write(fps_lines([60, 60, 59, 60, 60, 60, 60]))
ch = perfdiag.auto_tune(root_e, exe, lp7)
check(go.GameOptions.load(root_e).path_trial == "" and any("confirmada" in c for c in ch), "RTV bien → confirmada")
go.GameOptions(render_path="rov", rov_required=True).save(root_e)
open(lp7, "w", encoding="utf-8").write(fps_lines([60, 38, 40, 37, 41, 39, 40]))
perfdiag.auto_tune(root_e, exe, lp7)
check(go.GameOptions.load(root_e).render_path == "rov", "si el juego necesita ROV no se cambia")
go.GameOptions(render_path="rov").save(root_e)
open(lp7, "w", encoding="utf-8").write("[2026-10-16 19:10:00.000] [warning] [core] [t1] [ReForge] Guardián: imagen "
                                       "sobreexpuesta (97% blanca) → readback_resolve=some\n")
perfdiag.auto_tune(root_e, exe, lp7)
check(go.GameOptions.load(root_e).render_path == "rtv", "imagen blanca en ROV → se prueba RTV")
print(f"\nTodas las pruebas pasaron ({ok}).")
