"""Mejoras para PC: lo que hace falta para que un juego del Xbox 360 se sienta como un juego moderno.

1. FPS desbloqueados. La mayoría de juegos del 360 se limitan ellos mismos a 30 FPS (esperan a 2 «vblank»
   por fotograma o tienen su propio limitador). Aunque el PC dé 200 FPS, el juego solo genera 30 imágenes
   distintas por segundo. Eso no lo arregla el runtime: hay que cambiar el código del juego. La base de datos
   de Xenia Canary trae parches «Unlock FPS» / «60 FPS» probados para cientos de juegos; ReForge los integra
   en el código recompilado.
2. Correcciones gráficas de la misma base de datos («… Fix»: sombreado negro por el MSAA, streaming de
   texturas…) y quitar el desenfoque de movimiento, que a más FPS deja estelas al mover la cámara o disparar.
3. Ritmo de fotogramas (fps_mode en GameOptions): en rexglue «vsync» marca el ritmo del «vblank» del Xbox 360
   (la señal con la que los juegos se sincronizan). Activado: 60 por segundo (o los Hz que se elijan con
   video_mode_refresh_rate). Desactivado: 1000 por segundo, sin límite. La presentación en tu monitor sin
   desgarros (tearing) la controla d3d12_allow_variable_refresh_rate_and_tearing.
"""
import re
import sys

from . import cheats

FPS_RE = re.compile(r"(unlock(ed)?\s*(fps|frame\s*rate|framerate)|uncap(ped)?|fps\s*uncap|\b60\s*fps\b|"
                    r"\b120\s*fps\b|high\s*(fps|frame\s*rate)|frame\s*rate\s*unlock|variable\s*frame)", re.I)
NOT_FPS_RE = re.compile(r"(show|display|counter|graph|overlay|osd|meter|lock\s+to|cap\s+to|30\s*fps|cutscene)", re.I)
FPS_COMPANION_RE = re.compile(r"(fps|frame\s*rate|framerate|delta|game\s*speed|physics).*(fix)|fix.*(fps|speed)", re.I)
FIX_RE = re.compile(r"\bfix(es|ed)?\b", re.I)
NOT_FIX_RE = re.compile(r"(hash|check|crash\s*handler|cheat|debug|dev\s*menu|upscal|resolution|ultrawide|aspect|"
                        r"option\s*b)", re.I)
UPSCALE_FIX_RE = re.compile(r"upscal", re.I)
MOTION_BLUR_RE = re.compile(r"(disable|remove|no)\s+motion\s*blur", re.I)

FPS_MODES = [
    ("auto", "Automático · ritmo exacto para tu monitor (recomendado)"),
    ("60", "60 FPS con VSync"),
    ("monitor", "Frecuencia de tu monitor con VSync (experimental)"),
    ("unlimited", "Sin límite (VSync desactivado · puede haber desgarros)"),
]


def is_fps_patch(name):
    return bool(FPS_RE.search(name)) and not NOT_FPS_RE.search(name)


def unlocks_framerate(name):
    """Parche que quita el límite (no los que fijan 60: con esos el ritmo se queda en 60)."""
    return is_fps_patch(name) and not re.search(r"\b60\s*fps\b", name, re.I)


def classify(name):
    """'fps', 'fps_fix', 'fix', 'upscale_fix', 'motion_blur' o ''."""
    if is_fps_patch(name):
        return "fps"
    if FPS_COMPANION_RE.search(name) and not NOT_FPS_RE.search(name):
        return "fps_fix"
    if MOTION_BLUR_RE.search(name):
        return "motion_blur"
    if FIX_RE.search(name) and UPSCALE_FIX_RE.search(name) and not re.search(r"option\s*[b-z]\b", name, re.I):
        return "upscale_fix"
    if FIX_RE.search(name) and not NOT_FIX_RE.search(name):
        return "fix"
    return ""


def _fps_rank(name, fps_mode):
    n = name.lower()
    if fps_mode == "60":
        order = ("60 fps", "unlock", "uncap", "120")
    else:
        order = ("unlock", "uncap", "120", "60 fps")
    for i, k in enumerate(order):
        if k in n:
            return i
    return len(order)


def recommended(patches, scale=1, fps_mode="60", motion_blur=True):
    """Parches recomendados para PC entre `patches` ([Patch] o [(archivo, Patch)]). Devuelve [Patch]:
    un solo parche de FPS (y sus correcciones), correcciones gráficas y, si se pide, sin desenfoque."""
    ps = [p[1] if isinstance(p, tuple) else p for p in patches]
    out, seen = [], set()
    fps = sorted((p for p in ps if classify(p.name) == "fps"), key=lambda p: _fps_rank(p.name, fps_mode))
    if fps:
        out.append(fps[0])
    for p in ps:
        c = classify(p.name)
        if c == "fps_fix" and fps:
            out.append(p)
        elif c == "fix":
            out.append(p)
        elif c == "upscale_fix" and int(scale or 1) > 1:
            out.append(p)
        elif c == "motion_blur" and motion_blur:
            out.append(p)
    res = []
    for p in out:
        if p.name not in seen:
            seen.add(p.name)
            res.append(p)
    return res


