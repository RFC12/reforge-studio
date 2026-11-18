"""Ajustes de Windows que cambian cómo rinde un juego de Direct3D 12, y memoria libre del PC.

Solo se leen: cambiarlos afecta a todo el sistema (y algunos piden permisos de administrador), así que
ReForge informa y explica dónde se cambian, pero no los toca por su cuenta.
"""
import os
import subprocess
import sys

OK, WARN, INFO = "ok", "warn", "info"


def _reg(hive, key, value):
    """Valor del registro de Windows, o None."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        root = getattr(winreg, hive)
        with winreg.OpenKey(root, key) as k:
            return winreg.QueryValueEx(k, value)[0]
    except Exception:      # noqa: BLE001
        return None


def gpu_scheduling():
    """Planificación de GPU acelerada por hardware (HAGS): reduce la latencia de envío a la GPU."""
    v = _reg("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode")
    if v is None:
        return None
    if int(v) == 2:
        return (OK, "Planificación de GPU acelerada por hardware: activada.")
    return (WARN, "Planificación de GPU acelerada por hardware: desactivada. Activarla baja la latencia con "
                  "Direct3D 12. Windows → Configuración → Pantalla → Gráficos → Configuración "
                  "predeterminada (hay que reiniciar).")


def game_dvr():
    """La grabación en segundo plano de la Xbox Game Bar quita rendimiento."""
    v = _reg("HKEY_CURRENT_USER", r"System\GameConfigStore", "GameDVR_Enabled")
    pol = _reg("HKEY_LOCAL_MACHINE", r"SOFTWARE\Policies\Microsoft\Windows\GameDVR", "AllowGameDVR")
    if v is None and pol is None:
        return None
    on = (pol is None or int(pol) != 0) and (v is None or int(v) != 0)
    if not on:
        return (OK, "Grabación en segundo plano (Game DVR): desactivada.")
    return (WARN, "Grabación en segundo plano (Game DVR) activada: graba sin que se note y cuesta FPS. "
                  "Windows → Configuración → Juegos → Capturas → desactiva «Grabar lo sucedido».")


def game_mode():
    v = _reg("HKEY_CURRENT_USER", r"Software\Microsoft\GameBar", "AutoGameModeEnabled")
    if v is None:
        return None
    if int(v) == 1:
        return (OK, "Modo de juego de Windows: activado.")
    return (INFO, "Modo de juego de Windows desactivado. Activarlo da prioridad al juego: "
                  "Configuración → Juegos → Modo de juego.")


def power_plan():
    """Plan de energía activo (en «Economizador» la CPU no sube de frecuencia)."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, timeout=8,
                             text=True, errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:      # noqa: BLE001
        return None
    low = out.lower()
    if "economiz" in low or "power saver" in low or "ahorro" in low:
        return (WARN, "Plan de energía «Economizador»: la CPU no sube de frecuencia y el juego irá más lento. "
                      "Cámbialo a «Equilibrado» o «Alto rendimiento».")
    name = out.split(":", 1)[-1].strip() if ":" in out else out.strip()
    return (OK, f"Plan de energía: {name[:60] or 'equilibrado'}.")


def free_memory(need_mb=3500):
    """RAM libre ahora mismo frente a la que necesita un juego recompilado."""
    from .optimizer import _system_ram
    total, free = _system_ram()
    if not total:
        return None
    if free and free < need_mb:
        return (WARN, f"RAM libre: {free / 1024:.1f} GB de {total / 1024:.0f} GB. Queda poca para el juego; "
                      "cierra navegadores o programas pesados antes de jugar.")
    return (OK, f"RAM: {total / 1024:.0f} GB instalados, {free / 1024:.1f} GB libres.")


def report():
    """[(estado, texto)] de todo lo que se puede revisar en este PC."""
    rows = []
    for fn in (free_memory, gpu_scheduling, game_dvr, game_mode, power_plan):
        try:
            r = fn()
        except Exception as e:      # noqa: BLE001
            r = (INFO, f"No se pudo revisar ({e}).")
        if r:
            rows.append(r)
    return rows


# ---------------------------------------------------------------- montón (heap) del juego
# El CRT recompilado reserva su propio montón dentro de la memoria del juego (rexcrt_heap). Si un juego pide
# más de lo que cabe, rexglue lo anota en el registro y el juego se cierra. Estos avisos lo detectan para
# subir el tamaño: solo se sube, nunca se baja.
HEAP_ERRORS = ("rexcrt_heap: virtual heap allocation", "o1heapInit failed", "rexcrt_heap: memory is null",
               "o1heapAllocate", "rexcrt_RtlAllocateHeap: out of memory")
HEAP_STEPS = (512, 768, 1024)


def heap_exhausted(log_text):
    return any(e in log_text for e in HEAP_ERRORS)


def next_heap_size(current=0):
    """Siguiente tamaño de montón a probar, o None si ya está en el máximo."""
    for step in HEAP_STEPS:
        if step > int(current or 0):
            return step
    return None
