"""Optimizador de rendimiento de los juegos recompilados.

Ajusta las opciones reales del runtime de rexglue (verificadas en rexgpu-xenos.dll / rexruntime.dll):
* caché de texturas según la VRAM y la RAM del PC (menos texturas que se descartan y recargan → menos
  parpadeo y tirones, sin pasarse si el equipo tiene poca memoria),
* hilos de creación de pipelines según la CPU y compilación de shaders en segundo plano,
* prioridad de la cola gráfica,
y al lanzar: prioridad «por encima de lo normal» y preferencia de GPU de alto rendimiento.
"""
import json
import os
import re
import sys

from .core import config_dir

PERF_MODES = [
    ("fluido", "Fluido (recomendado)",
     "Sin pausas: los shaders nuevos se compilan en segundo plano. La primera vez que aparece algo nuevo "
     "puede parpadear un instante; la caché lo recuerda y no vuelve a pasar."),
    ("sin_parpadeo", "Sin parpadeo",
     "Espera a cada shader nuevo antes de dibujarlo: nunca parpadea, pero la primera vez que aparece algo "
     "nuevo hay una pausa breve."),
    ("off", "Desactivado", "Valores por defecto de rexglue."),
]

PERF_CVARS = ("async_shader_compilation", "d3d12_pipeline_creation_threads", "texture_cache_memory_limit_soft",
              "texture_cache_memory_limit_hard", "texture_cache_memory_limit_render_to_texture",
              "texture_cache_memory_limit_soft_lifetime", "d3d12_queue_priority",
              "gpu_debug_markers", "kernel_debug_monitor")

# Modos de imagen del asistente, del más rápido al más pesado: (clave, título, ruta, lectura CPU, datos no válidos)
RENDER_LADDER = [
    ("rtv", "Rápido (RTV)", "rtv", False, False),
    ("rtv_inv", "Rápido + datos no válidos", "rtv", False, True),
    ("rov_inv", "Preciso (ROV) + datos no válidos", "rov", False, True),
    ("rtv_rb", "Rápido + lectura de texturas en CPU", "rtv", True, True),
    ("compat", "Compatibilidad máxima (el más lento)", "rov", True, True),
]


# Modo de imagen conocido por juego (Title ID): se aplica al preparar el proyecto si aún no se eligió uno.
RENDER_HINTS = {
    "44500802": ("rov_inv", "Ben 10 Omniverse: en RTV el suelo sale con bloques negros y rayas"),
    "41560914": ("rtv", "Call of Duty: Advanced Warfare: en ROV la imagen sale blanca y va a ~40 FPS; en RTV, "
                        "60 FPS y bien"),
}


def title_hint(root):
    """(modo, motivo) conocido para el juego del proyecto, o None."""
    try:
        from .xex import read_xex_info
        tid = read_xex_info(os.path.join(root, "assets", "default.xex")).get("title_id", "").upper()
    except Exception:      # noqa: BLE001
        return None
    return RENDER_HINTS.get(tid)


def apply_title_hint(root):
    """Aplica el modo conocido si el juego todavía usa el automático. Devuelve el mensaje o ''."""
    from .game_options import GameOptions
    hint = title_hint(root)
    if not hint:
        return ""
    o = GameOptions.load(root)
    if o.preset() != "auto":
        return ""
    o.apply_preset(hint[0])
    if o.render_path == "rov":
        o.rov_required = True       # caso conocido: no se cambia a RTV por rendimiento
    o.save(root)
    return f"Modo de imagen para este juego: {dict((k, t) for k, t, *_r in RENDER_LADDER)[hint[0]]} ({hint[1]})."


def hardware_path():
    return os.path.join(config_dir(), "hardware.json")


