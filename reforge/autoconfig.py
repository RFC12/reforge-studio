"""Autoconfiguración al abrir el juego (cualquier juego, desde el Taller, la Biblioteca o el lanzador).

Antes de cada partida se revisa el PC tal como está ahora (GPU y VRAM, hilos de la CPU, frecuencia del monitor)
y se escribe la configuración más rápida que el juego ha demostrado aguantar: ritmo de fotogramas, caché de
texturas, hilos de pipelines, audio, consultas de oclusión y lo que el ajuste automático aprendió en partidas
anteriores. No pregunta nada: lo que se elija a mano en 🎮 Opciones / ⚡ Optimizar se respeta.
"""
import os
import time

HW_MAX_AGE = 7 * 24 * 3600      # la detección de hardware se repite cada semana (o si cambia la GPU)


def refresh_hardware():
    """Hardware actual (vuelve a detectarlo si la caché es vieja o la GPU cambió)."""
    from .optimizer import _gpu_from_registry, cached_hardware, detect_hardware, hardware_path
    hw = cached_hardware()
    try:
        old = time.time() - os.path.getmtime(hardware_path()) > HW_MAX_AGE
    except OSError:
        old = True
    try:
        gpus = _gpu_from_registry()
        gpu_now = max(gpus, key=lambda g: g[1])[0] if gpus else ""
    except Exception:      # noqa: BLE001
        gpu_now = ""
    if old or (gpu_now and gpu_now != hw.get("gpu")) or int(hw.get("cpu_threads") or 0) != (os.cpu_count() or 0):
        hw = detect_hardware()
    return hw


def summary(o, hw, values):
    """Una línea con lo que se aplicó."""
    from . import game
    parts = []
    gpu = hw.get("gpu") or "GPU"
    vram = int(hw.get("vram_mb") or 0)
    parts.append(f"{gpu}{f' {vram // 1024} GB' if vram >= 1024 else ''} · {hw.get('cpu_threads', '?')} hilos")
    if values.get("vsync") is False:
        parts.append("FPS sin límite")
    elif values.get("video_mode_refresh_rate"):
        parts.append(f"{float(values['video_mode_refresh_rate']):g} FPS"
                     + (" estables" if o.fps_cap else ""))
    perf = {"fluido": "Fluido", "calidad": "Calidad", "off": "sin optimizador"}.get(o.perf_mode, o.perf_mode)
    parts.append(f"optimizador {perf}")
    if values.get("d3d12_pipeline_creation_threads"):
        parts.append(f"{values['d3d12_pipeline_creation_threads']} hilos para shaders")
    if values.get("audio_maxqframes"):
        parts.append(f"audio {values['audio_maxqframes']}")
    if int(o.resolution_scale or 1) > 1:
        parts.append(f"resolución {o.resolution_scale}×")
    parts.append(f"código {game.CODEGEN_LEVEL_TITLES.get(o.codegen_level(), '')}")
    return " · ".join(parts)


def apply(root, exe):
    """Revisa el PC y escribe la configuración del juego. Devuelve el texto del resumen ('' si no se pudo)."""
    from .game_options import GameOptions, write_runtime_config
    try:
        hw = refresh_hardware()
        o = GameOptions.load(root)
        if o.resolution_auto:
            # Escalado universal: el juego se dibuja por dentro a 2× o 3× (supermuestreo real, mejor que
            # cualquier filtro de escalado) si tu tarjeta puede; si un juego no llega a sus FPS, el ajuste
            # automático la baja y no se vuelve a subir para ese juego.
            from .optimizer import recommended_scale
            want = recommended_scale(hw)
            if o.scale_ceiling:
                want = min(want, int(o.scale_ceiling))
            if want != int(o.resolution_scale or 1):
                o.resolution_scale = want
                o.save(root)
        write_runtime_config(exe, o)
        return summary(o, hw, o.runtime_values())
    except Exception:      # noqa: BLE001
        return ""