def available_for_exe(exe, title_id):
    """[(archivo, Patch)] de la base de datos para la versión exacta del juego compilado ([] si no se sabe)."""
    info = cheats.read_module_info(exe) if exe else {}
    h = info.get("hash", "")
    title_id = title_id or info.get("title_id", "")
    if not (h and title_id):
        return []
    return cheats.patches_for(title_id, h)


def describe(sel):
    """Texto corto de lo que hacen las mejoras elegidas."""
    kinds = {classify(p.name) for p in sel}
    parts = []
    if "fps" in kinds:
        parts.append("FPS desbloqueados")
    if kinds & {"fix", "upscale_fix", "fps_fix"}:
        parts.append("correcciones gráficas")
    if "motion_blur" in kinds:
        parts.append("sin desenfoque de movimiento (estelas)")
    return ", ".join(parts)


def apply_recommended(root, exe, title_id, options=None):
    """Añade las mejoras recomendadas a los trucos ya activos. Devuelve (parches_nuevos, hay_que_recompilar)."""
    from .game_options import GameOptions
    o = options or GameOptions.load(root)
    avail = available_for_exe(exe, title_id)
    if not avail:
        return [], False
    rec = recommended(avail, o.resolution_scale, o.frame_mode())
    state = cheats.cheats_state(root) or {}
    active = set(state.get("patches", []))
    new = [p for p in rec if p.name not in active]
    if not new:
        return [], False
    sel = [p for _f, p in avail if p.name in active] + new
    changed = cheats.apply_cheats(root, sel)
    o.pc_enhanced = True
    o.save(root)
    return new, changed


# ---------------------------------------------------------------- monitor
def monitor_hz():
    """Frecuencia actual del monitor principal (Hz); 60 si no se puede saber."""
    if sys.platform == "win32":
        try:
            import ctypes
            user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
            hdc = user32.GetDC(0)
            try:
                hz = int(gdi32.GetDeviceCaps(hdc, 116))      # VREFRESH
            finally:
                user32.ReleaseDC(0, hdc)
            if 24 <= hz <= 500:
                return hz
        except Exception:      # noqa: BLE001
            pass
    return 60


def paced_rate(hz, unlocked=True):
    """Ritmo del juego que encaja exacto con el monitor (cada imagen dura el mismo número de refrescos).
    60 en un monitor de 165 Hz son 2,75 refrescos por imagen: unas duran 3 y otras 2 → micro tirones aunque
    los FPS sean estables. 165/2 = 82,5 FPS encaja exacto. Solo se sube de 60 si el juego tiene los FPS
    desbloqueados (un juego bloqueado iría más rápido de lo normal)."""
    hz = float(hz or 60)
    if 58.0 <= hz <= 61.0:
        return round(hz, 3)            # 59,94 Hz, 60 Hz…: el mismo ritmo exacto que el monitor
    if not unlocked or hz <= 61:
        return 60.0
    cands = [hz / k for k in range(1, 9)]
    up = [r for r in cands if 59.5 <= r <= 100.5]
    if up:
        return round(min(up), 3)
    return 60.0


def frame_values(fps_mode, unlocked=False, hz=None, cap=0.0):
    """Cvars del ritmo de fotogramas. En rexglue «vsync» es el ritmo del vblank del Xbox 360 (la señal que
    usan los juegos para sincronizarse); la presentación en tu monitor la decide el driver (G-Sync/FreeSync
    elimina el resto de tirones). unlocked: el juego tiene un parche de FPS desbloqueados."""
    mode = fps_mode or "auto"
    if mode == "unlimited":
        return {"vsync": False, "d3d12_allow_variable_refresh_rate_and_tearing": True}
    # La presentación queda como la trae rexglue (permite G-Sync/FreeSync): forzarla sin desgarros
    # anulaba el refresco variable y añadía tirones.
    if mode == "60":
        rate = 60.0
    elif mode == "monitor":
        rate = float(hz or monitor_hz())
    else:
        rate = paced_rate(hz or monitor_hz(), unlocked)
        if cap and cap >= 30:
            rate = min(rate, float(cap))   # el Taller vio que el juego no aguanta más: ritmo estable sin bajones
    return {"vsync": True, "video_mode_refresh_rate": rate}