def _gpu_from_registry():
    """[(nombre, vram_mb)] de las tarjetas de vídeo (Windows; clave de clase de adaptadores de pantalla)."""
    out = []
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            for i in range(64):
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(k, sub) as s:
                        name = winreg.QueryValueEx(s, "DriverDesc")[0]
                        mem = 0
                        for val in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                            try:
                                v = winreg.QueryValueEx(s, val)[0]
                                mem = int.from_bytes(v, "little") if isinstance(v, (bytes, bytearray)) else int(v)
                                break
                            except OSError:
                                continue
                        out.append((str(name), mem // (1024 * 1024)))
                except OSError:
                    continue
    except Exception:      # noqa: BLE001
        pass
    return out


def _avx2():
    try:
        if sys.platform == "win32":
            import ctypes
            return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))   # PF_AVX2_INSTRUCTIONS_AVAILABLE
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            return " avx2" in f.read()
    except Exception:      # noqa: BLE001
        return False


def _system_ram():
    """(RAM total, RAM libre) en MB; (0, 0) si no se puede leer."""
    try:
        if sys.platform == "win32":
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            m = _MS()
            m.dwLength = ctypes.sizeof(_MS)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return 0, 0
            return int(m.ullTotalPhys // (1 << 20)), int(m.ullAvailPhys // (1 << 20))
        total = free = 0
        with open("/proc/meminfo", encoding="utf-8", errors="replace") as f:
            for ln in f:
                if ln.startswith("MemTotal:"):
                    total = int(ln.split()[1]) // 1024
                elif ln.startswith("MemAvailable:"):
                    free = int(ln.split()[1]) // 1024
        return total, free
    except Exception:      # noqa: BLE001
        return 0, 0


def free_ram_mb():
    """RAM libre ahora mismo, en MB (0 si no se puede leer)."""
    return _system_ram()[1]


def detect_hardware(game_log=""):
    """GPU (nombre y VRAM), hilos de CPU y AVX2. Si el registro no da la GPU, se lee del log del juego."""
    gpus = _gpu_from_registry()
    name, vram = ("", 0)
    if gpus:
        name, vram = max(gpus, key=lambda g: g[1])
    if not name and game_log and os.path.isfile(game_log):
        m = re.search(r"DXGI adapter: (.+?) \(vendor", open(game_log, encoding="utf-8", errors="replace").read())
        if m:
            name = m.group(1)
    ram_mb, ram_free_mb = _system_ram()
    hw = {"gpu": name or "desconocida", "vram_mb": int(vram), "cpu_threads": os.cpu_count() or 4,
          "avx2": _avx2(), "ram_mb": ram_mb, "ram_free_mb": ram_free_mb}
    try:
        os.makedirs(config_dir(), exist_ok=True)
        with open(hardware_path(), "w", encoding="utf-8") as f:
            json.dump(hw, f, indent=2)
    except OSError:
        pass
    return hw


def cached_hardware():
    try:
        with open(hardware_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:      # noqa: BLE001
        return detect_hardware()


def _texture_budget(vram, ram):
    """(soft, hard, render-a-textura) en MB para la caché de texturas.

    La caché vive en la VRAM, pero cuando la VRAM se llena el driver la desborda a la RAM del PC: por eso el
    presupuesto se limita también por la RAM instalada (la octava parte como mucho). En un equipo con 32 GB no
    cambia nada; en uno de 8 GB evita que el juego empiece a tirar de disco y a dar tirones.
    """
    if vram >= 12000:
        soft, hard, rtt = 2048, 4096, 128
    elif vram >= 8000:
        soft, hard, rtt = 1536, 3072, 96
    elif vram >= 6000:
        soft, hard, rtt = 1024, 2048, 64
    elif vram >= 4000:
        soft, hard, rtt = 768, 1536, 48
    else:                       # VRAM desconocida o pequeña: valores de rexglue
        soft, hard, rtt = 384, 768, 24
    if ram >= 1024:             # RAM conocida: no dejar que el desborde se coma el PC
        cap = max(768, ram // 8)
        if cap < hard:
            k = cap / hard
            soft, hard, rtt = max(384, int(soft * k)), cap, max(24, int(rtt * k))
    return soft, hard, rtt


def tuned_values(hw, mode):
    """Valores del runtime para el hardware y el modo elegidos ({} si el optimizador está desactivado)."""
    if mode == "off":
        return {}
    vram = int(hw.get("vram_mb") or 0)
    ram = int(hw.get("ram_mb") or 0)
    threads = int(hw.get("cpu_threads") or 4)
    soft, hard, rtt = _texture_budget(vram, ram)
    return {
        "async_shader_compilation": mode != "sin_parpadeo",
        # La mitad de los hilos: con casi todos compilando pipelines a la vez (al cargar o con efectos nuevos)
        # el juego y el audio se quedaban sin CPU → tirones y sonido estático (medido en Gears of War 2).
        "d3d12_pipeline_creation_threads": max(2, min(8, threads // 2)),
        "texture_cache_memory_limit_soft": soft,
        "texture_cache_memory_limit_hard": hard,
        "texture_cache_memory_limit_render_to_texture": rtt,
        "texture_cache_memory_limit_soft_lifetime": 120 if hard >= 2048 else 30,
        "d3d12_queue_priority": 1,
        # Más audio en cola: evita el sonido entrecortado/estático mientras el juego carga (CPU ocupada).
        "audio_maxqframes": 32,
        # Marcas de depuración de la GPU: no hacen falta para jugar y cuestan trabajo por cada dibujado.
        "gpu_debug_markers": False,
        "kernel_debug_monitor": False,
    }


def describe(hw, mode):
    v = tuned_values(hw, mode)
    if not v:
        return "Optimizador desactivado: valores por defecto de rexglue."
    vram = f"{hw['vram_mb'] / 1024:.0f} GB" if hw.get("vram_mb") else "VRAM desconocida"
    ram = f" · {hw['ram_mb'] / 1024:.0f} GB de RAM" if hw.get("ram_mb") else ""
    return (f"{hw.get('gpu')} ({vram}) · {hw.get('cpu_threads')} hilos de CPU{ram}\n"
            f"Caché de texturas {v['texture_cache_memory_limit_soft']}/{v['texture_cache_memory_limit_hard']} MB "
            f"(render a textura {v['texture_cache_memory_limit_render_to_texture']} MB) · "
            f"{v['d3d12_pipeline_creation_threads']} hilos para shaders · "
            f"shaders {'en segundo plano' if v['async_shader_compilation'] else 'antes de dibujar'}")


# ---------------------------------------------------------------- al lanzar el juego
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000


def launch_flags(options):
    if sys.platform == "win32" and getattr(options, "perf_mode", "fluido") != "off":
        return ABOVE_NORMAL_PRIORITY_CLASS
    return 0


def set_gpu_preference(exe, high=True):
    """Windows → Configuración de gráficos: «Alto rendimiento» para el .exe del juego (por usuario)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\DirectX\UserGpuPreferences") as k:
            if high:
                winreg.SetValueEx(k, os.path.abspath(exe), 0, winreg.REG_SZ, "GpuPreference=2;")
            else:
                try:
                    winreg.DeleteValue(k, os.path.abspath(exe))
                except OSError:
                    pass
        return True
    except OSError:
        return False


def shader_cache_info(title_id, name):
    """Tamaño de la caché persistente de shaders del juego (Documentos/<juego>/cache/shaders)."""
    home = os.path.expanduser("~")
    base = os.path.join(home, "Documents", name, "cache", "shaders", "shareable")
    files = []
    if os.path.isdir(base):
        for f in os.listdir(base):
            if not title_id or f.upper().startswith(title_id.upper()):
                files.append((f, os.path.getsize(os.path.join(base, f))))
    return base, files


# ---------------------------------------------------------------- calidad de imagen
# DLSS/FSR 2 temporales necesitan vectores de movimiento y desplazamiento de cámara por fotograma que los
# juegos de Xbox 360 no generan; lo que sí da nitidez real es dibujar a más resolución interna
# (draw_resolution_scale: supermuestreo) con filtrado anisotrópico 16×.
QUALITY_LEVELS = [
    (1, "Rendimiento · 1× (720p interno)", "Resolución original del Xbox 360. Lo más rápido."),
    (2, "Equilibrada · 2× (1440p interno)", "Cuatro veces más píxeles: bordes y texturas mucho más nítidos."),
    (3, "Máxima · 3× (2160p interno)", "Nueve veces más píxeles (4K interno). Pide una GPU potente."),
]


def is_nvidia_rtx(hw):
    return "rtx" in str(hw.get("gpu", "")).lower()


def is_integrated(hw):
    g = str(hw.get("gpu", "")).lower()
    return any(k in g for k in ("intel(r) uhd", "intel(r) hd", "iris", "radeon(tm) graphics", "vega 8",
                                "microsoft basic")) or int(hw.get("vram_mb") or 0) < 2000


def recommended_scale(hw):
    """Escala interna recomendada para la GPU (1, 2 o 3)."""
    vram = int(hw.get("vram_mb") or 0)
    if is_integrated(hw) or vram < 6000:
        return 1
    if vram >= 12000:
        return 3
    return 2


def nvidia_ai_tips(hw):
    """Funciones de IA del driver de NVIDIA que funcionan sin que el juego las integre."""
    g = str(hw.get("gpu", "")).lower()
    if "rtx" not in g:
        return ""
    tips = ["DLDSR (superresolución con IA): Panel de control de NVIDIA → Administrar configuración 3D → "
            "Factores DSR → «DL 1,78×» o «DL 2,25×». Luego elige esa resolución en Windows o en el juego a "
            "pantalla completa."]
    if re.search(r"rtx\s*50\d\d", g) or re.search(r"rtx\s*40\d\d", g):
        tips.append("Smooth Motion (generación de fotogramas del driver): NVIDIA App → Gráficos → Configuración "
                    "del programa → añade el .exe del juego → «Smooth Motion» activado. Duplica los FPS "
                    "mostrados; úsalo con VSync desactivado.")
    return "\n\n".join(tips)


def open_nvidia_app():
    """Abre la NVIDIA App (o el Panel de control de NVIDIA). False si no se encuentra."""
    if sys.platform != "win32":
        return False
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    for p in (os.path.join(pf, "NVIDIA Corporation", "NVIDIA app", "CEF", "NVIDIA app.exe"),
              os.path.join(pf, "NVIDIA Corporation", "NVIDIA App", "CEF", "NVIDIA App.exe"),
              os.path.join(pf, "NVIDIA Corporation", "Control Panel Client", "nvcplui.exe")):
        if os.path.isfile(p):
            try:
                os.startfile(p)      # noqa: S606
                return True
            except OSError:
                continue
    try:
        os.startfile("shell:AppsFolder\\NVIDIACorp.NVIDIAControlPanel_56jybvy8sckqj!NVIDIACorp.NVIDIAControlPanel")
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- protección contra DXVK
# DXVK traduce Direct3D 8-11 a Vulkan; rexglue usa Direct3D 12 y carga dxgi.dll. Un dxgi.dll de DXVK junto
# al juego sustituye al de Windows y Direct3D 12 deja de arrancar (pantalla negra o cierre).
DXVK_DLLS = ("dxgi.dll", "d3d11.dll", "d3d10core.dll", "d3d9.dll", "d3d8.dll")
DXVK_QUARANTINE = "_dxvk_desactivado"


def _is_dxvk(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return False
    return b"DXVK" in data or b"dxvk" in data


def quarantine_dxvk(exe):
    """Aparta las DLL de DXVK de la carpeta del juego. Devuelve la lista de archivos movidos."""
    d = os.path.dirname(exe)
    moved = []
    for name in DXVK_DLLS:
        p = os.path.join(d, name)
        if os.path.isfile(p) and _is_dxvk(p):
            dst_dir = os.path.join(d, DXVK_QUARANTINE)
            os.makedirs(dst_dir, exist_ok=True)
            try:
                os.replace(p, os.path.join(dst_dir, name))
                moved.append(name)
            except OSError:
                pass
    if moved:
        try:
            with open(os.path.join(d, DXVK_QUARANTINE, "LEEME.txt"), "w", encoding="utf-8") as f:
                f.write("ReForge Studio apartó estas DLL de DXVK porque rompen los juegos de rexglue.\n"
                        "DXVK traduce Direct3D 8/9/10/11 a Vulkan; los juegos recompilados usan Direct3D 12\n"
                        "y su dxgi.dll sustituye al de Windows, así que Direct3D 12 no arranca.\n")
        except OSError:
            pass
    return moved
